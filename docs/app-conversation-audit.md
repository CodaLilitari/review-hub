# Saved app conversations for user audit

Every external AI app review must use a named, saved, non-Temporary conversation scoped to the project, including one-response checks and synthetic validation. Reuse a relevant saved project conversation when one already exists. Names and collaborator identities remain user-configured; this requirement does not assign a persona or model preference.

Before sending, the coordinator checks the actual app's conversation mode/history. A URL, open browser tab, prepared packet or model assurance does not prove persistence. If the current conversation is Temporary, or its persistence cannot be established, do not send there. Select or establish a normal saved project conversation through the supported interface. Do not change account-wide training, activity, billing or retention settings merely to make a review possible.

A newly created normal chat may receive its URL/history entry only after the first send. Verify normal saved mode before that send; preserve the reference when assigned and verify the completed exchange in saved history afterward. An unassigned new-chat URL is different from an unknown or Temporary mode.

Preserve these task-scoped audit details:

- Project and actual app/product route.
- Conversation title and non-secret URL/ID, plus project ID where relevant.
- Time and actual observation establishing normal saved mode before sending.
- Exact prompt/attachment hashes and selected versus observed model/mode.
- Returned answer, response/delivery evidence, and acknowledgment state.
- Whether the saved exchange was successfully reopened or otherwise verified in history after completion; record any failure as unknown/unavailable.

Put persistence observations in the task's review record and the existing `record_handoff_result.evidence` field. The Hub returns the requirement with all newly prepared app handoffs, but does not operate the app or independently verify its settings. Do not invent a `persistence_verified` result. Historical jobs remain unchanged; missing persistence evidence is unknown, not implicitly saved.

A saved response is not necessarily a completed review. Preserve interrupted responses and their outstanding checks, then continue in that same saved conversation. See [app review completion](app-review-completion.md) for `completion_observation`, immutable turn receipts, and completion gates. A generic “finished” notice cannot override a tool-limit/Continue interruption.

After thanks, retain the conversation and its reference. Closing a browser tab is acceptable once the exchange is verified as saved; deleting the chat or using Temporary Chat is not a substitute. Older Temporary conversations may be unrecoverable through the app. Preserve available local records and label any reconstruction as a new conversation; never claim it restores the original provider history.

## CLI reviews are a separate audit route

The bounded CLI helpers retain exact packets, answers, model metadata and job receipts in local private Hub state. Their temporary working directories and isolation flags remain in place. In particular, Claude Code's `--no-session-persistence` means a trace/session ID does not establish a resumable or Claude Desktop-visible conversation. Do not remove that flag or silently broaden tools to obtain app history. When a user needs provider-app-visible audit, use a verified saved app conversation.

## Validation boundary

Synthetic tests cover all eleven app routes, preserve historical records, and verify that a prepared handoff does not invent persistence evidence. They do not prove any user's actual app mode, retained history, authentication, or account settings. The coordinator must observe those facts for the current task.
