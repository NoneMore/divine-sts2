# 06: Migrate rest, treasure and shop states

**What to build:** Concentrate each simple non-combat room's projection, legal actions and transitions
behind the active session without creating caller-visible room interfaces.

**Blocked by:** 05.

**Status:** resolved

- [x] Rest, treasure and shop each have one active-state implementation.
- [x] Their observation and action ordering remain compatible.
- [x] Native operations cross the semantic port; reflection objects do not enter state implementations.
- [x] The coordinator contains no room-specific dispatch for these states.
- [x] Replaced legacy methods and flags are removed rather than retained in parallel.

## Answer

`RestDecisionState`, `TreasureDecisionState` and `ShopDecisionState` now pair each room's active
projection with hidden executors for exactly its advertised actions. Those executors pass only typed
option identities or indices through the run-session compatibility port; reflected options, relics,
merchant entries and native tasks remain inside `PersistentNativeCombatEnvironment`.

The legacy generic action dispatcher no longer handles rest, treasure or shop actions. Native replay
uses the same semantic operations as live session steps, and the standalone `rest_reset` entry now
initializes `NativeRunCoordinator` just like run and map resets. Offline seam tests preserve action
identity and ordering across choose/open/skip/buy/leave transitions and prove none of these rooms falls
back to the generic compatibility action port.
