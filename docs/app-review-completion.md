# Interrupted app reviews and continuation

An app can display a verdict and a generic “finished” notice while the requested review remains incomplete. A tool-limit/Continue notice or explicitly unfinished checks takes precedence. Completing the requested audit is also different from approving the artifact: a completed review may still require repairs.

The classifier recognizes explicit tool-call and turn-budget exhaustion as well as tool-use-limit wording. Structured `pause_turn`, `tool_use`, and `refusal` prevent completion without all being labeled tool exhaustion. See [Claude limit handling](claude-limit-handling.md) for the distinct CLI/app behavior and recovery rules.

`record_handoff_result` records individual response turns. Supply the exact response, current UI evidence, and a `completion_observation` object. Prefer an actual structured provider stop reason when available; do not infer one from an answer's wording. The Hub records the coordinator's observations and does not inspect the app itself.

```json
{
  "status": "tool_limit",
  "provider_stop_reason": "tool_use_limit",
  "continue_available": true,
  "outstanding_checks": ["Check the source table", "Reconcile the title page"]
}
```

Omit `provider_stop_reason` when no structured reason was actually observed. `status` distinguishes `tool_limit`, `output_limit`, `cancelled`, `provider_error`, `delivery_unknown`, `incomplete`, `unknown`, and `completed`. Missing completion observations remain `unknown`; callers must supply an actual completion observation to finalize new jobs. Existing saved jobs are not rewritten or retrospectively certified.

Every unfinished or uncertain observation leaves the job in `needs_continuation`. It has no final `answer.txt`, completion timestamp, or completion turn ID. Its `completion.status` preserves the specific reason; this state does not authorize retrying a cancelled or ambiguously delivered request. Reconcile actual delivery and scope before any further action. No retry, Continue click, acknowledgment, or external hook is executed by this recording call.

To continue an interrupted review:

1. Preserve the initial answer verbatim, its SHA-256, current evidence, and outstanding checklist by recording the partial turn with `acknowledgment: "pending"`.
2. Continue the requested audit in the exact same saved, non-Temporary conversation. Do not start a fresh conversation and call it a continuation.
3. Record the next response using the same job and conversation reference and `previous_turn_id` equal to the latest recorded turn ID. The Hub retains the preceding answer hash and independently stored response bytes.
4. Supply `resolved_checks` naming the prior checks actually closed. Omitting a prior check carries it forward. Newly identified checks belong in `outstanding_checks`.
5. Mark completion only after inspecting the final response and current status. For example, `{"status":"completed","resolved_checks":["Check the source table","Reconcile the title page"]}`. A current interruption, Continue control, or unresolved check still prevents finalization.

The finalized `answer.txt` contains the final turn exactly, not a combined answer. All prior turns remain under `handoff-turns/<turn_id>/answer.txt` with their own `turn.json` receipts. `result(..., turn_id=...)` reads an individual turn and checks its hash; without a turn ID it returns the latest partial turn or completed answer. Returned artifacts are also kept separately per turn; use `attachment_files(..., direction="output", turn_id=...)` to reverify an earlier turn's artifacts. CLI readers accept `--turn-id`.

The database's turn list and completion binding are authoritative. The final turn is committed before writing the convenience `answer.txt` cache. If that cache write fails, `result` still reads the committed final turn; reconcile the call instead of recording or sending again. A database-write failure leaves the job unfinished and permits a retry against its actual preceding turn. Uncommitted staging files may remain on disk after an I/O failure; they are not successful turn or completion receipts.

Before completion, final findings, returned-job lineage, comparison reports, and closing acknowledgment are blocked. A terminal response creates the final answer once. A repeated terminal recording is refused; read `result` to reconcile an uncertain recording call rather than re-sending or creating another job. Existing reports for unstarted pending jobs remain available, but an explicitly interrupted/unverified app review must be resolved before comparison.

Conservative text cues supplement structured observations and can only prevent completion. They are not a general semantic audit: quoted earlier interruption text can keep a later response partial. Preserve the exact response and flag that limitation instead of editing the transcript to make it pass. Provider-specific continuation automation, native session resume, and automated UI inspection remain outside this implementation.

## Regression and validation scope

An isolated synthetic regression originally recorded a verdict-shaped answer containing a tool budget interruption as `returned_via_handoff`, allowed findings, and refused the next same-conversation response. The regression now covers the interrupted-to-completed lifecycle, verifies original response bytes/hash, and checks that finalization is blocked before completion.

Additional tests cover interruption categories, exact conversation/parent binding, unresolved checks, completion gates, per-turn artifacts, concurrent completion, historical records, CLI/MCP fields, and database/cache publication failures. These are local synthetic tests, with no provider calls or automatic UI continuation. A successfully recorded completion is still a coordinator observation requiring independent verification of consequential findings.
