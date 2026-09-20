# Review Hub (beta)

A local MCP server and CLI for coordinating bounded AI reviews, tracking exact inputs, and collecting responses. The Python package remains `coda_review_hub`; that is project branding, not an identity assigned to the user or their assistants.

The coordinator chooses relevant reviewers and verifies consequential findings. The hub supplies job records, parallel dispatch, duplicate prevention, attachment snapshots, cancellation, and app handoffs. It does not turn a review into authority to execute changes.

[![Review Hub beta: scope a project, select exact inputs, dispatch reviews, capture responses, verify and synthesize. MCP and CLI are implemented; ACP initialization is experimental. GitHub currently requires sign-in to view.](docs/assets/review-hub-beta.png)](docs/assets/review-hub-beta.svg)

[Public case study and text explanation](https://richard-pemberton-research.darkahn.chatgpt.site/projects/review-hub/index.html) · [Editable SVG](docs/assets/review-hub-beta.svg)

## Maturity and scope

**v0.3 is beta software:** an early, Windows-first implementation with synthetic test fixtures. It is not a turnkey installer for provider products, a billing service, or a universally authenticated multi-agent framework. Other platforms need separate validation.

**Repository access (2026-09-20):** GitHub currently requires sign-in to view this repository. Its public visibility setting does not establish anonymous access.

Three automated provider slots, `claude`, `grok` and `gemini-cli`, can use **locally supplied, reviewed subscription helpers**. No CLI route is ready merely because this package is installed. App handoffs work independently of those helpers: they prepare packets and record coordinator-observed replies without controlling a browser or desktop app.

The current transport is local stdio MCP plus CLI wrappers. ACP session management, provider-session resume, autonomous project editing, automatic image generation, and a persistent background service are outside the implemented scope. Provider capability is distinct from hub integration.

## Installation

Use Python 3.11 or later. From a checked-out copy on Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m coda_review_hub.cli --help
```

The command entry points are `coda-review` and `coda-review-mcp`. Register the latter, or the environment's Python executable with `-m coda_review_hub.mcp_server`, with an MCP client that supports local stdio servers. Choose one private state directory outside the repository and use it consistently across clients. No HTTP listener is started.

The repository ships `helpers.example.json` and a generic guarded Gemini CLI helper; it contains no personal helper configuration or account data. Automated dispatch requires reviewed local helpers configured in ignored `helpers.local.json`, including verified hashes and supported model/effort settings. Read the [adapter contract](docs/adapter-contract.md) before enabling one.

## Gemini and Meta extension (v0.3)

Distinct app handoffs are available for `gemini-desktop`, `gemini-spark`, `meta-ai` and `meta-muse`, alongside the existing Gemini browser route. Exact attachment snapshots and returned artifacts use the same checks. App receipts can preserve observed model/mode labels without claiming a verified backend identity.

The included Gemini helper targets official CLI 0.60.0 with separate Google OAuth sign-in, pinned runtime bytes, paid overage disabled and a text-only packet. A development probe completed ACP `initialize` using an empty unauthenticated home. That proves protocol initialization only; authenticated ACP sessions and live Gemini reviews remain unverified. See [Gemini/Meta setup and boundaries](docs/gemini-meta-v0.3.md).

## Identities belong to the user

Start with `identity_status`. If local choices already exist, inspect and reuse them. Otherwise, ask whether the user has established names for their coordinator and collaborators; do not infer names from product labels or unrelated conversation history. Use `configure_identity` to save the confirmed choices outside the repository.

An explicit anonymous choice is supported. It allows neutral introductions without inventing identities. The first-run requirement is a deliberate choice, not compulsory naming. Display names never establish account access, model identity, billing entitlement, or authority to send material.

## Eleven MCP tools

| Tool | Purpose |
|---|---|
| `identity_status` | Inspect local identity setup and whether a choice is needed. |
| `configure_identity` | Persist confirmed names or an explicit anonymous choice locally. |
| `routes` | Inspect route configuration and readiness limits without contacting a provider. |
| `observe_usage` | Record a sourced, recent included-usage observation. |
| `submit` | Prepare a bounded automated batch and return job IDs. |
| `jobs` | Read project-scoped status and reconcile interrupted work. |
| `result` | Read a bounded page of a response and its completion state. |
| `attachment_files` | Recheck saved input/output files and return their exact paths. |
| `cancel` | Request local process-tree termination. |
| `handoff` | Prepare a scoped app packet and optional file snapshots. |
| `record_handoff_result` | Record a reply, attachment observation, and optional returned files. |

Inspect the current tool schemas or CLI help for argument details. A batch accepts at most one request per automated provider, allowing up to three providers to run concurrently. Active jobs for the same provider are serialized across projects sharing the state directory.

## Subscription checks and delivery

Every automated send needs a real observation of available included usage and disabled paid extra usage. Set `paid_usage_disabled=true` only when that condition has actually been verified. The observation expires after one hour and permits only a bounded number of dispatches. It is coordinator testimony, not an independent billing query or a guarantee against later account changes. Authentication alone is insufficient. Missing entitlement, expired authentication, uncertain billing, or exhausted allowance must stop dispatch; never substitute API billing silently.

Use a stable idempotency key for each logical batch. Reusing it with identical inputs returns the original jobs. Inspect those jobs before retrying an uncertain send. A new key creates a new attempt, not continuation.

`returned` means the helper reported successful completion and provided a nonempty final answer; findings still need verification. `blocked`, `failed`, and `delivery_unknown` preserve different failure conditions. Cancellation cannot prove that a provider received nothing. Keep the MCP host connected while work runs: saved records survive interruption, but execution is not promised to survive host exit.

## Files and privacy

Automated routes embed selected UTF-8 source/text snapshots in the packet. App handoffs can stage native files, including images, for a separately operated upload. Staging is not sending. See [attachment routes](docs/attachment-routes.md) for limits, provider distinctions, and returned artifacts.

Keep local identities, helper configuration, job databases, requests, responses, snapshots, account observations and session references out of version control. Raw provider receipts can contain private diagnostics or reasoning. Normal result tools expose the final answer and selected metadata, not the raw stream.

Project binding prevents accidental cross-project retrieval. It is not isolation from other programs running as the same operating-system user. Windows Job Objects constrain process lifetime, not filesystem or network access. The coordinator remains responsible for disclosure scope and independent validation.

## Development

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Tests use synthetic inputs and local fake helpers; they do not establish live provider authentication or entitlement. Run relevant checks after changing a helper, transport, identity setup, or attachment handling.

License information is pending the repository owner's choice.

Current public-checkout validation: [v0.3 beta validation record](docs/validation-v0.3-2026-09-20.md), with 101 offline tests passing.
