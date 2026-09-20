# v0.3 beta validation — 2026-09-20

The current public checkout passed **101 tests in 32.044 seconds** during release preparation, using its own `src` through an explicit `PYTHONPATH` and an existing environment with the declared dependencies. The suite uses synthetic providers and isolated state; it makes no provider model requests. The executed test arguments were `python -B -m unittest discover -s tests -v`, from the public repository root. Earlier development runs passed 101 tests in each edition as well; this result is a fresh public-source rerun.

New checks exercise three-provider concurrent startup with a barrier, idempotent replay, new app-route attachment/returned-file round trips, MCP and CLI schemas, observed model/mode receipts, old-alias conflicts, contradictory delivery receipts, Gemini runtime pins, source-preserving packet encoding, missing-auth refusal, conservative model/tool/error/warning handling, process cleanup and ACP protocol failures.

Independent code review found and corrected receipt and process-lifetime defects. A helper cannot report successful completion while denying or contradicting submission. A failed receipt write after spawning a helper now terminates the child tree. Legacy route aliases remain readable and retain their earlier meaning until explicitly reconfigured.

The installed official Gemini CLI **0.60.0** completed an actual ACP `initialize` exchange, returning **protocol 1**. The corrected probe used an empty temporary home without a selected authentication method. It sent no authenticate, session-creation or model-prompt request. This establishes initialization only, not authenticated ACP review sessions, model quality, attachment interpretation or subscription eligibility.

The real Gemini helper passed runtime-pin verification and a dry run. A separate attempt without cached Google login returned `preflight_blocked`, `sent=false` and `submission_attempted=false` before launching a provider request. The completed adapter is therefore awaiting separate CLI Google sign-in, current quota evidence and a live review. Desktop login is not reused or scraped.

The registered local MCP command was opened with the official MCP client. It returned version **0.3.0**, all **eleven tools**, three matching reviewed helper pins, configured identity state and `paid_api_fallback=false`. Dependency checks passed. The current running client's tool schemas may need a reconnect to load edited server code.

Shared source and synthetic tests were copied into the public edition through an explicit file allowlist. Private identity seeds, configured helper paths, runtime/account configuration, live conversation references and evidence directories were excluded. This validation records local changes; it does not establish publication of v0.3.

Remaining limitations are explicit: Gemini CLI has not completed an authenticated live review; Meta AI and Muse are coordinator-operated handoffs; authenticated ACP sessions, native automated image transport, project-editing workers and provider-session resumption are not implemented. Review outputs still require independent validation.
