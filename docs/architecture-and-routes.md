# Architecture and provider routes

This note describes the generic **0.6.1 maintenance update**. It records implemented contracts, not current provider access, a completed release, or a live acceptance test. Historical validation records retain their original dates and scope.

## Local coordination and provider execution

The [MCP server](../src/coda_review_hub/mcp_server.py) and [CLI](../src/coda_review_hub/cli.py) expose the same local coordination operations. MCP uses stdio; the Hub starts no HTTP listener. [Core](../src/coda_review_hub/core.py) records project-bound jobs, exact input hashes, usage attestations, model choices and app handoffs. The [worker](../src/coda_review_hub/worker.py) executes reviewed helpers and retains their local receipts.

Three automated routes are implemented: `claude-code`, `grok` (Grok Build), and `antigravity`. The legacy `claude` identifier maps to Claude Code; it does not select Claude Desktop or Cowork. The retired `gemini-cli` route remains readable in historical records but cannot start new work. Users configure their own reviewed helper source paths and hashes in ignored `helpers.local.json`; [helpers.example.json](../helpers.example.json) contains nonfunctional placeholders.

Automated requests are bounded review packets, not authorization to edit the project. At most one active job per provider runs across projects sharing the state directory. Idempotency keys prevent a same-input replay from creating another attempt. A changed model selection is rechecked when a queued job claims the running state. Blocked, failed, interrupted and delivery-unknown outcomes remain distinct; cancellation does not prove non-delivery.

Restricted child environments, temporary working directories and Windows Job Objects limit process configuration and lifetime. They are not a filesystem or network sandbox. A provider session ID alone does not implement native resume; a new automated review does not silently continue an old provider session. The separate [mock ACP experiment](../experimental/acpx/README.md) exercises local contracts, without adding a production provider route.

## App handoffs retain separate product boundaries

App routes prepare packets and record coordinator-observed responses. They do not drive browser or desktop interfaces. The coordinator verifies the current account, included usage, intended conversation, supported inputs and actual selected model/mode at delivery.

| Route | Boundary |
|---|---|
| `chatgpt` | The user's configured ChatGPT reviewer and saved project conversation; separate from the coordinator's model and the OpenAI API. |
| `claude-desktop`, `claude-cowork` | Distinct app surfaces; Cowork requires the exact authorized folders, and neither inherits CLI entitlement. |
| `gemini`, `gemini-desktop`, `gemini-spark` | Separate app routes; they do not establish Antigravity CLI access. |
| `meta-ai`, `meta-muse` | Independent reviewers with separate conversations and results. Consumer Muse is not Muse Code. |
| `grok-bot` | A background browser handoff for the user's configured Bot, separate from Build, ordinary Grok chat and the xAI API. No automatic desktop fallback or verified headless Bot sender. |
| `microsoft-copilot`, `github-copilot` | Separate account/product observations; generic route metadata does not establish CLI eligibility. |

Use saved project conversations, or an explicit project anchor where the actual Bot interface requires one. Preserve immutable response turns and unresolved checks. A prepared packet, conversation reference, uploaded file or returned answer proves a different stage; none alone establishes a completed, independently verified review.

## Models, files and usage

[Model setup](models-and-updates-v0.5.md) uses account-observed options and the user's choice. Consumer apps can retain an explicit primary/fallback policy; non-primary selections require scoped evidence or a separate current human override. The [ChatGPT procedure](chatgpt-handoff.md) describes exact-control checks, observation freshness and compatibility with older workers. No model policy or collaborator identity is installed by default in the public package.

[Native file support](native-file-support.md) determines input routing. Claude Code supports quoted source/text plus native PNG/JPEG/GIF/WebP blocks. The Grok Build and Antigravity headless adapters remain source/text. App handoffs can stage native bytes, but the coordinator must verify that the selected app actually accepts each format. Preserve original media and disclose any deliberate conversion.

Automated dispatch requires a fresh, provider/project-bound attestation of included usage and disabled paid extra usage. It is coordinator testimony, not a billing API or cost guarantee. App checks are separate. In particular, the [Grok Bot usage contract](grok-bot-handoff.md#match-the-usage-observation-to-the-plan) requires the actual account, plan and applicable meter; a Build allowance cannot establish Bot availability or exhaustion.

## Edition and state boundaries

The public edition contains generic source, synthetic tests and user-facing documentation. It supplies no personal identity seed, active helper pins, account observations, conversation references or job records. Those belong in the user's private state outside version control. The Python namespace `coda_review_hub` is software branding, not a required assistant identity.

Retain the existing public history and deliberately review shared source updates. A private working repository and its operating records must not be merged wholesale into this public distribution. Package versions and local test results do not establish remote publication or public accessibility; verify those separately when releasing.
