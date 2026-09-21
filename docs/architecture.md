# Current architecture

STS2 Gym separates supported Python callers, the native simulation core, and shipped-game adapters.
The historical findings in [`architecture-review.md`](architecture-review.md) explain why the
boundaries changed; this document describes the implemented shape.

## Run decisions

`src/Sts2.NativeSim.Core/RunSession/` owns the active run state. `ActiveRunSession` exposes one
decision frame at a time and applies advertised action IDs through the native adapter. Room state,
nested Card-select prompts, legal actions, and observation capture remain behind that boundary.
`NativeRunCoordinator` owns branch history, restore, hashes, timing, and protocol result envelopes.

This is the implementation of [ADR-0006](adr/0006-model-run-decisions-as-one-active-state.md).
`PersistentNativeCombatEnvironment` remains the combat kernel behind the session rather than a
second non-combat dispatcher.

## Protocol and observations

`src/Sts2.NativeSim.Protocol/` owns semantic RPC messages, legal actions, canonical observation
records, and schema generation. The headless host and FullAppBridge retain separate wire adapters,
while their runtime encoders project into the same canonical observation family. This implements
[ADR-0005](adr/0005-share-rpc-contracts-while-keeping-host-encoders.md); changing either published
wire dialect still requires a versioned migration.

## Generated scenarios and Combat episodes

The supported `sts2_native_sim.scenarios` facade keeps generation, deterministic corpus writing,
materialization, and the forward-only `CombatEpisode` interface stable. Its private model, codec,
store, generation, corpus, and driver modules may change without becoming caller-visible seams.
Research code can therefore read a Generated scenario corpus, materialize a recorded first combat,
and complete it through `observation`, `legal_actions`, and `step(action_id)` without branch handles
or generator internals.

## Support direction

The dependency direction is inward: supported code under `python/sts2_native_sim/` may not import
`python/tools/`, `python/experiments/`, or `tests/acceptance/`. Maintained tools and experiments use
the supported package. See [`tooling.md`](tooling.md) for their support promises and entry points.
