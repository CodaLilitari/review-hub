# Antigravity integration and Gemini CLI migration

Review Hub **0.4.0 beta** gives Antigravity its own automated provider ID, `antigravity`, and retires this hub's personal-subscription `gemini-cli` route. The enabled automated routes are Claude Code, Grok Build, and Antigravity. Gemini browser, Desktop, and Spark remain separate coordinator-operated app handoffs.

Google's May 19 announcement said that Gemini CLI would stop serving Google AI Pro, Ultra, and free individual requests on **June 18, 2026**, with those users moving to Antigravity CLI. Its enterprise and paid API routes are a separate matter. This hub does not change to an API key or Google Cloud billing to work around the individual transition. See [Google's transition announcement](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/) and [official migration guide](https://antigravity.google/docs/cli/gcli-migration/).

## Route and record migration

`antigravity` is a new route, not an alias for `gemini-cli`. The old provider stays in the catalog as `retired_cli`, with `enabled:false`. New usage observations and submissions for it return a retirement explanation; a queued old job is blocked before helper launch. Existing jobs, answers, attachment manifests, provider IDs, and identity choices remain readable without conversion. Inspect `jobs` or `result` to retrieve them instead of resubmitting a retired request.

Old helper pins are tolerated for reading configuration but cannot authorize dispatch. They are never reused as Antigravity pins, and an old Gemini allowance cannot authorize a new Antigravity job. A pre-existing user alias called `antigravity` is preserved as an explicit naming conflict until the user resolves it. The upgrade does not invent collaborator names.

## Subscription and runtime boundary

The current Windows setup was inspected with the official native CLI **1.2.7** and a valid Google signature. Official Google account sign-in completed. These facts establish an installed, authenticated application, not a successful bounded review.

For an individual-subscription checker, inspect the effective configuration and current service-reported quota. The observed configuration had `useG1Credits:false`, an empty `modelProvider`, and no GCP configuration. Keep credit fallback disabled, exclude API credentials and endpoint overrides, and stop when included usage is unavailable or cannot be verified. A local pin proves only that reviewed helper bytes match; it does not prove entitlement or a remaining allowance. [Authentication](https://antigravity.google/docs/cli/install/), [credit controls](https://antigravity.google/docs/cli/credits/), and [usage reporting](https://antigravity.google/docs/cli/commands/usage/) describe these distinct mechanisms.

The actual model catalog exposed `gemini-3.8-flash-high` and `gemini-3.1-pro-high`. The intended first checker setting is `gemini-3.8-flash-high` with `high` effort, subject to matching effective configuration and fresh included quota. This is a CLI selection, not a claim that it is identical to the consumer app's Extended mode or universally superior for every task.

On the inspected build, put global flags before a subcommand:

```text
agy --output-format json models
agy --output-format json agents
```

Read-only reports such as `/config` and `/usage` are separate from review packets. Do not treat a report's successful parse as a completed model review. The official [headless guide](https://antigravity.google/docs/cli/headless/) documents the stream format; a live bounded checker round trip remains **pending** in this validation checkpoint.

## Setup (Windows)

These steps use the scripts in `scripts/`. Nothing below sends a review packet until a real `submit`, and nothing reads or copies credentials.

1. Install the official Antigravity CLI for Windows ([installation guide](https://antigravity.google/docs/cli/install/)) and check its Google signature. The helper accepts only the reviewed 1.2.7 build, SHA-256 `162607893eaacaf7b4a34bcd0bc3978342c6707b0340f96040f0139ac904dd22`; any other build is refused until the helper is re-reviewed and re-pinned. The CLI's background self-updater replaces its own binary in place, in interactive and print modes alike, so point the configuration at a private copy of the reviewed build, and note that the helper launches every session with `AGY_CLI_DISABLE_AUTO_UPDATE=true` (only the literal `true` disables it). If a build was replaced anyway, restore the reviewed copy; the helper refuses to run anything else.

2. Create the dedicated profile and configuration. Both paths must be new; nothing is launched:

   ```powershell
   .\.venv\Scripts\python.exe scripts\configure_antigravity.py --exe 'C:\review-tools\antigravity\1.2.7\agy.exe' --profile "$env:USERPROFILE\.review-hub\antigravity-home"
   ```

   This writes `%USERPROFILE%\.review-hub\antigravity.json` and a profile that contains only the no-credit settings, the `review-hub-checker` agent and the fixed deny hook.

3. Sign in once, interactively, in your own terminal. Complete the official Google sign-in, then exit the session. When the session ends, the script restores the reviewed settings (an interactive session records its folder under `trustedWorkspaces`) and re-verifies the runtime pin and profile:

   ```powershell
   .\.venv\Scripts\python.exe scripts\antigravity_login.py
   ```

4. Run the non-generating readiness check. It reads the CLI's ten local reports (`config`, `permissions`, `hooks`, `skills`, `usage`, `credits`, `model`, `effort`, `models`, `agents`), requires included Gemini quota and `useG1Credits:false`, and sends no prompt:

   ```powershell
   .\.venv\Scripts\python.exe scripts\antigravity_check.py --inspect --output-dir 'C:\exact\private-state\antigravity-inspect-01'
   ```

   A pass records `readiness_checked_no_prompt` in that folder's `metadata.json`.

5. Pin the reviewed helper in the ignored local helper configuration (`helpers.local.json`):

   ```powershell
   (Get-FileHash .\scripts\antigravity_check.py -Algorithm SHA256).Hash.ToLower()
   ```

   ```json
   "antigravity": {
     "path": "C:/path/to/review-hub/scripts/antigravity_check.py",
     "sha256": "<lowercase hash from the command above>",
     "model": "gemini-3.8-flash-high",
     "effort": "high"
   }
   ```

   The helper also accepts `gemini-3.1-pro-high`; `high` is its only effort setting. The repository's `.gitattributes` keeps the helper LF on checkout, so the pin does not change with a Windows line-ending setting.

6. Before each `submit`, record a fresh `observe_usage` for `antigravity` from a current readiness receipt. A pin proves only that the helper bytes match; it does not prove quota.

## Packet, result, and protocol limits

The hub wraps the official CLI behind its own local MCP interface. This integration makes **no Antigravity ACP implementation claim**. Previous Gemini/Grok ACP initialization receipts are historical capability probes; they do not validate Antigravity sessions. Session continuation and authenticated ACP dispatch remain unimplemented.

The helper contract uses the existing five arguments: `--prompt-file`, `--output-dir`, `--model`, `--effort`, and `--timeout`. Files use the hub's exact-path, hash-preserving snapshots. Automated inputs are bounded UTF-8 source/text embedded in the packet; native image uploads and arbitrary binary interpretation are not implemented. App handoffs retain their own exact-file upload and observed-receipt workflow.

CLI initialization may report a selected model without proving the response backend. `observed_cli_models` and `model_evidence` preserve that weaker evidence separately from `verified_response_models`. A nonempty model label cannot override an error, ambiguous delivery, missing final answer, or incomplete receipt. A returned answer still needs independent substantive verification.

## Tool-denial layers and their limits

The installed CLI advertises its full 57-tool catalog even for the custom agent, so the helper does not claim a tool-free agent. It layers these controls, none of which is an operating-system sandbox:

- Resource deny rules for file, command, URL and MCP access, verified in the effective `/config` and `/permissions` reports on every run.
- A fixed `PreToolUse` hook that matches every tool and returns a deny decision.
- `inheritCustomizations: true` in the `review-hub-checker` agent, on purpose. In development probes the profile's deny hook applied only when the agent inherited customizations; with inheritance off, an allowlisted file read succeeded. The helper verifies that the dedicated profile contains nothing else to inherit. Do not "harden" this setting to `false` without re-running the probes.
- The helper aborts the run, without saving an answer, if the stream reports any tool or subagent step.

Development probes confirmed the hook's denial for a file read. Command, browser/web, subagent, scheduling and MCP tool families have not been probed; treat them as untested rather than covered.

Before claiming the Antigravity checker ready, verify the effective custom agent, permissions, ambient-context restrictions, a bounded stream round trip, and the hub's returned receipt. Application controls are not an operating-system sandbox. See the [v0.4 validation record](validation-v0.4-2026-09-22.md) for what has actually been checked.
