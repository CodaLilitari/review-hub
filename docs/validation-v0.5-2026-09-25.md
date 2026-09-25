# v0.5 beta validation — September 25, 2026

This release removes the deprecated personal Gemini CLI implementation, separates Claude Code from Claude Desktop and Cowork, and adds explicit model/thinking choices using current account observations. Official application updates are checked for compatibility rather than rejected for differing from a frozen build.

## Verification

Final Windows validation:

- Private suite: **213 tests passed** in 57.581 seconds.
- Public suite: **213 tests passed** in 57.379 seconds.
- Newly launched registered MCP server: **v0.5.0, fifteen tools**, all three configured helper-source hashes matched; no provider request was sent by that installation check.
- Claude billing regressions verify that Fable family choices, credit-required entries and indirect aliases are excluded, and that direct model selection cannot bypass the filtered catalog. No live model request was sent for these checks.
- Editable installation metadata reports **0.5.0**; dependency checks passed.
- Private/public production modules and generic helper bytes matched. Public privacy scan and tracked-app/installer checks passed.
- Portfolio build, three rendered-page checks, and lint passed. Portfolio version 27 was published successfully.

Existing MCP connections can retain the old loaded server code and tool list until reconnected; the installation check starts the actual saved command afresh. These tests use synthetic fixtures and do not establish provider authentication, quota, model quality, or production tool isolation.

Actual non-generating checks established:

| Route | Observed result |
|---|---|
| Antigravity 1.2.7 and 1.2.8 | Both passed current publisher/capability verification and discovered 11 Gemini model choices with per-model thinking options. |
| Antigravity 1.2.8 readiness | Effective account route, disabled credit fallback, denial hook, and available included Gemini quota passed. An unavailable optional credit-balance report did not bypass the required billing controls. No review packet was sent. |
| Grok Build 1.0.34 | Native catalog exposed Grok 4.7, 4.7 Build Fast, 4.6 and 4.5 with their supported effort options. Only ACP initialization and model-list metadata were exchanged; no session or model prompt was created. |
| Claude Code 2.1.227 | Subscription metadata returned the older client's model choices without a prompt. The `opus` alias resolved to Opus 5. This did not prove Opus 5.5 was unavailable to the account. |
| Claude Code 2.1.282 | Updated through the existing official npm installation; valid Anthropic signature and matching official release-manifest hash verified. Current CLI sign-in and refreshed Opus 5.5 catalog remain pending. No review prompt was sent. |

Anthropic's [model configuration documentation](https://code.claude.com/docs/en/model-config) specifies Claude Code 2.1.280 or later for Opus 5.5. Discovery now includes a nonfatal official release advisory for Claude Code, and labels its catalog as runtime-observed. This is not a universal app updater or a proof that all newest announced models are accessible.

## Scope and limits

The first model choice requires a current catalog and the user's answer. A changed model list, effort menu, or resolved alias requires confirmation again. Compatible runtime updates and cosmetic labels do not erase the choice. App pickers are coordinator observations, not automated account probes or backend identity attestations.

The helper source remains hash-verified. Current app signatures, relevant capabilities, billing controls and per-run executable stability are checked independently. Additive report metadata, built-in inventories and account quota-window changes do not require freezing an older app.

A new live review through the revised Antigravity helper and a new 1.2.8 tool-denial canary remain unverified. The earlier synthetic response and file-read denial probe are dated v0.4 development evidence, not a new v0.5 result. No operating-system sandbox, universal tool-denial coverage, autonomous coding worker, provider-session resume, or authenticated ACP review session is claimed.

Public source excludes private identity seeds, runtime configurations, credentials, account reports, conversation references, installed apps and installers. The public package asks users to establish their own names or choose neutral labels. Private local identities are maintained separately.

Red's migration review supplied useful evidence and corrections for the self-updater, trusted-workspace restoration, line-ending integrity and failure receipts. This release builds on that work and replaces the earlier fixed-runtime design with current capability checks. Independent follow-up review also exercised model-selection races, database contention and repeated app observations.
