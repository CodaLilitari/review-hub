# The user's ChatGPT reviewer

`chatgpt` is an existing first-class app handoff route. It uses the user's signed-in ChatGPT account and a conversation dedicated to the current project. It is separate from the coordinator's Codex model, the OpenAI API, and a generic coding subagent. Review Hub prepares and records the handoff; a separately authorized coordinator operates the app or a verified conversation interface.

## Set up the user's own preferences

1. Inspect `identity_status`. Ask whether the user has an established ChatGPT collaborator and project/conversation preference, or prefers neutral labels. Use `configure_identity` to save the answer; it replaces the profile, so preserve unrelated existing fields. An established name does not prove a particular model or account is available.
2. Inspect the signed-in ChatGPT model and thinking/mode picker. `refresh_models("chatgpt")` returns this inspection instruction; it does not query an API, launch a CLI, or fabricate app options.
3. Record only the actual visible options with `record_models`, including observation time and evidence. Ask for the desired model and thinking/mode setting if the user has not already specified them. Use the existing confirmed preference when it matches current options; if options have changed, apply an already explicit conditional fallback when its condition is observed, or ask before selecting an unapproved alternative. `select_model` binds that choice to the current catalog fingerprint.
4. Reuse a conversation dedicated to this project, or establish one under the user's instructions. Retain its non-secret reference. Prepare the packet with `handoff(..., provider="chatgpt", conversation_ref=...)`.
5. Recheck the selected model/mode and included usage at actual delivery. Upload only the exact verified attachment snapshots. Record the returned answer with `record_handoff_result`, including the actual observed labels and delivery evidence. A prepared packet is not a sent message.

Each handoff requires a fresh app-picker observation; the saved choice survives an unchanged catalog, while stale observations cannot authorize a new handoff. A changed catalog still needs a current confirmed selection; an applicable user-preauthorized fallback is sufficient authorization to select its observed model/mode without asking the same question again. The route remains `coordinator_handoff`, and preparation returns `sent:false`.

## Conditional fallback preferences

Users may establish a primary model and a fallback with a specific condition. Preserve the instruction in their local profile and record the structured policy described below; free-text context alone does not activate the policy checks. Verify the selected model, the actual effort/Pro control and the intended account workspace separately. A model label alone does not establish Pro mode, and a slider position is not a permanent model/mode mapping.

For conditional unavailability fallback, inspect the exact primary model/mode control. Generic or hidden “Locked” / “Usage limit reached” text in a menu's `innerText`, an ancestor or another option does not make an enabled primary unavailable. Record the target's actual disabled/enabled and selected state; absence of `aria-disabled` is not a disabled observation. If the target can be selected and the intended Pro setting is available, use the primary. When evidence conflicts, inspect the current controls and the same account's usage page; do not resolve ambiguity by choosing the fallback. Failed history reads, browser errors, unavailable interfaces and another product's quota establish neither a model lock nor an account limit. A provider error can establish unavailability only when it explicitly targets an actual request with the primary model and required effort selected; first reconcile that request's delivery state before any new send.

A fallback with a named mode or personal workspace retains those requirements. Record the user's standing policy once through the optional `selection_policy` field in `record_models` / CLI `record-models`: `primary_model`, `primary_effort`, `fallback_model`, `fallback_effort`, and `workspace`, using exact locally recorded IDs. This policy is preserved on later catalog refreshes when the field is omitted; it is never inferred from free text. With a policy, an ordinary primary choice is accepted, but **every non-primary choice must be classified**. `selection_basis:"conditional_fallback"` requires the approved fallback and a valid `fallback_observation` targeting that policy's primary and workspace. An old call containing only prose about a lock is rejected. A genuinely new human instruction can use `selection_basis:"explicit_user_override"` with separate `override_evidence`; a provider notice or prior conditional authorization is not a current human override. This exception is rechecked for each new app catalog. No private policy is automatically installed in a user's state.

For example, an explicitly authorized `selection_policy` could have this shape. These IDs are placeholders, not models or modes supplied by the public package; use the exact values from the user's current catalog and instruction.

```json
{
  "primary_model": "primary-model",
  "primary_effort": "required-mode",
  "fallback_model": "fallback-model",
  "fallback_effort": "approved-fallback-mode",
  "workspace": "user-chosen-workspace"
}
```

Record the standing authorization in `evidence` and supply `fallback_observation` for a conditional selection. After observing an actually disabled primary control and recording a fresh accessible-model catalog that excludes that disabled model/mode, its observation has this shape:

```json
{
  "primary_model": "primary-model",
  "primary_effort": "required-mode",
  "target_model": "primary-model",
  "target_effort": "required-mode",
  "workspace": "user-chosen-workspace",
  "scope": "exact_control",
  "state": "disabled",
  "enabled": false,
  "selected": false,
  "observed_at": "<actual timezone-qualified observation time>",
  "evidence": "<actual target-specific control evidence>"
}
```

For an explicit primary-request error, use `scope:"provider_request"`, `state:"unavailable"` or `"limit_reached"`, and `selected_model` / `selected_effort` matching the primary. Omit the control-only `enabled` / `selected` fields. The Hub rejects ambiguous scopes, mismatched targets, enabled/selected controls, contradictions with an accessible catalog and observations older than 15 minutes. The primary evidence must also be at or after the latest catalog's actual `observed_at`; an old limit error cannot be rebound just by selecting again. For one scoped UI observation used for both records, pass that same actual observation timestamp to `record_models` and `fallback_observation`. Record time is not the UI observation time. A new app catalog requires a new primary observation and selection; no permanent fallback entitlement is saved. Each prepared handoff retains its fallback observation even after the later saved choice changes. When an unrelated option changes but the authorized primary remains available, reapply that standing choice without asking the user again.

This validates the structure and consistency of coordinator testimony; it does not inspect the provider, verify backend identity or automatically switch models. Providers without a configured policy retain the legacy direct-choice workflow; do not claim the policy guard is active until the policy is saved and current code has opened that state. Public model announcements, API model catalogs and Codex usage limits cannot establish this consumer conversation's entitlement.

Opening the model store through current code installs a narrow SQLite compatibility fence. Once a policy is configured, even old in-memory workers cannot drop it with a catalog write, save an unclassified choice or consume an existing policy-unbound choice. Those attempts fail atomically with an upgrade/policy error. Existing records are preserved; an explicit replacement policy and valid new-code primary selections still work. Result recording uses the separate jobs store and is not blocked by this model fence. This protects old SQL paths; it is not provider evidence verification or a general defense against direct database tampering.

Use fresh CLI processes for policy/model/handoff work while an MCP worker still exposes the old schema. The compatibility fence closes its silent-write bypass after activation, but does not update its imported descriptions or add new tool arguments. Reconnect that MCP only when coordinated with other active work; do not terminate the Codex backend or restart during handoff recording.
