# 02: Establish the Core test and scenario-replay seam

**What to build:** Add an offline xUnit project and a scripted native adapter so coordinator behaviour
can be characterized without the shipped game. Protect Generated scenario recipe replay through the
Ancient, nested choices and map node to the recorded Combat initial state before moving that path.

**Blocked by:** 01.

**Status:** resolved

- [x] Tests drive reset, legal actions, step, capture and fork/restore through the caller seam.
- [x] Invalid actions and action-id collisions are proven not to mutate state.
- [x] A recorded scenario recipe reaches the same encounter, canonical observation and state hash.
- [x] Production reflection and the scripted fake satisfy the same semantic port contract.
- [x] Ordinary tests require neither a game install nor source-text matching.

## Answer

`NativeRunCoordinator` is now the caller seam for `run_*`, fork and restore requests in both hosts.
It validates advertised action ids before the semantic native port can mutate state. The production
reflection adapter and an offline scripted adapter implement that port, and the new xUnit project
characterizes reset, capture, legal actions, step, fork/restore, invalid and colliding actions, and
combat/reward transitions. A checked-in recorded Generated scenario replays its Ancient choice,
nested Card-select prompt and map node to the exact canonical Combat initial state and state hash.
