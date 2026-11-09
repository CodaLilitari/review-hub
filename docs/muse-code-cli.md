# Muse Code CLI

`muse-code` is the official Meta coding CLI. It is not the consumer Muse
browser route (`meta-muse`) or Meta AI (`meta-ai`).
Their accounts, entitlement observations, packets and results are separate.

The Windows helper is `scripts/muse_code_check.py`. Configure an absolute
official native executable path and the existing native configuration root in
`~/.review-hub/muse-code.json`, outside the checkout:

```json
{"exe":"C:\\absolute\\path\\muse-bin-version.exe","config_home":"C:\\Users\\YourName\\.config"}
```

Do not put an API key in this file. Native Muse owns sign-in. The helper never
reads credential contents and never performs login or falls back to API billing.
Current allowance admission is deliberately limited to the verified native
`Muse Code Power Usage` and `Muse Code Max Usage` labels with a fresh `mint`
allowance. The CLI reports the documented Maximum Usage subscription as
`Muse Code Max Usage`; matching only Power Usage incorrectly rejects an upgraded
subscription. Other labels still require explicit adapter review, not a guessed
entitlement rule. The provider's subscription terms require an upgrade or waiting
at the limit; Maximum Usage requires waiting. Additional API keys are separately
billed and are never a fallback for this route.

Each discovery verifies the Meta Authenticode signature, checks non-secret
configuration, obtains `usage --json`, and asks the official MSP server for
`model/list` after initialize/initialized. The query creates no session and sends
no model prompt. Fake, bundled, config-derived and unresolved catalogs are refused.
Only actual advertised model IDs and effort variants can be selected.

Each review repeats preflight, then runs one `exec` turn using `--preset empty`,
`run.toolset=[]`, `--permission-profile :read-only`, contributor mode off,
reminders/web/user-input disabled, no foreign personal context, no native session
log, and one model step. Generic home, data, cache and working directories are
new isolated temporary directories. The native config root remains available
only so the official binary can own its existing authentication. Unknown config
files, custom permission profiles, hooks, MCP settings and endpoint overrides
stop dispatch. API/proxy/provider environment variables are not forwarded.

The native read-only profile cannot be combined with individual approval flags;
the helper selects the profile itself. It does not enable unrestricted mode or
disable the sandbox. Empty-tool operation is not a claim of OS isolation for
arbitrary agentic code. This route accepts bounded UTF-8/source packets only;
native images, binary attachments, workspace edits and resume are not implemented.

The JSONL parser requires one successful terminal event, one matching model
usage record, a consistent run ID, and no failed/cancelled/model-extra calls.
Native 1.4.14 model-configuration and task-status metadata are accepted narrowly:
configuration must name Meta and the selected model, and each status must match
the ID/stream of an admitted model-response task with the observed field types.
Status message/details are not copied to receipts. Model-side-effect records
remain restricted to model responses; this does not permit tool activity.
Unknown events, tool activity, missing output and inconsistent terminal evidence
are incomplete. A process timeout terminates the child tree and does not establish
non-delivery; do not automatically retry. Local receipts retain the answer and
terminal usage evidence, excluding hidden reasoning deltas. A run ID is not a
provider session ID. The Hub audit trail does not establish saved app history.

Every captured native exit now writes `diagnostics.json`, including timeouts,
nonzero exits, malformed JSONL and missing final replies. It contains bounded
event counts, recognized terminal status/reason categories, numeric usage,
text-presence flags and stderr hint categories. It never copies arbitrary
provider messages, raw stderr, unknown fields or reasoning text. Stderr hints
are observations, not a verified explanation for failure. Terminal/usage detail
lists are capped at eight entries; stderr inspection is capped at 64 KiB.
Successful response receipts also retain only verified fields and final text.
For schema drift, at most eight unknown event names and bounded key/type shapes
can be retained, only when those names/keys occur literally in the same signed
executable hash verified by preflight. No payload values are copied. This is
diagnostic evidence; it does not admit an unknown event into successful reviews.

If exactly one identifiable completed terminal contains final text but the
native process or stream validation fails, the helper saves
`unverified-result.txt` and keeps `model_review_completed=false`. This is a
candidate for reconciliation, not a successful Hub review. A fixed
`completion_validation_error` category identifies the failed check without
copying arbitrary exception text. Ambiguous terminal events are not retained.
No final answer is
reconstructed from partial output or reasoning deltas. `--max-model-steps 1`
caps model turns, not wall-clock duration; the native CLI documents exit 1 for
failure/cancellation, including reaching that cap. The helper's separate
timeout remains bounded and terminates the child process tree.

Fresh project-bound usage observation and explicit model selection remain Hub
gates. A verified signature or successful model query alone is not a review.
Record live validation only after a successful native exit and verified matching
terminal/model usage evidence. Describe the exact supplied source scope and
preserve reviewer limitations; a wrapper-only review does not validate its
underlying implementation or the entire project. Keep actual job/account
receipts outside Git, and leave prior failed jobs failed after a later repair.
An old imported MCP process needs a coordinated reconnect to pick up the new
schema; fresh CLI/MCP processes use the new implementation immediately.

Official references:

- [Headless execution and extensions](https://dev.meta.ai/docs/muse-code/extending)
- [Permissions and profiles](https://dev.meta.ai/docs/muse-code/permissions)
- [Native subscriptions](https://dev.meta.ai/docs/muse-code/subscriptions)
- [Configuration](https://dev.meta.ai/docs/muse-code/configuration)
