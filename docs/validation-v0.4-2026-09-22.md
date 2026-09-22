# v0.4 validation record — 2026-09-22

This is the public summary of the v0.4 Antigravity migration checkpoint. Account reports, raw provider streams and job receipts stay in the owner's private workspace, outside this repository.

## Offline and installation checks

- **Windows**, Python 3.13, `.\.venv\Scripts\python.exe -B -m unittest discover -s tests`: 135 of 135 tests passed in this repository and in the private installation it mirrors. That run predates the sign-in test added below; the 136-test tree is recorded in the live-review section when it runs.
- **Linux**, Python 3.12: 130 of the 136 tests passed and 4 were skipped as Windows-only. The other 2 failed because they assume Windows' case-insensitive environment (`SystemRoot`). That is a limit of the tests' portability, not a product defect. Windows is the supported platform.
- **The registered private installation**, checked with `scripts/verify_installation.py` in that edition: version 0.4.0, eleven MCP tools, verified helper pins for `claude`, `grok` and `antigravity`, `gemini-cli` listed as retired, and identity configured. None of these checks made a provider request.

## Runtime and account checks (development account)

- **Runtime:** the official Antigravity CLI 1.2.7 for Windows, Google-signed, with SHA-256 `162607893eaacaf7b4a34bcd0bc3978342c6707b0340f96040f0139ac904dd22`.
- **Non-generating readiness (2026-09-20):**
  - The effective configuration showed `useG1Credits:false` and no API or GCP provider.
  - Included Gemini quota was present.
  - Only the pinned checker agent and the deny hook were in effect.
- **Deny-hook probe (2026-09-20):** a test agent's file-read attempt was denied by the `PreToolUse` hook. With `inheritCustomizations: false` the hook did not apply, which is why the checker agent inherits customizations. Other tool families were not probed.
- **Self-update finding (2026-09-22):**
  - On first launch, the CLI's in-place self-updater replaced 1.2.7 with 1.2.8, and the helper refused the changed runtime, as designed.
  - The interactive sign-in also recorded its temporary folder under `trustedWorkspaces`, which the profile check rejects.
  - v0.4.0 now launches every session with `AGY_CLI_DISABLE_AUTO_UPDATE=true` and restores the reviewed settings when sign-in ends. Both behaviors have offline tests.

## Live bounded review

Pending at this checkpoint.

## Not claimed

- Backend model identity. The stream reports only the requested model label.
- An operating-system sandbox. The controls are application-level.
- Tool-denial coverage beyond file reads.
- Authenticated ACP sessions or provider-session resume.
