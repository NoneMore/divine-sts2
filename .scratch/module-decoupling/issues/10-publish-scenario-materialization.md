# 10: Publish Generated scenario materialization and Combat episodes

**What to build:** Add a supported interface that validates a Generated scenario, replays its recipe
into a worker and returns its live recorded first combat. Wrap that live combat in a thin forward-only
episode interface suitable for later NoSL algorithm research.

**Blocked by:** 09.

**Status:** resolved

- [x] `materialize_scenario` uses the recorded Ancient and nested choices and map coordinate.
- [x] It verifies encounter identity, canonical initial observation and state hash, naming the first mismatch.
- [x] It stores no state handle or portable snapshot in the scenario.
- [x] The Combat episode exposes observation, legal actions, `step(action_id)`, completion and outcome/HP loss.
- [x] A caller can finish one combat without fork, restore, room internals or private generator helpers.

## Answer

`materialize_scenario` is now a supported `sts2_native_sim.scenarios` interface. It validates a
complete scenario row before touching the worker, checks the row's build, recipe and canonical
combat observation for internal consistency, then replays the recorded Ancient choice, every
nested choice and the recorded map coordinate. The replay checks Act variant and Ancient offer on
the way in, followed by encounter identity, the first differing canonical-observation path and the
state hash at the live first combat.

The returned `CombatEpisode` exposes only the current observation, legal actions, forward
`step(action_id)`, completion, outcome and HP loss. HP loss follows the live player creature during
combat and the worker's scoring snapshot on the transition out, so the final action is included;
neither materialization nor the facade uses or exposes branch handles, fork, restore or room
internals.
