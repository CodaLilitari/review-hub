# Review Hub (beta)

A local MCP server and CLI for coordinating bounded AI reviews, tracking exact inputs, and collecting responses. Version **0.6.1**, a maintenance update to the beta series. The Python package remains `coda_review_hub`; that is project branding, not an identity assigned to the user or their assistants.

The coordinator chooses relevant reviewers and verifies consequential findings. The hub supplies job records, parallel dispatch, duplicate prevention, attachment snapshots, cancellation, and app handoffs. It does not turn a review into authority to execute changes.

[![Review Hub beta: scope a project, select exact inputs, dispatch reviews, capture responses, verify and synthesize. MCP and CLI are implemented; ACP initialization is experimental. GitHub currently requires sign-in to view.](docs/assets/review-hub-beta.png)](docs/assets/review-hub-beta.svg)

[Public case study and text explanation](https://richard-pemberton-research.darkahn.chatgpt.site/projects/review-hub/index.html) · [Editable SVG](docs/assets/review-hub-beta.svg)

## Maintenance update

The 0.6.1 update adds structured app primary/fallback policies, exact-control and provider-request evidence checks, protection against older workers bypassing a saved policy, and guidance that preserves already authorized choices. Grok Bot has an explicit background-browser handoff with account/plan-specific usage requirements; it remains separate from Grok Build. The update also clarifies independent Meta AI/Muse reviews and preservation of native media. Read the [0.6.1 maintenance notes and upgrade procedure](docs/release-0.6.1.md), [architecture and routes](docs/architecture-and-routes.md), [model setup](docs/models-and-updates-v0.5.md), and the [Bot procedure](docs/grok-bot-handoff.md).

These are implementation and workflow changes. Provider access, account allowance, actual delivery, public release status and independently verified review results remain separate checks. No personal model preference, collaborator alias, bot ID or account configuration is supplied by this public edition.

## Review results and comparison reports

Version 0.6 adds append-only structured findings, exact snapshot citation checks, explicit session relationships, attachment capability records, and static HTML/Markdown comparisons. Reports use selected saved jobs and make no provider requests. Matching a quoted line verifies the citation, not the finding. The five new MCP tools have CLI equivalents; see [v0.6 usage and limits](docs/review-results-v0.6.md).

A separate [mock ACP contract experiment](experimental/acpx/README.md) exercises session identity, permission denial, failure and retry behavior using a bundled synthetic agent. It is not a live acpx/provider integration, does not authenticate an account, and adds no production provider route. Installed provider applications remain outside version control.

## Maturity and scope

**The 0.6 series remains beta software:** an early, Windows-first implementation with synthetic test fixtures. It is not a turnkey installer for provider products, a billing service, or a universally authenticated multi-agent framework. Other platforms need separate validation.

**Repository access (2026-09-20):** GitHub currently requires sign-in to view this repository. Its public visibility setting does not establish anonymous access.

Four automated provider slots, `claude-code`, `grok`, `muse-code` and `antigravity`, can use **locally supplied, reviewed subscription helpers**. The former `gemini-cli` route is retired; historical records remain readable. No CLI route is ready merely because this package is installed. App handoffs work independently of those helpers: they prepare packets and record coordinator-observed replies without controlling a browser or desktop app.

The production transport is local stdio MCP plus CLI wrappers. Authenticated ACP session management, provider-session resume, autonomous project editing, automatic image generation, and a persistent background service remain outside production scope. The separate mock ACP experiment establishes a local contract only. Provider capability is distinct from hub integration.

## Installation

Use Python 3.11 or later. From a checked-out copy on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m coda_review_hub.cli --help
```

The command entry points are `coda-review` and `coda-review-mcp`. Register the latter, or the environment's Python executable with `-m coda_review_hub.mcp_server`, with an MCP client that supports local stdio servers. Choose one private state directory outside the repository and use it consistently across clients. No HTTP listener is started.

The repository ships `helpers.example.json` and generic helpers for Claude Code, Grok Build, Muse Code, and Antigravity; it contains no personal helper configuration or account data. Automated dispatch requires reviewed local helpers configured in ignored `helpers.local.json`, including verified helper-source hashes; model/effort choices are saved separately after discovery. The example's zero hashes are placeholders, not usable pins. Read the [adapter contract](docs/adapter-contract.md) and [Antigravity setup and boundaries](docs/antigravity-v0.4.md) before enabling a helper.

## Model setup and compatible updates (v0.5)

On first use, discover the models and thinking levels exposed through the current account and installed client, ask the user, and save that choice outside Git. Every new automated request refreshes the catalog. New/removed models, changed effort options, and changed resolved aliases prompt again; compatible app updates and cosmetic labels do not. Claude Code discovery includes a nonfatal official-release advisory because older clients can omit newer account models. CLI `choose-model` asks interactively. Consumer apps require current signed-in observations of available controls or their absence/provider-managed mode; local descriptors do not verify the backend. See [model setup](docs/models-and-updates-v0.5.md).

Claude Code has the explicit `claude-code` route; `claude` remains a legacy CLI alias. `claude-desktop` and `claude-cowork` are separate app handoffs. No app entitlement is inferred from another surface.

Official app versions are observations rather than frozen compatibility requirements. Current Windows publisher signatures, required capabilities and billing controls are checked each run; our own helper source remains hash-verified. Apps, installers, profiles and credentials stay outside version control.

## Antigravity replacement

Antigravity has its own `antigravity` provider ID. The upgrade does not redirect old Gemini requests, reuse their entitlement observations, or reinterpret their saved replies. Review the new helper and runtime, verify the current account's included usage and disabled paid fallback, then create a separate helper pin and usage observation. The deprecated Gemini helper implementation has been removed; only retirement errors and historical record compatibility remain.

A development diagnostic using the official Antigravity CLI 1.2.7 returned a nonsensitive synthetic response with `gemini-3.8-flash-high` selected and no observed tool calls. A bounded review through the guarded helper returned on September 25 with `gemini-3.1-pro-high` selected. These dated results do not establish continued entitlement, tool isolation, or a verified backend model identity. The current user selects from their own account catalog; examples do not establish availability or entitlement.

The integration wraps the CLI through the hub's existing local MCP interface. It implements no Antigravity ACP sessions. Earlier ACP initialization experiments remain historical protocol probes. See [Antigravity migration, subscription checks, and validation boundaries](docs/antigravity-v0.4.md).

## Muse Code bounded reviews

The separate `muse-code` route uses the official native subscription login for bounded source/text review. It verifies a fresh included allowance and model catalog, forces contributor mode off, runs empty tools with read-only permissions, and keeps an ephemeral session with local audit receipts. It never inherits consumer Muse identity or entitlement. Configure your own reviewed helper pin and choose an exposed model/effort; no account or personal model choice is supplied. See [Muse Code setup and boundaries](docs/muse-code-cli.md). This local addition is not a new published release.

## Your ChatGPT reviewer

The `chatgpt` route is included. Check the user's established ChatGPT collaborator and project conversation, inspect their signed-in account's current model and thinking/mode options, and save their explicit preference. A fresh picker observation is required for every handoff. When options change, reapply an applicable standing primary choice or a conditional fallback whose stated condition is currently verified; ask only before an unapproved model or effort change. Names and model preferences are user-configured, with no personal defaults in this public package. See the [ChatGPT handoff procedure](docs/chatgpt-handoff.md), including how to record a user-authorized conditional fallback.

This route prepares a packet and records a coordinator-observed reply. It does not send automatically, infer account access from an OpenAI API catalog, or substitute the coordinator's Codex model for the user's ChatGPT conversation.

## Grok Bot browser handoffs

`grok-bot` prepares a background browser handoff for the user's configured Bot collaborator. It does not invoke Grok Build (`grok`), ordinary Grok chat or the xAI API. Recover the actual bot reference and saved project conversation or explicit project anchor. Do not focus or launch a desktop fallback without a fresh explicit user request; no headless Bot response adapter is verified by this Hub.

Inspect the actual account, plan, applicable usage meter and paid-extra controls before a send. An exhausted Build observation alone cannot establish Bot exhaustion, and a brand label alone cannot establish shared or separate allowance. Route, capability and handoff metadata expose these coordinator checks as `usage_contract`; they do not query or enforce provider billing. See the [Grok Bot procedure](docs/grok-bot-handoff.md).

## Gemini and Meta app handoffs

Distinct app handoffs are available for `gemini-desktop`, `gemini-spark`, `meta-ai` and `meta-muse`, alongside the existing Gemini browser route. Exact attachment snapshots and returned artifacts use the same checks. App receipts can preserve observed model/mode labels without claiming a verified backend identity.

Meta AI and Muse remain independent reviewers. An authorized request for all accessible reviewers includes both, with separate conversations and results. A response from one does not fulfill a request for the other.

The consumer `meta-muse` route uses [Muse in the browser](https://muse.ai/) with a named, saved project side chat. Verify current included usage, actual model controls or an explicitly observed provider-managed mode, and every accepted attachment before sending. The Hub prepares and records the handoff; it does not operate the cloud agent or enforce app billing. Consumer Muse access does not establish entitlement to the separate Muse Code CLI. See the [Muse browser procedure](docs/meta-muse-browser.md).

These app handoffs are distinct from the Antigravity automated route. They preserve project scope and observed app receipts; they do not prove desktop control, authenticated ACP sessions, or automatic uploads. The [Gemini/Meta v0.3 notes](docs/gemini-meta-v0.3.md) remain historical context, including the retired Gemini CLI experiment. Use the v0.4 Antigravity documentation for current automated setup.

## Identities belong to the user

Start with `identity_status`. If local choices already exist, inspect and reuse them. Otherwise, ask whether the user has established names for their coordinator and collaborators; do not infer names from product labels or unrelated conversation history. Use `configure_identity` to save the confirmed choices outside the repository.

An explicit anonymous choice is supported. It allows neutral introductions without inventing identities. The first-run requirement is a deliberate choice, not compulsory naming. Display names never establish account access, model identity, billing entitlement, or authority to send material.

## Twenty MCP tools

| Tool | Purpose |
|---|---|
| `identity_status` | Inspect local identity setup and whether a choice is needed. |
| `configure_identity` | Persist confirmed names or an explicit anonymous choice locally. |
| `routes` | Inspect route configuration and readiness limits without contacting a provider. |
| `model_status` | Inspect saved catalog and user choice. |
| `refresh_models` | Query current CLI account options without a model prompt. |
| `record_models` | Record a signed-in app's visible options. |
| `select_model` | Save the user's confirmed model and thinking level. |
| `observe_usage` | Record a sourced, recent included-usage observation. |
| `submit` | Prepare a bounded automated batch and return job IDs. |
| `jobs` | Read project-scoped status and reconcile interrupted work. |
| `result` | Read a bounded page of a response or a specified immutable turn and its completion state. |
| `attachment_files` | Recheck saved input/output files, including a specified turn's outputs, and return their exact paths. |
| `cancel` | Request local process-tree termination. |
| `handoff` | Prepare a scoped app packet and optional file snapshots. |
| `record_handoff_result` | Record a response turn, observed completion state, attachment evidence, and optional returned files. |
| `capabilities` | Describe implemented file/session contracts without querying accounts. |
| `record_review` | Append advisory findings and check exact saved source citations. |
| `review` | Read findings, revisions and refreshed integrity checks. |
| `record_lineage` | Record observed parent context without sending or resuming. |
| `comparison_report` | Render selected local records as inert HTML or Markdown. |

Inspect the current tool schemas or CLI help for argument details. A batch accepts at most one request per automated provider, allowing up to four providers to run concurrently. Active jobs for the same provider are serialized across projects sharing the state directory.

## Subscription checks and delivery

Every automated send needs a real observation of available included usage and disabled paid extra usage. Set `paid_usage_disabled=true` only when that condition has actually been verified. The observation expires after one hour and permits only a bounded number of dispatches. It is coordinator testimony, not an independent billing query or a guarantee against later account changes. Authentication alone is insufficient. Missing entitlement, expired authentication, uncertain billing, or exhausted allowance must stop dispatch; never substitute API billing silently.

Use a stable idempotency key for each logical batch. Reusing it with identical inputs returns the original jobs. Inspect those jobs before retrying an uncertain send. A new key creates a new attempt, not continuation.

`returned` means the helper reported successful completion and provided a nonempty final answer; findings still need verification. `blocked`, `failed`, and `delivery_unknown` preserve different failure conditions. Cancellation cannot prove that a provider received nothing. Keep the MCP host connected while work runs: saved records survive interruption, but execution is not promised to survive host exit.

## Files and privacy

Choose a route that preserves the files needed for the task. Claude Code accepts native PNG, JPEG, GIF and WebP image blocks alongside quoted UTF-8 source/text. Its image transport permits 5 MiB per image and 8 MiB per complete encoded request, with at most 16 selected files. The current Grok Build and Antigravity headless adapters accept source/text. App handoffs stage exact native files for a separately operated upload through an app whose current controls support the format. When sound or motion matters, preserve supported audio/video inputs and the bounds of any excerpts. Staging is not sending, and unsupported files must not be silently omitted or converted. See [native file support](docs/native-file-support.md) and [attachment routes](docs/attachment-routes.md) for limits, receipt checks, and returned artifacts.

Every app review uses a named, saved, non-Temporary project conversation. Verify saved mode before sending and preserve its reference and history evidence afterward; the Hub records the coordinator's observations rather than inspecting the app. See [saved conversation audit](docs/app-conversation-audit.md). CLI helpers retain their separate local packet/response audit and existing isolation settings.

An app response is complete only after its requested checks are finished. Record interruptions and unknown outcomes with `completion_observation`; the job stays `needs_continuation`. Continue in the same saved conversation, preserving each response and returned file set as an immutable turn. Final findings, comparison reports, and closing acknowledgment remain blocked until completion. See [interrupted reviews and continuation](docs/app-review-completion.md).

Keep local identities, helper configuration, job databases, requests, responses, snapshots, account observations and session references out of version control. Raw provider receipts can contain private diagnostics or reasoning. Normal result tools expose the final answer and selected metadata, not the raw stream.

Project binding prevents accidental cross-project retrieval. It is not isolation from other programs running as the same operating-system user. Windows Job Objects constrain process lifetime, not filesystem or network access. The coordinator remains responsible for disclosure scope and independent validation.

## Development

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Tests use synthetic inputs and local fake helpers; they do not establish live provider authentication or entitlement. Run relevant checks after changing a helper, transport, identity setup, or attachment handling.

License information is pending the repository owner's choice.

Historical checkpoints include the [v0.6 validation record](docs/validation-v0.6-2026-09-25.md), [v0.5 record](docs/validation-v0.5-2026-09-25.md), [v0.4 record](docs/validation-v0.4-2026-09-22.md), and [v0.3 record](docs/validation-v0.3-2026-09-20.md). Their dated test counts and live-check limits do not establish validation of later source changes. Setup steps and remaining checks are in the [Antigravity notes](docs/antigravity-v0.4.md).
