# Gemini and Meta routes in v0.3 beta

Review Hub v0.3 adds one automated text-checker slot (`gemini-cli`) and four distinct app routes (`gemini-desktop`, `gemini-spark`, `meta-ai`, `meta-muse`). The existing `gemini` browser handoff remains compatible. All eleven MCP tools and their CLI equivalents remain available. A batch can contain up to three distinct automated providers: Claude, Grok and Gemini CLI.

## What each route does

| Provider ID | Transport | Capability and remaining boundary |
|---|---|---|
| `gemini-cli` | Guarded official CLI | Google OAuth only, included-quota attestation required, paid overage disabled, bounded UTF-8 packet. Requires installation pins and separate CLI sign-in. |
| `gemini` | Coordinator handoff | Existing browser-chat route; verify model and thinking in each conversation. |
| `gemini-desktop` | Coordinator handoff | Native app packet and exact attachment snapshots; the coordinator operates and observes the actual app. |
| `gemini-spark` | Coordinator handoff | Agent task with explicitly scoped inputs/actions; app availability does not identify its backend model or grant connector access. |
| `meta-ai` | Coordinator handoff | Consumer app/browser review; record the strongest appropriate mode actually exposed on the account. |
| `meta-muse` | Coordinator handoff | Separate cloud-agent candidate; verify account access, included usage and authorized scope before sending. |

Handoffs stage files and messages locally. They do not drive browsers, sign in, upload files or send prompts. Existing attachment hash checks, exact manifest ordering, returned-artifact snapshots and project-bound records apply to all new app routes. Consumer subscriptions do not automatically establish developer API or separate coding-CLI entitlement.

## Gemini CLI installation and authentication

The included helper targets the reviewed official `@google/gemini-cli` **0.60.0**, Node 20+, with `gemini-3.1-pro-preview` and `high` effort. This is a deliberately narrow supported combination. It is not the same model/mode as a consumer app's Flash Extended selector. Actual response model names must match the requested CLI model before the helper accepts completion.

Install the official package in a dedicated runtime directory, outside the source repository and project being reviewed:

```powershell
npm install --prefix C:\review-tools\gemini-runtime --ignore-scripts --no-audit --no-fund --save-exact @google/gemini-cli@0.60.0
python scripts/configure_gemini.py --node 'C:\Program Files\nodejs\node.exe' --cli-root 'C:\review-tools\gemini-runtime\node_modules\@google\gemini-cli' --profile 'C:\review-tools\gemini-home'
python scripts/gemini_login.py
```

These paths are examples. The configuration defaults to `~/.review-hub/gemini-cli.json`; the selected profile must be new and dedicated to these reviews. The configure command pins the Node executable and the complete official CLI package tree, then creates the Google-sign-in selection. It neither reads credentials nor authenticates. The interactive login launcher uses the same restricted configuration and supplies no model prompt. Complete the official Google account/consent flow yourself, using the account with the existing subscription, and exit after authentication. Desktop/browser authentication is separate. No credential scraping or copying is implemented.

After source review, configure the helper path, SHA-256, model and effort in the installation's ignored `helpers.local.json` (or its private equivalent). See the existing adapter contract. Runtime or helper changes invalidate pins until separately reviewed. A missing OAuth cache blocks the helper before it launches a model request. Cache presence alone is not proof that a token works or quota remains; the dry-run field `requires_google_signin` is a cache-presence hint, not an authentication check. The coordinator's fresh usage observation is still required.

Inspect quota with exact `/stats` in the official **interactive** CLI after login; that action attempts to refresh quota and credits. A rendered panel alone does not prove a fresh successful fetch; check for refresh failures and current values before recording an observation. `/stats model` displays cached quota. Do not run `gemini -p '/stats'` or an unknown slash command as a supposed non-generating probe: in 0.60.0 the noninteractive dispatcher can fall through and send that text to the model. No supported headless account/quota probe was established in this implementation. This is distinct from the explicit initialize-only ACP probe below.

## Restrictions and evidence

- Use only Google OAuth (`oauth-personal`), enforced by CLI settings. Provider API keys, cloud credentials, proxy overrides, Node flags and unrelated environment variables are not inherited.
- Set `billing.overageStrategy` to `never`; no API or paid-credit fallback is implemented. A fresh included-usage observation remains a separate precondition in the hub.
- Use a clean temporary working directory and a dedicated CLI home. Disable hooks, extensions, MCP servers, skills, agents, automatic memory, directory-tree context and parent memory traversal. Fail closed on unexpected profile customizations or system policies that override the deny policy.
- Remove built-in tools and install an admin wildcard denial. These are application controls, not an OS filesystem/network sandbox.
- Encode the complete review packet as JSON text, escaping every literal `@`. Gemini's noninteractive preprocessing can expand `@file` references before normal tool policy, so disabling tools alone is insufficient. Preserve original and transmitted bytes and their hashes.
- Keep final answers distinct from private raw provider diagnostics. Accept a completed review only with a successful process result, no error or warnings, nonempty answer, exact expected model receipt and zero observed tool calls. A requested model is not sufficient evidence of a returned model.
- No automatic retry follows a timeout, model mismatch or uncertain delivery. A helper's contradictory sent/completion claims cannot become a successful hub result.

The CLI may retain its own session records under the dedicated home. This adapter does not offer session resumption or automatic courtesy follow-ups; use a continuing app conversation when those are required, and thank disposable reviewers in the initial packet.

## ACP capability probe

```powershell
python scripts/gemini_check.py --probe-acp --output-dir C:\review-evidence\gemini-acp
```

The probe uses an empty disposable home with no selected authentication method, sends ACP `initialize`, saves the advertised capabilities and then terminates the process tree. It never sends `authenticate`, `session/new` or `session/prompt`, and rejects client callbacks. A live initialization succeeded with official CLI 0.60.0 and protocol 1 during development. The advertised image/audio/context and session capabilities belong to the provider; this text adapter does not implement those capabilities. Authenticated ACP review sessions and general session continuation remain outside this version.

The first development probe incorrectly retained a selected OAuth method and timed out during startup authentication. The corrected probe omits that selection and cannot reuse the account profile. This distinction has regression coverage; initialization alone is not a model-review test.

## App model and mode receipts

`record_handoff_result` accepts optional `observed_model` and `observed_mode`, in addition to the actual response, conversation reference and evidence. Labels are bounded to 256 characters and cannot contain control characters. They are recorded as coordinator observations with `backend_model_verified=false`; a UI label never silently becomes an independently verified backend identity. Omit the model label if the product does not expose it.

Older saved aliases that collide with these new canonical route names are preserved and surfaced as `alias_conflicts`. Outbound preparation remains blocked until the user explicitly resolves the naming choice. The upgrade must not silently redirect an existing app alias to an automated CLI.

## Official references checked during implementation

- [Google sign-in and subscription authentication](https://geminicli.com/docs/get-started/authentication/)
- [CLI quotas and pricing](https://geminicli.com/docs/resources/quota-and-pricing/)
- [Configuration, billing and model overrides](https://geminicli.com/docs/reference/configuration/)
- [Native ACP mode](https://geminicli.com/docs/cli/acp-mode/)
- [Official source](https://github.com/google-gemini/gemini-cli)
- [Official package 0.60.0](https://www.npmjs.com/package/@google/gemini-cli/v/0.60.0)
- [Meta consumer assistant](https://ai.meta.com/meta-ai/assistant/)
- [Muse cloud agent](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/)
- [Muse Code's separate subscriptions](https://dev.meta.ai/docs/muse-code/subscriptions)

Provider features and subscription rules can change; refresh account and route evidence before dispatch.
