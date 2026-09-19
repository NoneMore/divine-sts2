# 05: Migrate the map state

**What to build:** Move map observation, legal actions, action execution and next-state selection behind
the active-session implementation, using the semantic native port rather than reflection objects.

**Blocked by:** 04.

**Status:** resolved

- [x] Map projection and its hidden action executors are produced together.
- [x] Entering each supported map point selects exactly one next active state.
- [x] Ancient entry and the recorded first-combat replay remain bit-for-bit compatible.
- [x] The coordinator contains no map-specific dispatch.
- [x] The old map path is removed when the new path passes its seam tests.

## Answer

`MapDecisionState` now owns each map frame together with the hidden executor table built for exactly
its advertised action ids. Executors carry a semantic `MapPointSelection` through the native adapter;
reflected map points remain inside `PersistentNativeCombatEnvironment`, and its generic `StepAsync`
no longer dispatches `choose_map`. The state factory classifies the one capture returned after entry,
so Ancient, combat, rest, event, treasure, shop and boss/elite points each select one next active
state without adding map logic to `NativeRunCoordinator`.

Both run resets and standalone `map_reset` now initialize the same active-session seam, including
map observe, step, fork and restore. Offline seam tests cover projection/executor pairing, semantic
port execution, every supported map point type, standalone reset and the checked-in Generated
scenario replay. Shipped-game acceptance covers the full 17-point standalone map path, all 111
Ancient choices across 37 seeds, and the recorded Generated scenario replays without changing
their hashes, floor bookkeeping, encounters or RNG results.
