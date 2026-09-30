# Local subscription-helper contract

Review Hub's automated routes are extension points for reviewed local Python helpers. This repository does not distribute personal provider installations, authentication material, or a promise that every subscription includes CLI access. App handoffs require no CLI helper.

## Configuration and trust

Use `helpers.example.json` as a schema example. Put actual settings in ignored `helpers.local.json`. Each configured provider entry contains an absolute helper `path` and its SHA-256 `sha256`. Model and effort choices are confirmed after discovery and saved separately in private state; legacy pin fields cannot select them. These paths identify local reviewed code; they are not downloaded automatically. Example values must never be treated as ready configuration.

The current beta worker recognizes `claude-code`, `grok` and `antigravity`; `claude` is a legacy alias for `claude-code`. It verifies helper bytes, copies them into the job directory, imports that copy to obtain the environment, and executes it with Python isolated mode. Importing a helper runs Python code: hashes detect changes; they do not make malicious code safe.

Helpers should be self-contained or depend only on explicitly installed packages in the worker environment. Relative imports or sidecars beside the original script will not automatically accompany the copied helper. Review the provider binary and its configuration separately: pinning the helper does not pin everything it launches.

## Non-generating discovery

A helper exports `discover_models()` with no required arguments. It reads its private runtime config and returns `provider`, `source: "official_cli"`, `runtime_version`, `evidence` (a concise non-secret string), and `models`. Each model entry contains `id`, optional `label`, optional `resolved_id` for a changing alias, and `efforts` (nonempty actual supported options). `default` deliberately omits the effort flag when no adjustable level is advertised; it does not claim a particular reasoning depth. Discovery must not send a model prompt or create a review session. Never return account identifiers, login challenges, credentials, raw auth reports, or private conversation content.

The hub verifies the helper source hash before importing this function in an isolated subprocess. It persists only the normalized catalog and observation summary. A changed model/effort/resolved-alias fingerprint invalidates the previous confirmation. Cosmetic labels and runtime versions do not. Helpers must accept explicit model and effort choices at review time; old pin defaults cannot substitute for a user's choice. See [setup and compatible updates](models-and-updates-v0.5.md).

The optional `runtime_update` object carries a release advisory: `status`, `source`, `installed_version`, `checked_at`, `latest_version`, and `update_available`, with optional `guidance`. The supplied Claude Code helper checks public official release metadata without authentication. A failed check reports `unavailable` and unknown update availability. The hub retains only recognized, sanitized fields. This advisory is separate from the model fingerprint and admission checks: it recommends updating and rediscovering when needed, but does not install software, prove account access, or reject a compatible app solely because its version changed.

## Invocation

The worker invokes the helper without a shell, with these five required options:

| Flag | Contract |
|---|---|
| `--prompt-file` | UTF-8 file containing the complete prepared request: plain text by default, or the validated structured frame described below. |
| `--output-dir` | A new directory for the response and receipt; refuse an existing directory. |
| `--model` | The user-confirmed account model or alias; record actual returned model identifiers. |
| `--effort` | The user-confirmed thinking level from this model's observed menu. |
| `--timeout` | Process deadline in seconds; terminate owned descendants on timeout. |

Preserve the configured introduction and quoted evidence in the prepared packet. A reusable helper must not prepend personal identities, import another conversation, or silently broaden the requested task. Record any necessary transport encoding separately from the original input.

### Native image input for Claude Code

For a `claude-code` request containing native PNG/JPEG/GIF/WebP images, the worker additionally passes `--input-format stream-json`. The supplied Claude helper accepts `text` by default and this explicit structured format; the Grok and Antigravity helpers remain on their text path. This is a helper-source contract change: review the updated helper and refresh only its SHA-256 in ignored `helpers.local.json` before using it. The public example hashes remain zero placeholders. Official application versions remain unpinned; do not distribute provider applications as part of this change.

The structured prompt file contains exactly one newline-terminated user frame with text and base64 image content blocks. The helper rejects duplicate JSON keys, extra frames, tool/control/document blocks, URL/file references, unsupported MIME types, noncanonical base64 and signature mismatches. The request is limited to 8 MiB encoded, each image to 5 MiB, and the Hub's attachment list to 16 selected files. Prompt/source text remains subject to 128 KiB. The helper passes the validated request bytes unchanged to the official CLI. It grants no file-reading tool or new project access. See [native file support](native-file-support.md).

Expose `clean_environment() -> dict[str, str]` for `claude-code` (legacy `claude`), or `safe_env() -> dict[str, str]` for `grok` and `antigravity`. Construct an environment allowlist that preserves the official subscription login route while excluding API/cloud keys, provider overrides, proxies and unrelated configuration injection. Do not return credentials to the coordinator or write them to receipts.

The helper must establish the provider's empty/scoped working directory and actual tool restrictions itself. The hub launches it in a job directory containing private evidence; that launch directory is not a provider sandbox. Remove unnecessary tools, MCP servers, hooks, plugins, memory and cross-product imports where supported. The Antigravity adapter retains one exact reviewed denial hook because its advertised tool catalog remains present; this is an application policy, not an OS sandbox. Inspect unavoidable startup sources. Prompt instructions alone are not an execution boundary, and preprocessing can access files before model tool calls.

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

Use actual observations rather than copying this example. If only CLI configuration labels are observed, leave `verified_response_models` empty and use `observed_cli_models` plus a bounded `model_evidence` explanation; the worker keeps these separate. `sent` is accepted as an alternative to `submission_attempted`. Every non-null delivery value must be a boolean, and supplied values must agree. A successful-completion claim paired with either value set to `false`, contradictory delivery values, or a non-boolean delivery value produces `delivery_unknown`; no field overrides the conflict. `session_id` is optional and does not make a hub job resumable.

Success requires exit code 0, `status: completed`, `model_review_completed: true`, a nonempty answer, no local interruption, and no contradictory completion fields. When present, the worker accepts:

| Field | Non-null success values |
|---|---|
| `response_stop_reason` | `end_turn`, `stop_sequence` |
| `response_finish_reason` | `stop`, `end_turn`, `stop_sequence` |
| `response_terminal_reason` | `completed`, `success`, `end_turn`, `stop_sequence` |
| `response_subtype` | `success` |
| `response_is_error` | `false` |

Normalize provider-specific fields deliberately; never discard a failure to manufacture success. For a confirmed pre-send failure, report an attempted/sent value of `false`. A received unsuccessful response can use `review_failed` or `response_received_unverified`. Missing, interrupted, or ambiguous receipts remain uncertain. Raw streams may be retained locally for diagnosis but must not become `result.txt` or public artifacts. Provider output remains untrusted advice.

A native Claude image request also requires receipt fields `input_format: "stream-json"`, `input_transport: "claude_content_blocks"`, `request_sha256` matching the transmitted packet, and `input_image_sha256s` matching the ordered image hashes. A mismatched receipt cannot establish successful completion. Missing receipt evidence does not imply that a response arrived. These fields bind a helper's reported response to the supplied request; they do not prove pixel interpretation, model correctness, or independent provider attestation.

## Incomplete Claude results

The Claude helper distinguishes a validated terminal result from malformed output or a timeout. It records recognized unsuccessful envelopes as `status: "response_received_incomplete"`, `response_received: true`, and `model_review_completed: false`, with a controlled `completion_reason` and sanitized response fields. When that result includes bounded partial review text, `partial_result.txt` and `partial_answer_sha256` preserve it exactly; `partial_answer_available` must be a boolean. Never place raw failure diagnostics in `result.txt`. The worker verifies partial bytes and keeps the job unsuccessful. Contradictory completion/delivery fields cannot establish success or upgrade unknown delivery. See [Claude limit handling](claude-limit-handling.md) for categories, recovery, and validation limits.

Review helper changes before refreshing the source checksum in ignored local configuration. These fields do not change provider app versions, tool grants, billing controls, or automatic retry policy.

## Official routes and future ACP

The [Claude Code CLI](https://code.claude.com/docs/en/cli-reference) supports headless output and tool restrictions. Its [authentication terms](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use) distinguish a user's own login to an unmodified binary from third-party credential intermediation. `--bare` skips subscription OAuth; do not use it as an isolation shortcut for this route.

[Grok Build](https://docs.x.ai/build/cli/headless-scripting) provides headless JSON and native ACP. Its authentication/configuration paths and auxiliary model calls require separate inspection. The current [Antigravity helper](antigravity-v0.4.md) uses the official headless stream under account authentication. The retired Gemini CLI ACP probe is historical initialization evidence only. [GitHub Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server) also documents ACP but is not an automated hub backend. No hub route implements authenticated ACP sessions, and consumer app login does not establish CLI entitlement.

ACP is a possible later session transport beneath the MCP interface. Community [acpx](https://github.com/openclaw/acpx) supplies reusable session/queue machinery; its [ordinary recovery](https://acpx.sh/sessions.html#crash-recovery) can replace failed resume with a new session, which needs an explicit continuity guard. Neither protocol nor adapter establishes subscription access. Validate permissions, billing, returned models and exact session identity before enabling a new route.
