# Grok Bot alongside Grok Build

The `grok-bot` route prepares a background browser handoff. The `grok` route remains the automated Grok Build CLI. Ordinary Grok chat and the xAI API are separate routes and cannot silently fulfill a request for the user's Grok Bot collaborator. This maintenance update adds no automated Bot sender.

Use the actual Bot browser entry in the background. Do not focus or launch a desktop fallback without a fresh explicit user request. The Hub has no verified headless Bot response adapter. A future wrapper would need supported messaging and response return, current subscription entitlement, and saved bot/conversation continuity; extracting authentication cookies or bypassing app controls is not an acceptable substitute.

The entry pattern `https://grok.com/bot/<observed-id>` is a discovery hint. Recover the actual reference from the user's authorized project records or current app, and allow the page to finish loading before classifying missing controls. A matching URL or display name alone does not establish access or identity. The public package supplies no bot identifier, collaborator name, private alias, or account choice.

## Prepare and record a review

1. Inspect `identity_status` and retain the user's established names, aliases and notes. If configuration is needed, obtain their choice or explicit preference for neutral labels. `configure_identity` replaces the profile, so preserve unrelated fields. Never retarget the automated `grok` route to mean Bot.
2. Inspect `capabilities("grok-bot")` and `refresh_models("grok-bot")`. The latter requests an app observation; it neither launches Build nor inspects the browser. User-configured aliases resolve to the same canonical Bot route.
3. Verify the intended signed-in account and bot in the actual app. Reuse its saved project thread. If the interface provides only a persistent bot conversation or reply thread, retain that reference and use an explicit project anchor. Verify the exchange can be reopened; a project anchor does not create an isolated conversation or filesystem.
4. Check the applicable plan and usage meter, paid-extra controls, current model options or their absence, and authorized scope. Record the actual options with `record_models` and apply the user's applicable choice with `select_model`. `provider-managed` and `default` are local descriptors when no adjustable controls are exposed, not backend identities. Refresh the observation for each handoff and recheck at actual send.
5. Prepare `handoff` with `provider:"grok-bot"`, the exact project, bounded prompt, conversation reference and any allowlisted files. The returned job is `awaiting_handoff` with `sent:false`. Its packet includes the configured introduction and a reminder to limit the shared cloud computer to the authorized inputs and actions.
6. Reverify `attachment_files`, upload only those exact snapshots through the authorized background browser route, and confirm every attachment chip before sending. Separate bot conversations do not isolate files, accounts or connectors. Do not expand access merely because the cloud computer already has it.
7. Record the exact answer and observed model/mode, attachment and completion evidence with `record_handoff_result`. Keep interrupted output as `needs_continuation`; continue in the same conversation using `previous_turn_id`. Reopen the saved exchange and acknowledge useful contributions when the route permits.

If the authorized background route is unavailable, keep the packet unsent and report the access limit. Do not substitute Build, ordinary Grok chat or an API and label the result a Bot review.

## Match the usage observation to the plan

Record the account and plan, product scope, meter label, whether a percentage means used or remaining, its value/reset, observation time, and applicable paid-extra controls. A general Grok or Build percentage alone establishes neither Bot availability nor exhaustion. When the applicable meter is unknown, record that uncertainty and keep the handoff unsent.

The provider's [plan documentation](https://cursor.com/help/grok-bot/plans) distinguishes legacy Cursor plans and account links, with a Bot weekly allowance, from The X Subscription's shared weekly pool. Verify the actual account and plan before deciding which applies. Legacy on-demand controls and newer credit/top-up controls also differ. Do not infer permanent sharing or separation from a brand name, and do not change billing settings to complete a review.

The Hub exposes these requirements as `usage_contract` in route, capability and handoff metadata. They are coordinator checks, not live quota verification. Build usage observations remain scoped to `grok`; they neither reserve nor revoke Bot usage and cannot replace an observation of the applicable Bot account/plan.

## What the implementation establishes

`dispatch_mode:manual_coordinator`, `automatic_fallback:false`, and `live_ready:false` distinguish prepared instructions from an authenticated, delivered review. The Hub does not operate the app, enforce its billing controls, verify a backend model, or independently establish the reviewer's conclusions.

`tests/test_grok_bot.py` uses isolated synthetic state to check route/alias consistency, browser/background metadata, refusal of automated Bot dispatch, file/response handling, neutral identity defaults, plan/meter metadata, and separation from Build usage observations. These checks do not establish a live Bot send or current account access. See [saved conversations](app-conversation-audit.md), [completion and continuation](app-review-completion.md), and [native files](native-file-support.md).
