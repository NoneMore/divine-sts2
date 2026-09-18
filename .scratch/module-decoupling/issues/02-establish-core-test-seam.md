# 02: Establish the Core test and scenario-replay seam

**What to build:** Add an offline xUnit project and a scripted native adapter so coordinator behaviour
can be characterized without the shipped game. Protect Generated scenario recipe replay through the
Ancient, nested choices and map node to the recorded Combat initial state before moving that path.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Tests drive reset, legal actions, step, capture and fork/restore through the caller seam.
- [ ] Invalid actions and action-id collisions are proven not to mutate state.
- [ ] A recorded scenario recipe reaches the same encounter, canonical observation and state hash.
- [ ] Production reflection and the scripted fake satisfy the same semantic port contract.
- [ ] Ordinary tests require neither a game install nor source-text matching.
