# v0.6 beta validation — September 25, 2026

The private and generic public editions each passed **283 tests** on Windows with Python 3.13. The final complete runs took 90.383 seconds and 89.174 seconds respectively. These tests use synthetic fixtures and local subprocesses; they do not establish current provider login, included usage, or model quality.

## Verified behavior

- Structured reviews append revisions while retaining original answers. Tests cover forged fields, source and answer mutation, missing/hash/quote/range mismatches, unsupported binary input, cross-project access, and exact CR/LF line semantics including Unicode-separator counterexamples.
- Lineage records require returned jobs in one project, an earlier parent, and exact app/provider references for same-conversation assertions. They perform no send, replay or native resume.
- Capability/attachment views preserve declared representation and allowlisted metadata without treating staged files as uploaded or viewed.
- HTML/Markdown reports handle untrusted markup, code fences, unknown states, missing reviews, integrity warnings and bounded answer displays. CLI export refuses existing files and output outside the project. A real stdio MCP test exercises normalization and comparison with process/network execution blocked.
- The synthetic report was visually inspected at desktop size and a 390-pixel viewport. The comparison table scrolls horizontally on narrow screens; receipt details stack vertically. No provider data was used for that preview.
- The separate mock ACP contract passes **25 tests**. It covers identity binding, explicit loading, history separation, permission denial, duplicates/concurrency, uncertain delivery, malformed/oversized output, cancellation/cleanup, command-path shadowing, and probe failure signaling. Its standalone probe completes a new mock session, a local duplicate receipt, and an exact-session load.
- A fresh launch of the registered local MCP command reported version **0.6.0**, all **20 tools**, and matching hashes for the three configured helpers. No provider/account probe was made by this installation check. Editable installation and dependency consistency checks passed.

## Corrections made during review

Independent code review reproduced a source-anchor defect: Python's `splitlines()` treated Unicode separators inside a source line as line endings. Citation checking now splits CR/LF only, with regressions for U+2028, U+2029 and U+0085.

The mock ACP audit found that a relative command path could validate against the bundled file but execute a project-local shadow after changing the child directory. Both command paths now must be absolute; launch uses only the verified canonical paths. The demo probe also now stops on any failed step, requires the exact nonempty prior session ID, and exits nonzero for a failed or mismatched result. It cannot silently reinterpret a missing session as a new-session request.

The first full runs also exposed two isolated-package test fixtures that omitted the new modules. Their explicit copy lists were updated, the failing fixtures passed individually, and both complete suites then passed as recorded above. The independent audit rechecked the ACP fixes before publication.

The final public-export review restored neutral `FixtureAgent` names in three synthetic prompts in both editions. Each edition's eight MCP tests passed again after that text-only cleanup; no production code changed after the complete runs.

## Existing route compatibility and consultation evidence

This increment includes two compatibility corrections found during earlier bounded consultations: Claude Code's validated `system/commands_changed` initialization event and Grok's no-argument `safe_env()` configuration-loading path. The regression suites cover both. The MCP scripting client now has a configurable 180-second default call timeout; a timeout still requires reconciliation before another send.

Before implementation, a project-scoped ChatGPT consultation and bounded Claude Code, Grok Build and Antigravity consultations returned. Their source/model claims were treated as advice and checked separately. The new report/normalization features were also exercised locally against those four saved answers, without new model calls. Private conversation references, account receipts and actual comparison files are excluded from the generic public edition.

All new implementation code is independently authored. Comparable apps informed the design, but no third-party implementation or provider application was vendored. There is no new runtime dependency. See the [mock ACP experiment](../experimental/acpx/README.md) for its pinned design references.

## Limits

This remains a Windows-first beta. The ACP work validates only the bundled mock; no acpx package, provider ACP session, subscription-backed native resume, or adversarial Windows process containment after host death was tested. Automated production routes still accept bounded text/source snapshots rather than native images. App routes still require separate observed app actions. Model names and dated consultation results are not ongoing entitlement guarantees. A matched source citation does not independently verify its claim.
