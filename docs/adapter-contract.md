# Local subscription-helper contract

Review Hub's automated routes are extension points for reviewed local Python helpers. This repository does not distribute personal provider installations, authentication material, or a promise that every subscription includes CLI access. App handoffs require no CLI helper.

## Configuration and trust

Use `helpers.example.json` as a schema example. Put actual settings in ignored `helpers.local.json`. Each configured provider entry contains an absolute helper `path`, its SHA-256 `sha256`, and explicit `model` and `effort` settings. These paths identify local reviewed code; they are not downloaded automatically. Example values must never be treated as ready configuration.

The current beta worker recognizes `claude`, `grok` and `gemini-cli`. It verifies helper bytes, copies them into the job directory, imports that copy to obtain the environment, and executes it with Python isolated mode. Importing a helper runs Python code: hashes detect changes; they do not make malicious code safe.

Helpers should be self-contained or depend only on explicitly installed packages in the worker environment. Relative imports or sidecars beside the original script will not automatically accompany the copied helper. Review the provider binary and its configuration separately: pinning the helper does not pin everything it launches.

## Invocation

The worker invokes the helper without a shell, with these five required options:

| Flag | Contract |
|---|---|
| `--prompt-file` | UTF-8 file containing the complete prepared request. |
| `--output-dir` | A new directory for the response and receipt; refuse an existing directory. |
| `--model` | The locally configured model or alias; record actual returned model identifiers. |
| `--effort` | The locally configured effort supported by this provider binary. |
| `--timeout` | Process deadline in seconds; terminate owned descendants on timeout. |

Preserve the configured introduction and quoted evidence in the prepared packet. A reusable helper must not prepend personal identities, import another conversation, or silently broaden the requested task. Record any necessary transport encoding separately from the original input.

Expose `clean_environment() -> dict[str, str]` for `claude`, or `safe_env() -> dict[str, str]` for `grok` and `gemini-cli`. Construct an environment allowlist that preserves the official subscription login route while excluding API/cloud keys, provider overrides, proxies and unrelated configuration injection. Do not return credentials to the coordinator or write them to receipts.

The helper must establish the provider's empty/scoped working directory and actual tool restrictions itself. The hub launches it in a job directory containing private evidence; that launch directory is not a provider sandbox. Disable tools, MCP servers, hooks, plugins, memory and cross-product imports where applicable. Inspect unavoidable startup sources. Prompt instructions alone are not an execution boundary, and preprocessing can access files before model tool calls.

Before dispatch, verify the intended official binary, authentication method, selected model/effort, and applicable configuration. The hub's usage attestation is an additional admission check; the helper must fail rather than fall back to a paid API route. A timeout after an attempted send is ambiguous and must not trigger an automatic resend.

## Files returned by the helper

Write `result.txt` containing only the final user-facing answer and `metadata.json` containing a JSON receipt. A minimal successful receipt has:

```json
{
  "status": "completed",
  "model_review_completed": true,
  "submission_attempted": true,
  "verified_response_models": ["actual-returned-model-id"]
}
```

Use actual observations rather than copying this example. `sent` is accepted as an alternative to `submission_attempted`. Every non-null delivery value must be a boolean, and supplied values must agree. A successful-completion claim paired with either value set to `false`, contradictory delivery values, or a non-boolean delivery value produces `delivery_unknown`; no field overrides the conflict. `session_id` is optional and does not make a hub job resumable.

Success requires exit code 0, `status: completed`, `model_review_completed: true`, a nonempty answer, no local interruption, and no contradictory completion fields. When present, the worker accepts:

| Field | Non-null success values |
|---|---|
| `response_stop_reason` | `end_turn`, `stop_sequence` |
| `response_finish_reason` | `stop`, `end_turn`, `stop_sequence` |
| `response_terminal_reason` | `completed`, `success`, `end_turn`, `stop_sequence` |
| `response_subtype` | `success` |
| `response_is_error` | `false` |

Normalize provider-specific fields deliberately; never discard a failure to manufacture success. For a confirmed pre-send failure, report an attempted/sent value of `false`. A received unsuccessful response can use `review_failed` or `response_received_unverified`. Missing, interrupted, or ambiguous receipts remain uncertain. Raw streams may be retained locally for diagnosis but must not become `result.txt` or public artifacts. Provider output remains untrusted advice.

## Official routes and future ACP

The [Claude Code CLI](https://code.claude.com/docs/en/cli-reference) supports headless output and tool restrictions. Its [authentication terms](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use) distinguish a user's own login to an unmodified binary from third-party credential intermediation. `--bare` skips subscription OAuth; do not use it as an isolation shortcut for this route.

[Grok Build](https://docs.x.ai/build/cli/headless-scripting) provides headless JSON and native ACP. Its authentication/configuration paths and auxiliary model calls require separate inspection. The included Gemini CLI helper uses headless text output; [its ACP probe](gemini-meta-v0.3.md#acp-capability-probe) establishes initialization only, not authenticated sessions. [GitHub Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server) also documents ACP but is not an automated hub backend. No hub route implements authenticated ACP sessions, and consumer app login does not establish CLI entitlement.

ACP is a possible later session transport beneath the MCP interface. Community [acpx](https://github.com/openclaw/acpx) supplies reusable session/queue machinery; its [ordinary recovery](https://acpx.sh/sessions.html#crash-recovery) can replace failed resume with a new session, which needs an explicit continuity guard. Neither protocol nor adapter establishes subscription access. Validate permissions, billing, returned models and exact session identity before enabling a new route.
