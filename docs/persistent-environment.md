# Persistent native combat environment

**Role.** Canonical contract for the persistent in-process native environment (`reconstructed_native`): its worker/process model, reset and branch protocol, run-level coordinator modes, native choice seams, audited run-start (Neow) contract, and presentation-suppression inventory.

**Scope boundary.** This document owns durable interface and architecture facts only. It does not own:

- dated verification results, fault-injection evidence, or measured performance → [persistent-environment-evidence.md](persistent-environment-evidence.md)
- the shipped-application bridge (`full_application_native`) → [full-application-control-bridge.md](full-application-control-bridge.md)
- native critic/value-model training evidence → [native-rollout-farm.md](native-rollout-farm.md)
- current capability status, evidence precedence, and milestone order → [project-status-and-review-guide.md](project-status-and-review-guide.md)

**Freshness.** Every behaviour below is asserted against the build pinned in [version-compatibility.md](version-compatibility.md) and fails loudly on drift. No state, trace, or branch compatibility is claimed across assembly hashes.

## Environment authority model

The project maintains two native operational environments with different authority:

- **`full_application_native` (primary differential authority).** Spawns the shipped `SlayTheSpire2.exe --headless --force-steam=off` binary in isolated sandbox directories with `Sts2.NativeSim.FullAppBridge`. It executes normal shipped run initialization, room transitions, and combat lifecycles with no synthetic mid-combat state reconstruction. Its sandbox layout, protocol, and suppression seams are specified in [full-application-control-bridge.md](full-application-control-bridge.md); its current projection gaps and the golden-differential gate that closes them are tracked in [first-combat-scene-generation-plan.md](first-combat-scene-generation-plan.md) §3 and §5 (E5).
- **`reconstructed_native` (diagnostic / micro-benchmark accelerator).** An in-process `GodotHost` that performs direct synthetic combat reset and reconstruction for fast local tests and state diffing. This document specifies it.

A separately checked-out Python simulator is neither of these: it is a non-authoritative research accelerator that is not a label source or product dependency. The binding constraint lives in [holistic-solver-roadmap.md](holistic-solver-roadmap.md) and in the claims discipline of [project-status-and-review-guide.md](project-status-and-review-guide.md).

## Worker and process model

- The Godot host has a newline-delimited JSON server mode. One process mounts the shipped PCK, loads the shipped assembly once, installs the audited presentation seam once, and remains alive across combat, isolated run-level decisions, and composed `run_reset` map/room sequences.
- Every mode uses the same bounded content-addressed fork/restore machinery. Replies are one JSON object per line; diagnostics use stderr. The Python client classifies Godot's startup banner as diagnostics.
- Each worker is one isolated headless Godot process. Native singleton state is never shared between simultaneous environments.
- Windows workers inherit `SEM_NOGPFAULTERRORBOX` and related process error modes before Godot starts; the host reapplies them on entry, and the standalone feasibility/exporter-smoke executables do the same. Worker close requires a zero exit code, closes every pipe, and fails loudly on timeout or unclean exit instead of allowing desktop crash dialogs or silent shutdown faults.
- The Python pool keeps persistent workers, schedules one operation per isolated worker, and replaces crashed workers before subsequent operations.

## Reset, step, and branch protocol

- `reset` reconstructs native `RunState`, `Player`, `CombatState`, creatures, card piles, and the native card database from structured input.
- `step` validates a stable ID against freshly derived native legality and calls native `PlayCardAction`, `UsePotionAction`, `DiscardPotionGameAction`, or the proven native full-turn coordinator.
- Non-choice enemy actions run atomically through the next player `Play` phase.
- Every result includes a complete observation, legal actions, terminal flags, SHA-256 state hash, logical handle, and transition timing.
- A handle stores reset input, ordered action history, and expected hash. `restore` reconstructs and replays, then refuses to continue on mismatch. It does not deep-copy active combat.
- A restore to the already-resident exact prefix is a verified cache hit; non-resident prefixes reconstruct, because caching an unverified active-combat object would be unsafe.
- A portable branch record is a reset-mode-plus-parameters-plus-history record and can be reconstructed on a different pool worker under the same expected-hash gate. Reset provenance covers combat, composed run, faithful run start (Neow), map, card reward, item reward, custom reward, rest, and event modes rather than assuming every branch began as isolated combat.
- A portable branch record states its schema version, the exact game build it was captured on, its reset provenance, and its reset request. Cross-worker restore validates all of them before it issues any reset RPC, so a tampered provenance, an unsupported schema, an unknown reset mode, or a build mismatch fails closed with a named error instead of reconstructing a different lifecycle. A record without a schema version takes an explicit version-0 compatibility path that reads the mode from the recorded reset method alone.
- `NativeSearchCoordinator` expands a portable root over isolated workers in bounded batches, executes only legal native actions, verifies the reconstructed root hash before every child, restores the source worker, and returns native child observations to a caller-supplied scorer. Its multi-ply beam search has explicit depth, node, and width budgets, deduplicates nodes by stable `branch_identity` (reset_request + action history + expected_hash) instead of raw state hash transposition, and breaks score ties in stable native legal-action order.
- Every result includes a deterministic auxiliary `scoring_features` snapshot drawn directly from native run/combat objects. It provides consistent HP, block, inventory, act/floor, energy, creature, power, and hand/draw/discard/exhaust/play-pile inputs across all environment modes without entering the canonical observation or state hash, so it cannot alter exact differential observations. The native value scorer that consumes these features has its own checkpoint-provenance requirements and gate results, recorded in [native-rollout-farm.md](native-rollout-farm.md).

## Reconstruction isolation

- Every reconstruction creates fresh shipped `RunManager` test services against the new `RunState`, including action queues and event, reward, rest-site, treasure, and player-choice synchronizers. This prevents coordinators and RNG bindings from leaking across replayed runs.
- Reconstruction also calls the shipped `CombatManager.Reset(false)` lifecycle before replacing its singleton state. A broad terminal-rollout corpus exposed a delayed completion from one combat ending the next reconstructed combat; native reset cancels the prior combat token and continuations before the new `CombatState` is installed.
- Isolated combat construction preserves the native `RunState`/`CombatRoom` invariant, so shipped end-combat hooks execute on both the enemy-turn victory and the player-death paths. Native `LoseCombat` remains active; only the subsequent game-over music/UI/history/save block is suppressed.

## Reset contract and supported subset

The reset model includes build fingerprints, seed/RNG counters, character, ascension, encounter, HP, deck/card state, relic state, potions, gold, turn/resources, and extensible run context. The implemented subset is deliberate:

- character and encounter lookup is generic over native `ModelDb` entries;
- arbitrary cards populate one authoritative deck; every card has a unique stable `instance_id`, and `initial_hand` lists IDs to move those same native combat instances from draw pile to hand;
- native upgrade/enchantment operations reconstruct upgrades and enchantments; named native `[SavedProperty]` scalar state reconstructs evolving cards such as Genetic Algorithm;
- relic identities and named native `[SavedProperty]` scalar state are reconstructed; `counter` is accepted only for one unambiguous saved integer counter;
- potions are placed into exact native slots; native target legality and shipped use/discard actions are used;
- supplied RNG stream counters are loaded with native `RunRngSet.LoadFromSerializable`, including rewind behavior;
- current/max HP, gold, ascension, seed, turn, and energy are applied;
- asynchronous combat card choices routed through native `CardSelectCmd` are exposed and resumable, including bounded multi-select/skip combinations;
- blocking native bundle and relic screens are exposed as stable `choose_option` actions, including native Skip where allowed, and resume the shipped continuation;
- creature targets are represented at the native play-card decision boundary; no separate blocking combat creature-choice command exists in the inspected shipped assembly;
- regular card, relic, and potion reward choices, rest-site options, and event options are exposed with stable native-derived actions;
- an explicit `invoke_combat_entry_hooks` capability requests the assembly-owned relic `AfterRoomEntered`, `BeforeCombatStart`, and `BeforeCombatStartLate` lifecycles generically, so no relic is reimplemented; legacy traces retain their prior contract.

The explicit initial hand is reconstruction input, not a simulated draw. It moves the identified native combat instances after the native initial shuffle, so reset never changes the requested total card count. Cards created during combat receive deterministic `dynamic-{ordinal}-{model}` identities. Subsequent end turns use native discard, shuffle, draw, hooks, enemy AI, and RNG.

### Construction phases

Construction is split into a run-only phase and a combat-only phase.

- The **run-only** phase creates the player, the starting or custom deck, relic and potion state, the native `RunState`, run services, ascension effects, and stable card instance identities. It creates no encounter or `CombatState`, populates no `PlayerCombatState`, and consumes no combat RNG stream.
- The **combat-only** phase owns encounter and monster generation, the `CombatState`, the combat manager and player combat state, entry hooks, opening pile and enemy overrides, and combat RNG initialization.
- Every construction records a `last_construction` audit in `diagnostics`, sampled at that boundary from shipped native state: the `CombatManager` combat-state reference before and after the run-only phase, whether the newly built player has a `PlayerCombatState`, and the native run RNG counter map after each phase. Shipped `CombatManager.Reset(graceful: false)` deliberately keeps a stale `CombatState` reference, so the audit compares object identity rather than nullness.
- The deck owns its stable card instance identities for the whole run. Because a composed run never builds a combat before entering one, the run-only phase publishes a deck-card-to-instance-id map that both combat construction and a later native combat started from the map resolve their cloned cards through; combat deals therefore keep the same instance-id vocabulary with or without a synthetic construction.

### Reset provenance

Reset provenance is first-class and enumerated. Each reset RPC names exactly one `ResetMode` (`combat`, `run`, `neow_run`, `map`, `card_reward`, `item_reward`, `custom_reward`, `rest`, `event`), and that single value selects the reconstruction lifecycle for the reset, for a resident restore, and for a cross-worker portable restore. A mode with no lifecycle fails loudly rather than degrading to a direct combat reset. Branches persist the provenance together with the parameters that mode needs (item reward kind and model, custom reward kinds and linking, event id) instead of a set of mode booleans, and `diagnostics.reset_mode` reports the resident provenance.

- `run_reset` performs exactly `ConstructRun` → `GenerateRooms` → `GenerateMap`: it creates no synthetic combat, shuffles no pile, rolls no monster intent, and lets the first real combat start natively from the map.
- A composed-run branch also reconstructs through the run-only path, so restoring a map or run-combat handle cannot install and discard a combat.
- `neow_run_reset` reuses that same run-only construction and adds only the shipped starting Ancient event room; see [Audited run-start contract](#audited-run-start-neow-contract).
- `diagnostics.last_restore` records how the last restore rebuilt its branch (`resident_prefix`, `combat_snapshot`, or `replay`), the shipped `CombatManager` combat-state reference comparison across the reconstruction, whether the rebuilt player has a `PlayerCombatState`, and the run RNG counters at that boundary, so "no synthetic combat during restore" is observable rather than asserted.

### Composed-run RNG positioning

Removing the discarded synthetic combat changes the RNG position of a composed run. The synthetic combat used to consume `Shuffle` (9 draws for the 10-card acceptance deck, 10 for the A10 starting loadout) and one `Niche` draw before the map was generated.

Map and room generation read the `UpFront` stream, so the generated map, its points, the visited coordinates, and the map legal actions are unchanged, but the first real combat now shuffles the draw pile and rolls monster HP from the unspent stream positions. Post-E2 composed-run seeds therefore produce a different first-combat state than pre-E2 runs, and a pre-E2 run-mode portable branch fails closed with `replay_divergence` rather than replaying to a state the pin no longer produces. The other seven reset modes are bit-identical, and schema-less records still replay through the version-0 compatibility path.

## Run-level coordinator slices

### Map

`map_reset` invokes the shipped act's `CreateMap` implementation and exposes the complete native coordinate/type/edge graph. `map_step` accepts only a child/start coordinate from that graph and advances the native `RunState.AddVisitedMapCoord` state. This mode is routing-only: it does not call room entry or apply room effects, and therefore does not advance `ActFloor`.

### Rewards

`reward_reset` builds a regular encounter `CardReward` from the character's shipped `CardPool`, `CardCreationOptions`, `CardFactory`, run RNG, and hooks. `item_reward_reset` builds native `RelicReward` or `PotionReward` objects; an optional `model_id` uses the shipped predetermined-reward constructor for exact scenario testing. `reward_step` calls `Reward.SelectUnsynchronized`; native inventory mutation, hooks, and choice history remain active, while skip calls the reward's native `OnSkipped`. The generic blocking reward coordinator intercepts only the native reward-screen factory while leaving `RewardsSet`, `RewardsSetSynchronizer`, reward hooks, card selection, and inventory mutations native. Gold, linked, and room-owned reward sets are not yet connected.

### Rest sites

`rest_reset` calls shipped `RestSiteOption.Generate`. Native Heal executes creature healing and hooks; native Smith suspends through `CardSelectCmd` and resumes into `CardCmd.Upgrade`.

### Events

`event_reset` resolves a shipped `EventModel`, enforces its native `IsAllowed`, creates a mutable instance, and calls `BeginEvent`. Stable `choose_event` actions map to current native `EventOption` objects and execute `Chosen()` until another card choice or completion. Event-entered combat and specialized room/UI transitions remain loud unsupported boundaries.

### Composed run

`run_reset` composes these pieces through the shipped room lifecycle. It constructs only the run and its map, then a legal `choose_map` calls native `RunManager.EnterMapPointInternal`, which rolls the room type, pulls the act encounter/event, appends history, constructs and pushes the room, invokes room hooks, and starts its coordinator. Because the map is generated from the `UpFront` stream, the composed-run map is unaffected by the removal of the discarded synthetic combat; the first real combat is started natively from the map rather than pre-built.

Run-level observations include the complete native RNG counter map. This caught and now guards against stale coordinator bindings that map-only projections could otherwise conceal.

## Native combat choice seams

### Async card choices (`CardSelectCmd`)

The worker installs a runtime adapter for STS2's shipped `ICardSelector` automation interface. When native `CardSelectCmd` requests cards, the adapter returns an unresolved native-typed task. The executing `PlayCardAction` remains suspended on that task while `step` returns a `card_choice` observation containing the exact native option objects, selection bounds, and stable `choose_cards` actions. Selecting an action completes the native task and runs the original continuation until completion, another choice, or terminal state.

This is generic across `CardSelectCmd` callers; it does not identify or implement individual cards. Pending choices can be forked, reconstructed, replayed, or abandoned by restoring another handle.

### Bundle and relic screens

The worker intercepts the shipped `CardSelectCmd.FromChooseABundleScreen` boundary instead of allowing its test-mode fallback to silently pick bundle zero. A real Scroll Boxes `AfterObtained` continuation suspends with two native-derived bundle snapshots and stable `choose_option` actions; selecting one completes the assembly-owned task with the exact selected native card models, and the shipped continuation adds those three cards.

The same coordinator covers shipped `RelicSelectCmd.FromChooseARelicScreen`, including its native Skip outcome, and returns the exact selected shipped relic instance to the continuation. This relic selector has no production call site in the inspected build, so its coverage is an API-boundary test rather than a claim that a current encounter reaches it.

### Creature targets

Creature selection in shipped combat cards occurs at the play-card target boundary rather than through a separate blocking selector. `AnyEnemy` and `AnyAlly` targets derive from native `IsValidTarget`; self/non-target cards correctly pass null. The inspected build has no separate blocking combat creature-choice command. The only additional shipped player-target call site found is `MendRestSiteOption`, and `RestSiteOption.Generate` adds Mend only when `RunState.Players.Count > 1`; it is therefore unreachable in the supported single-player environment rather than silently automated. Run-level reward, rest-site, and event choices are exposed by their native coordinators.

## Audited run-start (Neow) contract

`neow_run_reset` is the faithful run start. Its wire record accepts only `game_build`, `seed`, `character`, and `ascension`; there is deliberately no field for a deck, relic, potion, hand, enemy, or RNG counter, so no caller can forge the post-Neow state it is asking the shipped lifecycle to produce.

### Pinned unlock profile

The worker owns the unlock profile, which is pinned to the shipped `UnlockState.all` instance (`unlock_profile: "unlock_state_all"`: every timeline epoch revealed including `NEOW_EPOCH`, every encounter seen, and a run count high enough that no first-run tutorial ordering applies). It is pinned rather than caller-supplied because the profile decides the whole Act 1 world, and it is published in `hello.run_start`, in the Neow observation's `run_start` block, and in `diagnostics.run_identity`.

### Lifecycle

The lifecycle is the E0 contract's fixed sequence, run only after the run-only construction phase:

```text
GenerateRooms
→ GenerateMap
→ AddVisitedMapCoord(StartingMapPoint.coord)
→ EnterMapPointInternal(1, MapPointType.Ancient, null, saveGame: false)
→ capture and await the fire-and-forget BeginEvent scheduled task
→ the Neow decision
```

Its run construction differs from every other mode's in two ways, both required for fidelity with production's own start seam:

- it passes `UnlockState.all` to `Player.CreateForNewRun`;
- it builds the `RunState` with `RunState.CreateForNewRun` (what `NGame.StartNewSingleplayerRun` calls) instead of `CreateForTest`.

Before generating the world it also performs the same `CombatManager.Reset(graceful: true)` cleanup the composed-run map path performs, because shipped `Reset(graceful: false)` keeps the previous run's stale `CombatState` reference and the next `SetUpCombat` refuses to start against it; without that cleanup a worker could serve only one run start per process.

`EnterMapPointInternal(..., saveGame: false)` does not update `State.VisitedMapCoords`, so the lifecycle adds the starting coordinate first exactly as the production `EnterMapCoord` path does. The probe evidence behind this sequence, including the plain-console crash chains that force an engine-hosted process, is recorded in [first-combat-e0-launch-contract-report.md](first-combat-e0-launch-contract-report.md).

### Enforced preconditions

Before the Neow decision is returned, every E0 precondition is asserted against shipped state rather than re-derived:

- `ExtraRunFields.StartedWithNeow` is true;
- `StartingMapPoint.PointType` is `Ancient`;
- the starting event id is `NEOW`;
- the event exposes at least one option after its scheduled begin task is awaited;
- `Hook.ShouldAllowAncient` accepts it;
- every travelable first-floor node is a `Monster`.

Reflection drift in a pinned enum member this seam depends on (`MapPointType.Ancient`) fails as `unsupported_build_contract`; a profile that cannot produce Neow fails as `neow_unavailable`. Neither degrades to a direct reset or a synthetic post-Neow state.

### Decisions

Decisions are ordinary protocol actions. Neow's options are `choose_event` actions whose identity is the shipped option's `text_key`. Every blessing's nested choice runs through the shipped machinery unchanged — `choose_cards` for the deck selectors (New Leaf, Precise Scissors, Pomander, Hefty Tablet, Lead Paperweight, Massive Scroll), `choose_option` for the bundle and relic screens (Scroll Boxes), and `choose_custom_reward`/`skip_custom_rewards` for reward sets (Lost Coffer, Small Capsule, Large Capsule, Kaleidoscope, Neow's Bones). No blessing is identified or reimplemented by relic id.

Once the event is finished, an explicit `proceed_neow` action moves the coordinator to the map decision, which is computed by `MapTravel.GetTravelablePointsFrom(runState, StartingMapPoint)` — the seam the map screen itself uses — rather than by enumerating the current point's children. `proceed_neow` performs no game-state mutation: the finished event room stays on the stack so the next native `EnterMapPointInternal` exits it exactly as production does.

Entering the first node then starts the combat natively and reaches `combat.turn == 1 && phase == Play` with no `Player`/`RunState` rebuild anywhere between Neow and that boundary. `diagnostics.run_identity` exposes stable `RuntimeHelpers` identity hashes of the `RunState`, `Player`, and player `Creature` for a validation run to compare across RPCs. The internal `_runStage` values `neow` and `neow_map` are coordinator bookkeeping only, and `neow_map` is left as soon as the first coordinate is entered, so the Neow-only travel seam cannot leak into a later Act 1 map decision.

Combat entry from the map is a suspendable native transition. A blessing can grant a relic whose combat-entry lifecycle opens a native card choice — Gambling Chip's discard selection runs from `AfterPlayerTurnStart` while the combat is starting — and awaiting the raw start task would make the worker sit silently on an unresolved choice until the client timed out. Routing map-entry combat start through the same transition coordinator the other native transitions use turns that into a first-class `card_choice` decision, which the existing action protocol resolves before the root is reached.

### First-combat root enumeration

`python/sts2_native_sim/first_combat.py` turns the run-start seam into a reusable enumeration of first-combat roots. For one `seed` + `character` + `ascension` it walks the protocol's own legal actions from the Neow decision — every `choose_event` option, every nested `choose_cards`/`choose_option`/`choose_custom_reward`/`skip_custom_rewards` selection, the `proceed_neow` coordinator action, and every legal first-floor `choose_map` action — and stops exactly at `combat.turn == 1 && combat.phase == Play`. It only ever follows legal actions the worker exposes, so a generated outcome that offers the player no choice contributes no fabricated branch.

- Branches are identified by their ordered action trace (`branch_identity`), never by surface deck, relic, encounter, or state-hash equality: the enumeration keeps every trace, so the several first-floor map points that roll the same encounter stay separate records instead of collapsing into one.
- A node is reached by re-driving the run-start recipe — `neow_run_reset` followed by the recorded actions — rather than by restoring a sibling's state, which keeps branches mutually independent and makes each root a genuine replay recipe rather than a memory snapshot: `neow_run` provenance, the recorded trace as history, and the root hash as expected hash, plus the root observation, legal actions, complete run RNG counters, build identity, and the first-floor route (coordinate, point type, and the enemy side of the encounter).
- `EnumerationLimits` explicitly bounds actions per branch, recorded roots, and expanded nodes; hitting a cap, meeting a terminal or unsupported decision, or finding no legal action appends an `EnumerationFailure` and marks the seed `complete=False`, and `assert_complete()` refuses to release a truncated walk as a complete corpus.
- Records are canonically ordered (roots by trace, failures by reason and trace) and serialised, so the same input produces byte-identical records.
- `replay_first_combat_root`, `restore_first_combat_root`, and `portable_restore_first_combat_root` expose the three reconstruction paths for reuse, and the root-state and equivalence assertions are the same ones the acceptance gate uses.

The root record is a replay recipe, not a native memory snapshot: restoring it replays the Neow prefix and cannot be described as keyframe or low-cost restore.

## Presentation suppression

The persistent environment enables the shipped automation switch `NonInteractiveMode.AutoSlayerCheck = () => true`. This natively suppresses gameplay presentation waits, including `BygoneEffigy.InitialSleepMove -> Cmd.Wait(0.5f)`; `Cmd.Wait` is not patched.

It also uses the Phase 1b presentation-only prefixes: `CreatureCmd.TriggerAnim`, the power-card fly animation, card-pile and Sovereign Blade previews, speech bubbles, the card-reward screen factory, void `SfxCmd` and `ThinkCmd` methods, informational `Log.Info`, visual `NCardPlayQueue` bookkeeping, visual branches of `CardPileCmd`, and the damage-number, thrown-potion, ground-fire, and large-missile VFX factories.

For composed rooms, only room asset preload, screen clearing/fade, combat FTUE creation, and event scene-node creation are additionally suppressed; room models, room stacks, history, hooks, combat startup, event synchronization, rewards, and exits remain native. Fabricator's spawned Guardbot, Noisebot, Stabbot, and Zapbot retain native spawn/RNG/power/AI mechanics while their `TestMode.IsOff` node-positioning blocks are suppressed as presentation-only.

Headless replay-file recording is disabled while coordinator state hashes and action histories remain active. Explicit shipped `TestMode` presentation guards are suppressed only in audited call scopes; global test mode remains off. Native power application, damage, pile mutation, reward generation/selection, RNG, potion effects, and hooks remain active.

`TestMode.IsOn` (the shipped test seam) and the game's mod loader are mutually exclusive: `ModManager.Initialize` sets `State = Skipped` under test mode. The full-application bridge therefore cannot use it and relies on explicit Harmony presentation patches instead.

## Verification entry points

Acceptance scripts, their gates, and the recorded results (including fault injections, recorded stale expectations, and measured performance) are maintained in [persistent-environment-evidence.md](persistent-environment-evidence.md). Exact shipped-game differential evidence, and its deliberately non-global certification scope, is owned by [differential-trace-format.md](differential-trace-format.md), [trace-exporter.md](trace-exporter.md), and [isolated-autotrace.md](isolated-autotrace.md).
