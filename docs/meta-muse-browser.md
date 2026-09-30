# Meta Muse through the browser

`meta-muse` is the consumer Muse route at [muse.ai](https://muse.ai/). Review Hub prepares a bounded packet and exact file snapshots; an authorized coordinator operates the user's signed-in browser and records what actually happened. It does not automatically drive Muse, grant access to its cloud computer, or claim a verified backend model.

## Choose the correct product

As checked on September 30, 2026, Meta advertises consumer Muse on the web, iOS, Android, and Mac. No official Windows consumer Muse app or consumer cloud-agent CLI was verified. The browser is the supported route used by this integration on Windows. Keep the existing `meta-ai` route separate.

Muse Code does have an official Windows/macOS/Linux CLI, including headless commands and an SDK. It is a separate developer product with its own subscription or API credentials. Consumer Muse access does not establish Muse Code entitlement. Do not switch a failed browser review into a CLI/API request or enable paid credits. Installed applications, credentials, usage records, and private conversation references remain outside the public repository.

## First use and subsequent checks

1. Open the official browser app and verify the intended signed-in account. Inspect current included usage and the applicable payment boundary. A free allowance or existing subscription must cover the requested action without paid fallback; stop at exhausted or uncertain capacity. This is a coordinator observation, not a Hub-enforced app billing gate.
2. Inspect the actual model/thinking controls. When options exist, record only those options with `record_models`, ask the user, and bind the choice with `select_model`. When no adjustable picker is exposed, describe that observation explicitly and ask whether to use the provider-managed mode. The local descriptor `provider-managed` with effort `default` can represent that choice; neither string identifies the backend or asserts a particular amount of reasoning. Never import Muse Code's effort levels or a marketing model name into this consumer route.
3. Refresh the observation before each prepared handoff and recheck at actual send. An unchanged catalog preserves the confirmed choice. New options or a changed resolution require another choice. Login and a saved choice do not establish current allowance.
4. Use **Chats → New side chat**, or reopen the project's existing named side chat. Keep it in normal saved mode; do not use Temporary or unsaved conversations. A side chat is a project organization aid, not an isolated cloud computer, memory, or connector permission boundary. Restrict each packet to the authorized inputs and actions.
5. Keep unrelated main-chat history and activity out of review packets and evidence. If sign-in opens the main chat, move directly to the project side chat. Prefer reading the targeted settings panel or side-chat controls instead of exporting the whole page. Do not change connectors, wallet, permissions, or account settings to obtain a review.

The public distribution asks about existing collaborator names or neutral labels. No particular name, identity, account, or model is supplied by this route.

## Files, delivery, and completion

Prepare `handoff(..., provider="meta-muse", attachments=[...])` with exact project-local files. The preparation remains `sent:false`. Immediately before upload, use `attachment_files` to recheck the snapshot hashes and obtain the exact `upload_paths`. Use a direct file chooser and verify every attachment chip against the allowlist before sending.

Do not infer accepted formats from an unrestricted file chooser, from Meta AI's separate product, or from a file being staged locally. Observe actual acceptance and record the result. Provider limits can be narrower than the Hub's limits. Preserve original images/documents when supported; explain any conversion or unsupported input rather than silently replacing it with extracted text. Returned files can be retained with `returned_files` and separate provenance after saving them into the authorized project.

After sending, retain the side chat's actual title/reference. Check that the response has finished, distinguish interruptions from completion, and reopen the saved side chat to verify persistence. Record the exact response with `record_handoff_result`, including `conversation_ref`, observed mode/model labels, ordered `observed_attachment_ids`, attachment evidence, and `completion_observation`.

An interrupted answer remains `needs_continuation`. Continue only in the same saved side chat, bind the prior `turn_id`, and identify resolved outstanding checks. Preserve separate turns and artifacts. Thank the reviewer in the same conversation when finished; do not treat its response as independently verified merely because it arrived. See [app completion](app-review-completion.md) and [native files](native-file-support.md).

## What route metadata establishes

`routes`, `capabilities`, and newly prepared Muse jobs expose the official entry URL, browser surface, provider-cloud runtime, manual-coordinator dispatch, and required observations. Capability fields for native interpretation and session resumption remain unknown until observed. `live_ready` remains false: a route description cannot verify a live browser session, billing setting, delivery, or answer correctness. Existing `meta-muse` jobs and provider IDs remain compatible.

## Sources and evidence limits

A bounded live check on September 30, 2026 used the consumer browser's provider-managed mode and one synthetic `.txt` attachment. The coordinator verified the exact upload chip and saved message, reopened the named side chat, and independently reproduced the returned arithmetic result and code defect. An initially incomplete response and its same-conversation completion were retained as separate receipts; closing thanks were delivered. This demonstrates that specific text-file workflow, not binary-format support, automatic browser dispatch, an exact backend model, or general agentic editing. Account-specific records and conversation references remain private.

- [Consumer Muse product and free-usage FAQ](https://ai.meta.com/muse/)
- [Muse desktop productivity](https://ai.meta.com/muse/productivity/)
- [How Meta designed Muse: side chats and activity history](https://introducing.muse.ai/)
- [Muse Code CLI overview](https://dev.meta.ai/docs/muse-code)
- [Muse Code subscription scope](https://dev.meta.ai/docs/muse-code/subscriptions)
- [Muse Code authentication priority](https://dev.meta.ai/docs/muse-code/auth)

Product documentation describes available surfaces; current signed-in UI observations establish account-specific readiness. Tests use synthetic local inputs and observations and do not establish live provider access. Dated live checks should separately state the tested file format, observed mode, persistence result, and independently reproduced answer checks, without publishing private session records.
