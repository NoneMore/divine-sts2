# 10: Publish Generated scenario materialization and Combat episodes

**What to build:** Add a supported interface that validates a Generated scenario, replays its recipe
into a worker and returns its live recorded first combat. Wrap that live combat in a thin forward-only
episode interface suitable for later NoSL algorithm research.

**Blocked by:** 09.

**Status:** ready-for-agent

- [ ] `materialize_scenario` uses the recorded Ancient and nested choices and map coordinate.
- [ ] It verifies encounter identity, canonical initial observation and state hash, naming the first mismatch.
- [ ] It stores no state handle or portable snapshot in the scenario.
- [ ] The Combat episode exposes observation, legal actions, `step(action_id)`, completion and outcome/HP loss.
- [ ] A caller can finish one combat without fork, restore, room internals or private generator helpers.
