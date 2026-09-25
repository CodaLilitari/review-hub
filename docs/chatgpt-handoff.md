# The user's ChatGPT reviewer

`chatgpt` is an existing first-class app handoff route. It uses the user's signed-in ChatGPT account and a conversation dedicated to the current project. It is separate from the coordinator's Codex model, the OpenAI API, and a generic coding subagent. Review Hub prepares and records the handoff; a separately authorized coordinator operates the app or a verified conversation interface.

## Set up the user's own preferences

1. Inspect `identity_status`. Ask whether the user has an established ChatGPT collaborator and project/conversation preference, or prefers neutral labels. Use `configure_identity` to save the answer; it replaces the profile, so preserve unrelated existing fields. An established name does not prove a particular model or account is available.
2. Inspect the signed-in ChatGPT model and thinking/mode picker. `refresh_models("chatgpt")` returns this inspection instruction; it does not query an API, launch a CLI, or fabricate app options.
3. Record only the actual visible options with `record_models`, including observation time and evidence. Ask for the desired model and thinking/mode setting if the user has not already specified them. Use the existing confirmed preference when it matches current options; if options have changed, show the difference and confirm again. `select_model` binds that choice to the current catalog fingerprint.
4. Reuse a conversation dedicated to this project, or establish one under the user's instructions. Retain its non-secret reference. Prepare the packet with `handoff(..., provider="chatgpt", conversation_ref=...)`.
5. Recheck the selected model/mode and included usage at actual delivery. Upload only the exact verified attachment snapshots. Record the returned answer with `record_handoff_result`, including the actual observed labels and delivery evidence. A prepared packet is not a sent message.

Each handoff requires a fresh app-picker observation; the saved choice survives an unchanged catalog, while stale or changed options cannot authorize a new handoff. The route remains `coordinator_handoff`, and preparation returns `sent:false`.

## Conditional fallback preferences

Users may establish a primary model and a fallback with a specific condition. Save that policy in their private `context_notes.chatgpt` and preserve it alongside the current model choice. Verify and record the stated condition before selecting the fallback. An unavailable picker entry, authentication error, or unknown backend does not establish that a usage limit has been reached. Record the fallback's actual visible model/mode and the user's preauthorization in selection evidence, then recheck the primary on later runs. No model is chosen automatically by a public default.

This is a coordinator procedure, not an automatic quota detector or fallback engine. The app's current account state is the availability evidence. Public model announcements, API model catalogs, and Codex usage limits cannot establish access or remaining allowance for this particular consumer ChatGPT conversation.
