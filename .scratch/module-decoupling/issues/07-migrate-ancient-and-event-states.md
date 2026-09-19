# 07: Migrate Ancient and event states

**What to build:** Move Ancient and ordinary event decisions behind the active session, including their
Card-select prompt continuations and transitions into combat or back to the map.

**Blocked by:** 05, 06.

**Status:** resolved

- [x] Ancient choices and nested choices reproduce every recorded Generated scenario recipe.
- [x] Event observation, action order and errors remain compatible.
- [x] Event-to-combat and event-to-map paths settle at one stable decision.
- [x] No event or Ancient mode flag remains a second source of truth.
- [x] Shipped-game acceptance covers representative prompt and combat paths.

## Answer

`EventDecisionState` now owns Ancient and ordinary-event action order, validation and hidden semantic
executors. Event choices and leaves cross typed compatibility-port operations, while Card-select,
reward and option prompts replace their suspended event as the sole active state until their typed
continuation resumes. Both native hosts route standalone `event_reset` through `NativeRunCoordinator`,
and replay dispatch uses the same semantic event operations as live steps.

Offline seam tests cover event ordering, standalone reset, recorded Generated-scenario replay and each
nested-prompt shape. Shipped-game acceptance drove all 111 choices offered by the 37-seed Ancient
sweep (including Card-select, reward, nested reward and option-pick paths), plus four-worker ordinary
event reset/replay and event-to-combat-to-map restore paths without changing the recorded hashes.
