# Mock ACP session contract experiment

This is an **original Python experiment**, informed by acpx's session design and the ACP specification. It runs only the bundled mock agent. It neither invokes nor installs acpx, a provider CLI, a model, a paid API, or an authentication flow. Nothing here is registered as a Review Hub production route or dependency.

The experiment tests the failure contract needed before considering a future acpx sidecar: bind a session precisely, distinguish local admission from prompt delivery, and avoid silently replacing or replaying uncertain work. A local mock passing these tests does not establish provider entitlement, actual session continuity, or an operating-system sandbox.

## Run it

From the repository root, using Python 3.11 or newer:

```powershell
python experimental/acpx/probe.py --allow-mock-command
python -m unittest tests.test_acpx_experiment -v
```

The probe creates a temporary synthetic project and SQLite ledger, obtains a mock session, repeats the same logical request without dispatching again, then reloads that exact session for a new synthetic request. Each required step must return successfully with the same nonempty session ID; failure stops later steps and produces a nonzero exit code. The reload is never called with a missing ID. The probe prints only the receipts reached and removes its temporary files. The explicit flag is required. No provider executable, arbitrary command, user prompt file, account token, or network endpoint can be selected through this probe.

`MockCommand.reviewed()` records the current Python executable and bundled agent source hashes. Both supplied paths must be absolute, and launch uses their verified canonical absolute paths so the subprocess working directory cannot redirect execution to a project-local shadow. Launch is restricted to those two exact paths with Python isolated mode (`-I`), no shell, and an environment containing only basic operating-system/locale variables. The hashes are rechecked immediately before launch. A hash records reviewed bytes; it does not establish that arbitrary code is trustworthy or create a sandbox. The mock intentionally reads its known fixture-control file and writes a method-only journal inside the synthetic project to exercise failures.

## Contract that is implemented

- **Exact identity:** the ledger binds a provider session ID to the canonical project directory, explicit local `mock:` account tag, `mock-acp` route, complete command, and reviewed executable/source hashes. A different project, account tag, route, command, or unknown session cannot reuse it. The account tag is caller-supplied scope metadata, never proof of authenticated account ownership.
- **Explicit creation or loading:** first use sends `initialize`, then `session/new`. Reuse requires an existing bound session and advertised `loadSession:true`, then sends `session/load` with that exact ID, directory, and no MCP servers. Unsupported or failed loading ends the attempt before the prompt. There is no automatic `session/new` fallback, history reconstruction, or prompt replay.
- **History separation:** bounded text notifications received during loading are checked for the same session but do not become the new turn's answer. The current subset uses ACP `session/load`; it does not implement the separate `session/resume` extension.
- **Denied capabilities:** initialization advertises no file read/write or terminal capability. Every permission request receives the ACP cancelled outcome, even when the mock offers only an allow option. Other client requests receive an error and terminate the turn. Unsupported tool/content/event families stop the experiment. The client performs no requested filesystem, shell, or network action.
- **Durable duplicate handling:** a request key binds the scope, selected session, and prompt hash. An identical repeat returns its saved receipt, including an in-progress or uncertain receipt; changed inputs with the same key are rejected. A SQLite transaction admits at most one active attempt per exact scope. This is local experiment behavior, not an assertion that ACP request IDs or acpx provide idempotent retries.
- **Bounded lifecycle:** 16 KiB input, 64 KiB per output frame, 1 MiB combined stdout/stderr, and a 0.05–30 second configured operation deadline. A bounded queue and independently interruptible writes prevent a silent child from defeating the deadline through blocked stdin. Cleanup has its own bounded process-termination wait. Raw stderr and provider error messages are discarded.
- **Conservative outcomes:** `returned` requires a nonempty current answer and `stopReason:end_turn`. A known incomplete final response is `failed`; a failure before a prompt attempt is `blocked`; disconnect, cancellation, timeout, malformed events, or size violations after an attempted prompt preserve `delivery_unknown`. Partial text is never promoted to a final answer.
- **Cancellation and cleanup:** unfinished turns receive a best-effort `session/cancel`, followed by local process-group/tree termination. The receipt never claims verified remote cancellation. A complete final response keeps its actual result if cleanup becomes uncertain, but that scope remains unavailable for another owner. An abrupt host death leaves an active ledger entry that blocks new work; it is not automatically cleared or replayed.

Receipts record request/session identifiers, delivery state, permission-denial count, final answer when complete, cleanup status, and explicit mock-only/authentication limitations. Before writing a prompt, the ledger conservatively marks an attempted send with `prompt_written:null`; a host death cannot leave a false durable no-send claim. A completed local write becomes `prompt_written:true`, which still is not proof of provider execution. The ledger stores a prompt hash rather than prompt text. Use synthetic inputs only; local SQLite is not encrypted, and same-user access is not isolated.

## Validation and deferred boundaries

The tests run real local mock subprocesses and exercise first use/reload, exact identity conflicts, failed and unsupported reload, history separation, completed and concurrent duplicates, conflicting request keys, permission denial, forbidden client calls, disconnect, partial output, malformed JSON/protocol metadata, per-frame and total output bounds, timeout, pre-send and in-flight cancellation, cleanup uncertainty, abandoned ownership, and environment/error redaction.

No acpx package compatibility or provider session was tested. A live sidecar would still need: a reviewed installed-command registry; model/effort selection receipts; verified subscription and disabled paid fallback; actual provider-account binding; protected startup/profile configuration; Windows lifetime containment under abrupt host death; explicit authority for files/tools; and tests against the exact acpx/provider protocol versions. This experiment deliberately does not accept an arbitrary installed command as a shortcut to those checks. Its process cleanup is tested for its own controlled mock, not for adversarial descendant processes.

## Primary sources and attribution

The code is independently written; no acpx implementation, dependency, or license text was copied. Design references checked 2026-09-25:

- [acpx shared-session contract at commit 3265ab28](https://github.com/openclaw/acpx/blob/3265ab28dcf25b63cd3947b50ee1cb4ee207ceb8/docs/shared-sessions.md): exact command/directory/session scope, distinct prompt-start admission, no silent replacement after failed resume, and uncertain-delivery/no-retry behavior. Its own request IDs are not an idempotent retry API; the ledger here supplies a separate local guard.
- [ACP session setup](https://agentclientprotocol.com/protocol/v1/session-setup): initialize before creating/loading, capability checks, exact session IDs, and history replay during loading.
- [ACP tool calls](https://agentclientprotocol.com/protocol/v1/tool-calls): permission requests and cancelled permission outcomes.
- [ACP prompt turns](https://agentclientprotocol.com/protocol/v1/prompt-turn): notifications, terminal stop reasons, and session cancellation.

The existing production MCP/CLI paths remain unchanged. This artifact is a transport-contract experiment, not an authenticated ACP release.
