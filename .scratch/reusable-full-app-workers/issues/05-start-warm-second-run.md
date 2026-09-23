# 05: Start a warm second run in the same process

**What to build:** After a successful `end_run`, the same shipped-game process direct-starts a second independent run whose decisions, histories, observations, identities, and driver execution cannot be contaminated by the abandoned first run.

Blocked by: 04: End one shipped run without exiting its worker.

Status: resolved

- [x] Reuse mode suppresses the shipped driver's final process exit, tracks its task, and starts later runs through the shipped direct-start seam with saving disabled.
- [x] Teardown increments run generation, requests driver cancellation, cleans the current run, releases a parked coordinator wait with an abandonment sentinel, and waits for the old driver before allowing another start.
- [x] A resumed continuation from an older generation is rejected as abandoned and cannot observe or mutate the next run.
- [x] Driver shutdown has a fixed 45-second deadline; timeout fails `end_run`, poisons the worker, and never falls back to returning to the main menu.
- [x] Run-scoped reset removes pending completions, observations, legal actions, action/state-hash histories, choice state, fused claims, boundary bookkeeping, and identity references from the previous run; unsafe non-null pending state fails teardown instead of being silently discarded.
- [x] Immediately after the second `start_run`, public history reports zero actions and exactly the second run's initial state hash.
- [x] A targeted shipped-game acceptance starts two different runs in one process, observes the second initial boundary, and proves the first driver has completed before the second begins.
- [x] Repeating the same seed in the second run produces the same compared initial state as an independent fresh menu-started process.

## Comments

The warm-start acceptance checks both different-seed and same-seed second runs against independent menu starts. The bridge waits for the shipped start task before returning the first boundary to the client, so teardown cannot race unfinished run entry.
