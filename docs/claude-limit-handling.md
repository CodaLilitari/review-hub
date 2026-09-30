# Claude limits, interrupted reviews, and recovery

Tool calls, agentic turns, output tokens, spending budgets, and local deadlines are different limits. Record the actual observed cause. A verdict or a generic success notice does not establish that all requested checks finished.

## App conversations

Claude's app can leave a review unfinished while displaying substantial findings. Observe the actual current notice, Continue control, and outstanding work. Record `completion_observation` with the appropriate status and checklist. Do not derive a tool limit from an API document or assume a fixed numerical limit for Desktop/Cowork.

Explicit tool-call exhaustion notices, including “Tool call limit reached” and “ran out of tool calls,” prevent finalization even when a coordinator reports `completed`. Recognized turn-limit reasons also prevent completion. Structured `pause_turn`, `tool_use`, and `refusal` mean incomplete work; they do not all mean an exhausted tool budget. Phrase matching is supplementary and conservative, including when historical notices are quoted.

The job remains `needs_continuation`. Preserve the exact response and files as a separate turn, leave closing acknowledgment pending, and continue only in the same saved, non-Temporary project conversation. Reconcile delivery uncertainty before any continuation. Resolve outstanding checks explicitly and verify the final response before completion. The Hub does not click Continue or send automatically. See [the complete app continuation contract](app-review-completion.md).

## Claude Code

The supplied helper disables tools, MCP integrations, and native session persistence. Native image blocks do not enable file-reading tools. It does not set `--max-turns`, raise an app limit, or automatically resume a CLI session. These restrictions remain intact after the limit-handling correction.

The helper checks both the result subtype and final stop/terminal reason. An `error_max_turns` result carrying the last model's `end_turn` still represents an incomplete review. Nonempty or malformed error/permission-denial fields contradict success under this no-tools review contract.

| Observed result | Recorded interpretation | Recovery |
|---|---|---|
| Recognized turn/tool limit | `tool_limit` | Inspect preserved partial work and remaining checks; no automatic retry |
| Output-token or model-context truncation | `output_limit` | Inspect partial work and narrow or split the next authorized request |
| Spending-budget exhaustion | `budget_limit` | Inspect billing and scope; never increase a budget or switch billing automatically |
| Paused/deferred/aborted work | Incomplete, with the observed reason retained | Reconcile the actual result before another request |
| Valid terminal error without answer text | Received incomplete; no partial answer invented | Inspect the sanitized failure category |
| Timeout, malformed JSON, or no recognized terminal result | Delivery unknown | Reconcile before another attempt; never assume nothing was sent |

Known terminal envelopes retain bounded machine fields in `response_termination` and a normalized `completion_reason`. Raw error strings, denied tool inputs, authentication diagnostics, and failure streams are not promoted to answer text. Unknown reason values remain unknown instead of being copied as arbitrary metadata.

When a recognized interrupted result actually contains user-facing partial text, the helper retains its exact UTF-8 bytes in `partial_result.txt`, bounded to 1 MiB, and records a SHA-256 receipt. The worker exposes only matching, unlinked bytes, marks `partial_answer_available`, and keeps the job `failed / response_received_incomplete`. Later reads recheck the saved answer hash. Corrupt or missing partial bytes are not exposed. Normalized final findings cannot be attached to this failed job. The CLI worker has ended; this state is distinct from an app conversation awaiting continuation.

Some documented CLI error results contain no `result` text. The helper cannot reconstruct preceding assistant turns from a final error object. Timeout output is not parsed as a completed response. CLI session IDs do not establish resumability because persistence remains disabled. A subsequent review requires a new, explicitly scoped packet and fresh usage admission; an idempotency replay returns the original job and does not resend it.

## Primary sources and validation scope

- [CLI reference](https://code.claude.com/docs/en/cli-reference): `--max-turns` bounds agentic turns in print mode; `--max-budget-usd` is an API-spend threshold; `--no-session-persistence` disables native resume.
- [Agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop): the turn limit counts tool-use round trips, not individual tool calls. Error subtypes and final model stop reasons are separate fields.
- [Result schema](https://code.claude.com/docs/en/agent-sdk/typescript): structured error subtypes and terminal reasons.
- [Messages API stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons): use these meanings only when the corresponding values are actually observed. API server-tool iteration limits do not establish consumer-app limits.

The September 29, 2026 audit used isolated synthetic helper and app fixtures. It reproduced missed tool-call-limit wording, lost CLI limit classification/partial text, and success-shaped receipts containing error or permission-denial contradictions. These regressions do not establish current account access, a numerical app cap, or a live provider round trip.

Final validation ran 378 tests in each edition: 377 passed and one file-symlink fixture was skipped because this Windows host does not permit creating file symlinks. Public duration was 139.424 seconds; private duration was 139.263 seconds. Coverage includes valid-envelope completion gates, exact saved partial bytes, later hash checking, native input receipt binding, contradictory-delivery suppression, and preservation of unexposed helper evidence. No generating provider request was made. A fresh registered MCP process verified all 20 tools and helper source pins; the installed reviewer skill also passed validation.
