# Account models and app updates — v0.5 beta

Review Hub checks what the signed-in account exposes through the installed client, then asks the user which observed model/mode and available effort setting to use. It remembers that choice in the private state directory. It does not invent a picker, select a model from a hard-coded ranking, or silently switch to a newly released model.

## First use and subsequent runs

1. Configure identity preferences and a reviewed helper. `claude-code`, `grok`, and `antigravity` are automated text-review routes. `claude-desktop` and `claude-cowork` are separate app handoffs; access to one does not establish access to another.
2. Call `refresh_models(provider)` to query the official CLI without a model prompt. Claude Code uses native initialization metadata; Grok Build uses its model catalog over ACP without creating a session; Antigravity uses native model and per-model effort reports. These are discovery mechanisms, not implemented ACP review sessions.
3. Inspect any `runtime_update` advisory before describing these options as current. If a newer official client exists, arrange its update through the installed provider's supported method, then refresh discovery. Show the returned options and ask the user for both a model and a thinking level. Call `select_model` with the returned `catalog_fingerprint` and a concise record of the user's answer. No generation occurs during selection.
4. Record a fresh, sourced subscription-usage observation before dispatch. Authentication or model visibility alone is not a billing entitlement check.
5. Each new automated submission refreshes the catalog. An added/removed model, changed effort menu, or changed resolved model behind an alias requires another explicit choice before sending. Unchanged choices survive app-version and display-label changes. Replaying an existing request retrieves its original receipt without another discovery or model call, even if helper configuration or identity preferences have changed. A queued job checks its saved selection when it claims the local running state; later preference changes apply to subsequent jobs.

For consumer apps, `refresh_models` returns instructions to inspect signed-in model/thinking controls or their absence and provider-managed mode. Record the actual observation using `record_models`, then obtain the user's choice. If there is no model picker, describe the observed provider-managed choice locally without assigning a backend identity. List only offered thinking controls; use `default` when none is adjustable and record that absence in the evidence. These descriptors do not verify a backend model. Never substitute a CLI catalog, public release announcement, or guessed control. Each prepared handoff consumes one app control/mode observation, so record a fresh observation for the next handoff even when options are unchanged. The existing choice is preserved when the catalog matches. Verify the actual app state again at delivery if a prepared packet has been waiting. Observations expire after 15 minutes; saved choices persist, but stale observations cannot authorize a new send.

Catalogs describe options exposed through the current account, route, and installed client. An older client can omit a newer model the account could use after updating. Absence from that catalog therefore does not prove absent account entitlement, and a public announcement does not prove access. App labels also do not independently attest to the response backend. A helper may restrict the catalog to models whose subscription/quota and bounded-review controls it supports; Antigravity currently supports Gemini models only. Claude Code excludes Fable and credit-dependent choices from this subscription-only text route: Anthropic documents that noninteractive Fable requests can bill usage credits without a consent prompt. Model visibility alone does not establish included usage; see [Anthropic's billing behavior](https://code.claude.com/docs/en/model-config#fable-and-usage-credits). Unsupported new controls stop that route with an actionable error instead of silently changing billing or scope.

## CLI prompts

```powershell
coda-review --state-dir C:\private\review-hub-state models --provider claude-code --refresh
coda-review --state-dir C:\private\review-hub-state choose-model --provider claude-code
```

`choose-model` requires an interactive terminal and asks for the observed model/mode and offered effort setting, including `default` when no adjustable control is offered. An MCP coordinator instead presents the actual options to the user and calls `select_model` after their answer. App users record a fresh control/mode observation before choosing, including observed absence of a picker. `model_status` reads saved state without contacting a provider. The other JSON commands are `record-models` and `select-model`.

## Setup for the generic helpers

Install and sign in to the official provider apps separately. Keep app executables, installers, profiles, tokens, account reports, and state outside the source repository. The supplied adapters are our code; they do not bundle the apps.

Use absolute paths in private JSON configuration:

| Adapter | Local configuration | Required fields |
|---|---|---|
| Claude Code | `~/.review-hub/claude-code.json` | `exe`; optional `profile` for an existing Claude config directory |
| Grok Build | `~/.review-hub/grok.json` | `exe`; `profile` for the dedicated subscription-only profile |
| Antigravity | `~/.review-hub/antigravity.json` | `exe`, `profile`; use the configure/login scripts for its isolated checker profile |

The official runtime owns authentication. The hub does not read or copy tokens. Claude Code supports the native Windows executable, not an arbitrary shell wrapper. Grok requires its clean dedicated startup profile. Antigravity requires the configured resource denials, custom checker agent and deny hook; see the migration guide for their limitations.

In ignored `helpers.local.json`, configure each route with `path` and `sha256` for the reviewed **Python helper source**. Old `model` and `effort` pin fields remain readable for migration but cannot select a user's preferences. The old `claude` provider ID is a compatibility alias for `claude-code`; it never means Desktop or Cowork.

## Compatible app updates

App versions and hashes are recorded as evidence, not permanent compatibility allowlists. At each run the Windows helpers verify the current official publisher signature, required capabilities, authentication/billing boundary, and relevant response semantics. Additive catalog and report metadata is accepted. A newer app can run without changing adapter code when these checks pass.

Claude Code discovery also checks Anthropic's public [latest-release metadata](https://downloads.claude.ai/claude-code-releases/latest), without authentication or a model prompt. Its optional `runtime_update` advisory reports the installed and latest versions, check time, source, and whether an update is available. It currently applies to the Claude Code helper, not every provider or app. If the network check fails or the response is invalid, its status is `unavailable` and update availability remains unknown. The hub exposes this limitation instead of claiming that the installed catalog is the latest. An advisory never updates software automatically and does not invalidate a confirmed model choice by itself.

For example, Anthropic's [model configuration documentation](https://code.claude.com/docs/en/model-config) states that Opus 5.5 requires Claude Code 2.1.280 or later. Earlier clients can resolve `opus` to Opus 5. Updating the runtime and rediscovering is the appropriate response; adding a guessed model entry or accepting a `--model` string does not establish account access. This is an example of client-version scope, not a permanent model or minimum-version list in the hub. Model availability and included-usage eligibility still require their separate checks.

Each run also checks that its executable has not changed during that run. Antigravity's auto-update suppression applies to that child process so its binary stays stable during preflight and dispatch; it is not a global update setting. Updating an app between runs is supported. Updating our helper source still requires reviewing the change and updating its source hash.

The deprecated personal Gemini CLI configure, login and checker implementations have been removed. Only a retired-route error and historical record compatibility remain. Existing user profiles are preserved. This release adds no paid API fallback, provider-session resume, autonomous coding workers, or automatic desktop/browser control.
