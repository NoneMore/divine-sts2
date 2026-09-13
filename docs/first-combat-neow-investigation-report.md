# Investigation Report: Faithful Batch Generation of Post-Neow First-Combat Training States in `divine-sts2`

**Date:** 2026-09-13  
**Scope:** First combat only, immediately after the Act 1 Neow blessing flow  
**Primary target repository:** [`favet/divine-sts2`](https://github.com/favet/divine-sts2)  
**Supporting repository:** [`hotwords123/StS2.RandomForeseer`](https://github.com/hotwords123/StS2.RandomForeseer)  
**Reverse-engineered game source used for behavioral cross-checking:** [`Hexpion/Slay-the-spire-2`](https://github.com/Hexpion/Slay-the-spire-2)

---

## 1. Executive Summary

The best design for generating training data for the **first combat after Neow** is:

> **Run Neow, resolve all blessing-side choices, enter the first map combat, and only then snapshot/fork the state — all inside the same native `RunState` / `Player` object.**

This is materially safer than synthesizing a “post-Neow” `ResetRequest` and reconstructing the player before the first fight.

The key reason is not only RNG fidelity. Neow relics can modify hidden or partially modeled state that the current `ResetRequest` does not fully represent. A concrete example is **Phial Holster**, whose `AfterObtained()` increases potion capacity and generates random potions. The current `ResetRequest` can specify potion contents, but it does not expose potion slot capacity as a first-class field.

For first-combat training, the problem can be simplified substantially compared with reproducing an entire run:

- Neow option generation uses an **event-local RNG**, not the main run combat RNG streams.
- Many Neow effects consume player-level reward/transformation RNG that will not matter during the first fight.
- The first fight itself is driven by `RunRngSet` streams such as `Shuffle`, `MonsterAi`, `CombatCardGeneration`, `CombatTargets`, and others.
- Once the first combat reaches **Turn 1 / Play**, the training system can stop caring about map generation, future rewards, shops, and later events.
- At that boundary, exporting a portable branch/snapshot is the cleanest and fastest basis for massive parallel rollouts.

The recommended implementation is therefore to refactor `PersistentNativeCombatEnvironment` so that run construction and combat construction are separate operations, and then introduce a run-start path that composes:

```text
ConstructRun
    ↓
GenerateRooms
    ↓
GenerateMap
    ↓
Begin native NEOW event
    ↓
resolve Neow option + nested choices
    ↓
return to map
    ↓
choose first reachable combat node
    ↓
enter native first combat
    ↓
Turn 1 / Play
    ↓
export portable branch
    ↓
parallel combat rollouts / training data generation
```

The most important architectural change is to avoid the current `run_reset()` behavior where `Reset()` first constructs a synthetic combat and only afterward switches into run/map mode. For a production-quality first-combat corpus generator, `run_reset()` should construct only the run state before generating the map.

---

## 2. Investigation Goal

The target use case is deliberately narrow:

> Generate many faithful first-combat states corresponding to real Slay the Spire 2 runs after Neow, then use those states for combat-policy training.

This report does **not** require full-run fidelity after the first fight. In particular, it is acceptable if future shop, reward, transformation, or event RNG would diverge after the fight, provided that:

1. the first combat begins from the same effective state as the real game,
2. the combat itself consumes the same relevant RNG streams,
3. all legal combat actions and native hooks behave identically,
4. complete combat trajectories remain deterministic under replay.

This distinction allows us to avoid implementing unnecessary run-wide state serialization.

---

## 3. Repositories and Evidence Base

### 3.1 `favet/divine-sts2`

Inspected commit:

```text
7cb715916fc9abfb0281c0adf4939c74468e05a4
```

Important files include:

- `src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs`
- `src/Sts2.NativeSim.Protocol/Messages.cs`
- `src/Sts2.NativeSim.TraceExporter/TraceExporterMod.cs`
- `src/Sts2.NativeSim.FullAppBridge/FullAppBridgeMod.cs`
- `python/native_rollout_farm.py`
- `python/run_room_entry_acceptance.py`
- `python/run_option_reward_acceptance.py`
- `python/combat_breadth_acceptance.py`
- `docs/persistent-environment.md`

### 3.2 `hotwords123/StS2.RandomForeseer`

Inspected commit:

```text
86f1300b94c9efc24bd6793c59e5faabc2833bb7
```

Important files include:

- `RandomForeseerCode/OutOfCombat/RelicPickupPrediction.cs`
- `RandomForeseerCode/InCombat/Simulation/CombatPredictionRngSet.cs`
- `RandomForeseerCode/Common/PotionPrediction.cs`
- documentation and changelog entries related to Neow prediction.

### 3.3 `Hexpion/Slay-the-spire-2`

Inspected commit:

```text
64ed626b7ec9692bc54536b0123fc3cb580c28da
```

This repository appears to contain reverse-engineered / decompiled source and should therefore be treated as a behavioral reference rather than an official source distribution.

Important files include:

- `src/Core/Entities/Rngs/RunRngType.cs`
- `src/Core/Entities/Rngs/PlayerRngType.cs`
- `src/Core/Runs/RunRngSet.cs`
- `src/Core/Runs/RunState.cs`
- `src/Core/Runs/RunManager.cs`
- `src/Core/Models/EventModel.cs`
- `src/Core/Models/AncientEventModel.cs`
- `src/Core/Models/Events/Neow.cs`
- `src/Core/Models/Relics/PhialHolster.cs`
- `src/Core/Models/MonsterModel.cs`

---

## 4. What `divine-sts2` Already Provides

`divine-sts2` is already much closer to the desired system than a fresh simulator would be.

### 4.1 Persistent native workers

The project provides persistent workers that reuse the shipped game assembly rather than reimplementing combat rules in Python.

Its README includes a parallel rollout farm:

```bash
python python/native_rollout_farm.py \
  --workers 6 \
  --episodes 100 \
  --ascension 1 \
  --summary-only
```

The rollout farm maintains persistent `NativeWorker` objects, feeds them episode specifications, calls `run_reset()`, and then advances them with native legal actions.

This is exactly the right infrastructure for large-scale training-data generation.

### 4.2 Custom reset protocol

`ResetRequest` already supports:

- seed
- character
- ascension
- encounter
- current/max HP
- gold
- full deck
- initial hand
- relics
- potions
- run RNG counters
- enemies
- initial draw pile
- combat-entry hooks
- native character starting loadout

This is enough to reconstruct many isolated combat states.

However, it is not a complete serialization of a live player/run.

### 4.3 Native run/map entry

The project already supports:

```text
run_reset
→ choose_map
→ native room entry
→ combat
```

`python/run_room_entry_acceptance.py` verifies that a state produced by `run_reset()` can select a map coordinate and enter a native combat at Turn 1.

### 4.4 Native nested reward and option handling

`run_option_reward_acceptance.py` demonstrates that the simulator can:

- create a relic reward,
- obtain Scroll Boxes,
- suspend on a native option choice,
- choose one of the card bundles,
- replay/restore the choice deterministically,
- export and restore branches.

This is important because several Neow outcomes involve nested choices.

### 4.5 Portable branch / fork / restore

The project already has the right mechanism for the expensive-vs-cheap split:

- expensive once: construct run → resolve Neow → enter first fight,
- cheap many times: restore first-fight root and run combat rollouts.

This should be central to the production architecture.

---

## 5. RNG Architecture in Slay the Spire 2

One of the most important findings is that StS2 does **not** use one global deterministic RNG stream for all run events.

### 5.1 Run-level RNG streams

`RunRngType` contains:

```text
UpFront
Shuffle
UnknownMapPoint
CombatCardGeneration
CombatPotionGeneration
CombatCardSelection
CombatEnergyCosts
CombatTargets
MonsterAi
Niche
CombatOrbs
TreasureRoomRelics
```

Each stream is initialized independently from the run seed and a stream-specific name.

Relevant implication:

> Consuming RNG in one category does not automatically shift every other future random result.

For first-combat fidelity, the most obviously relevant streams are:

- `Shuffle`
- `MonsterAi`
- `CombatCardGeneration`
- `CombatPotionGeneration`
- `CombatCardSelection`
- `CombatEnergyCosts`
- `CombatTargets`
- `CombatOrbs`
- `Niche`

Rather than guessing a minimal subset, the safest first-combat root snapshot should preserve **all Run RNG counters**.

### 5.2 Player-level RNG streams

`PlayerRngType` contains:

```text
Rewards
Shops
Transformations
```

These matter heavily for full-run reproducibility, but many of them are irrelevant once the first combat starts.

Examples:

- Neow relic generation may use `PlayerRng.Rewards`.
- transformations may use `PlayerRng.Transformations`.
- shop generation uses `PlayerRng.Shops`.

If the only target is the first fight, these streams do not necessarily need to be serializable after the fight starts, provided that Neow itself was executed natively before combat.

---

## 6. Does Neow Consume RNG?

Yes, but the answer is more nuanced than “Neow advances the seed.”

### 6.1 Neow option generation uses event-local RNG

`EventModel.BeginEvent()` constructs an RNG specifically for the event based on run seed, owner identity, and event ID.

`Neow.GenerateInitialOptions()` then uses that event RNG for:

- selecting the cursed option,
- several boolean choices,
- shuffling positive options,
- taking the final positive options.

Therefore:

> Merely generating and displaying the Neow options does **not** advance `RunState.Rng.Shuffle`, `MonsterAi`, `CombatTargets`, etc.

This is excellent for branching: inspecting or enumerating Neow choices need not perturb the first-combat run RNG streams.

### 6.2 Obtaining a Neow relic can consume other RNG streams

The selected relic is obtained through normal native relic acquisition:

```csharp
await RelicCmd.Obtain(relic, owner);
```

That means its native `AfterObtained()` effect executes.

Different Neow relics consume different RNG streams.

#### Phial Holster

`PhialHolster.AfterObtained()`:

1. increases maximum potion count,
2. creates random out-of-combat potions,
3. uses `RunState.Rng.CombatPotionGeneration`.

This directly modifies a run RNG stream that may later be used during combat.

#### New Leaf

RandomForeseer predicts New Leaf using `RunState.Rng.Niche`.

#### Leafy Poultice

RandomForeseer uses `PlayerRng.Transformations`.

#### Neow's Bones

RandomForeseer explicitly simulates random Neow relic acquisition using reward RNG and contains logic to fast-forward pickup effects before predicting curses.

Its changelog also documents a bug caused by failing to account for RNG consumption from obtaining generated relics in the correct order.

This is strong evidence that “manually copy final inventory” is not always equivalent to “actually resolve the Neow blessing.”

---

## 7. First-Combat RNG Dependencies

For first-combat training, the relevant question is:

> Which state can affect any observation, legal action, or future transition before combat ends?

### 7.1 Deck order

Native combat construction calls:

```text
PopulateCombatState(... RunRng.Shuffle ...)
```

So `Shuffle` directly affects draw-pile order and therefore the entire combat trajectory.

### 7.2 Enemy intent

`MonsterModel.RollMove()` uses:

```text
RunRng.MonsterAi
```

Therefore initial enemy intent and later AI decisions depend on the correct `MonsterAi` stream position.

### 7.3 Generated cards, random targets, energy costs, orbs, etc.

RandomForeseer's combat prediction simulator mirrors native combat using the following cloned run RNGs:

```text
Shuffle
CombatCardGeneration
CombatPotionGeneration
CombatCardSelection
CombatEnergyCosts
CombatTargets
CombatOrbGeneration
```

This is a useful empirical list of combat-active RNG categories.

### 7.4 `Niche` can also matter in combat

`Niche` is not purely “out of combat.” Some monster or relic mechanics use it during combat.

Therefore the conservative and recommended policy is:

> Save and restore the complete `RunRngSet` counter map at the first-combat root.

---

## 8. Why Reconstructing a Post-Neow `ResetRequest` Is Not Sufficiently Faithful

A synthetic post-Neow state is tempting because the protocol already accepts deck/relic/HP/gold/RNG data.

For quick experimentation, it can work.

For a canonical training corpus, it has several structural problems.

### 8.1 Missing hidden player state

The protocol does not serialize every field a relic may modify.

The clearest example is Phial Holster:

```text
AfterObtained:
  + max potion slots
  + random potions
```

`ResetRequest` can include potion contents but currently does not expose “max potion slots.”

If the relic is merely inserted with `AddRelicInternal`, its pickup effect should not be rerun because that would duplicate random effects. But if it is not rerun, the slot-capacity side effect is absent.

Both choices are wrong.

### 8.2 Pickup effects may alter internal relic state

A relic can mutate:

- dynamic variables,
- counters,
- player fields,
- card state,
- potion capacity,
- reward state,
- grab bags,
- or other model-specific data.

Some of this can be represented with `native_state`, but not all of it is guaranteed to be captured by the public reset schema.

### 8.3 Player RNG is not represented by current `rng_counters`

`divine-sts2`'s `rng_counters` restoration logic is based on:

```text
RunRngType
SerializableRunRngSet
```

It does not represent `PlayerRngType` counters.

That is acceptable for first-combat training **if Neow executes natively before the fight**, but it makes a fully synthetic post-Neow reset incomplete.

### 8.4 Ascension effects can be reapplied during reconstruction

`PersistentNativeCombatEnvironment` calls the native test setup lifecycle. The code comments explicitly note that Ascension 10 may add `ASCENDERS_BANE` after the supplied deck is constructed.

If a post-Neow deck already includes all ascension modifications and the reset lifecycle applies them again, special handling is required to avoid duplication.

### 8.5 Conclusion

The synthetic path should be classified as:

```text
Useful:
  benchmark scenarios
  isolated unit tests
  hand-authored combat states
  approximate training experiments

Not ideal:
  canonical "real first combat after Neow" corpus
```

---

## 9. The Current `run_reset()` Has a First-Combat-Fidelity Problem

The current implementation is approximately:

```csharp
public EnvironmentResult RunReset(ResetRequest request)
{
    Reset(request);
    _runMode = true;
    _runStage = "map";
    InitializeRunMap();
    return Capture(...);
}
```

But `Reset(request)` itself calls `Construct(request)`, which constructs a combat.

During that construction the code:

1. selects an encounter,
2. generates monsters,
3. creates a `CombatState`,
4. resets player combat state,
5. calls `PopulateCombatState` with `RunRng.Shuffle`,
6. initializes combat details.

Only later does it restore supplied RNG counters.

This currently works because `RunRngSet.LoadFromSerializable()` can rewind a stream by recreating it from the seed when the requested counter is lower than the current one.

However, for a production-grade first-fight generator, relying on:

```text
construct fake combat
→ consume RNG
→ restore counters backward
→ generate map
```

is unnecessary and increases the number of hidden assumptions.

The clean fix is architectural: do not construct combat for a run reset.

---

## 10. Recommended Refactor: Separate Run Construction from Combat Construction

Refactor the current `Construct()` into two conceptual stages.

### 10.1 `ConstructRun`

Responsibilities:

```text
create/select character
create player
create or preserve starting loadout
attach supplied deck when appropriate
create RunState
initialize native run services
apply ascension effects
install supplied relic state when appropriate
install potion state when appropriate
establish stable card instance IDs
restore desired pre-run RNG counters if needed
```

This stage must not:

- create an encounter,
- create a combat state,
- shuffle the deck for combat,
- roll enemy moves.

### 10.2 `ConstructCombat`

Responsibilities:

```text
resolve encounter
generate monsters
create CombatState
attach player
ResetCombatState
PopulateCombatState(Shuffle)
execute room/combat entry hooks
roll initial monster moves
apply optional exact enemy/hand/draw-pile overrides
```

### 10.3 Revised method behavior

Recommended:

```text
reset
  → ConstructRun
  → ConstructCombat

run_reset
  → ConstructRun
  → GenerateRooms
  → GenerateMap

neow_run_reset
  → ConstructRun
  → GenerateRooms
  → GenerateMap
  → Begin native Neow event
```

This makes the lifecycle explicit and eliminates synthetic RNG consumption.

---

## 11. Recommended New Run Mode: `neow_run_reset`

A dedicated method is preferable to trying to overload plain `run_reset()` with implicit Neow behavior.

Conceptually:

```text
neow_run_reset(starting_run_spec)
```

returns a decision state whose legal actions are Neow options.

### 11.1 Initialization sequence

The desired sequence is:

```text
ConstructRun
InitializeRunServices
GenerateRooms
GenerateMap
Begin Neow
```

The important ordering is:

> Generate the Act 1 world before resolving Neow.

This mirrors the game's real startup lifecycle more closely and prevents an obtained Neow relic from incorrectly changing generation that should already have happened.

### 11.2 Why Neow should be part of run mode, not a standalone `event_reset`

`event_reset()` already knows how to initialize an event and select options.

However, a standalone event reset reconstructs state around the event.

For the training-data use case, the important property is:

> The same `Player` and `RunState` object must survive continuously from Neow acquisition into the first combat.

Therefore the ideal change is to reuse event machinery *inside* run mode rather than running Neow as an isolated event episode and then serializing its result.

---

## 12. Reuse Existing Event and Reward Infrastructure

The project should avoid adding Neow-specific simulations for each relic.

Use shipped game behavior.

Existing pieces already cover most of the hard work.

### 12.1 Native event selection

The environment already has:

```text
choose_event
ChooseEventAsync(optionIndex)
```

### 12.2 Native relic pickup

The game's `AncientEventModel.RelicOption(...)` executes:

```csharp
await RelicCmd.Obtain(relic, owner);
```

Thus all real `AfterObtained()` behavior runs.

### 12.3 Nested option choices

Scroll Boxes is already demonstrated through existing reward/choice coordinator code.

### 12.4 Nested relic generation

Small Capsule, Large Capsule, Neow's Bones, and similar outcomes should be routed through native acquisition and existing choice/reward machinery rather than manually emulated in Python.

---

## 13. Branching Strategy for Training Data

If the target model is a **combat policy**, Neow policy should not arbitrarily limit the corpus.

A strong corpus-generation strategy is to branch over all legal Neow outcomes.

For one seed:

```text
seed
 ├─ Neow positive option A
 │   ├─ first reachable combat route 1
 │   ├─ first reachable combat route 2
 │   └─ ...
 │
 ├─ Neow positive option B
 │   └─ ...
 │
 └─ Neow cursed option
     └─ ...
```

If a blessing has subchoices:

```text
Scroll Boxes
 ├─ bundle A
 └─ bundle B
```

or generated relic branches:

```text
Capsule / Neow's Bones
 ├─ generated result path A
 └─ generated result path B
```

then fork those too when economically reasonable.

### 13.1 Why branching is particularly safe here

Neow option generation uses event-local RNG.

Therefore forking option choices does not inherently consume the run's `Shuffle`/`MonsterAi` streams just by inspecting alternatives.

The simulator's existing fork/restore machinery is a natural fit.

### 13.2 Dataset diversity benefit

A single seed can produce several legitimate first-combat states differing in:

- deck composition,
- relics,
- potions,
- HP/max HP,
- combat RNG offsets,
- reachable first-floor encounter,
- opening hand,
- enemy intent.

That is valuable diversity for combat training.

---

## 14. Where to Place the Snapshot Boundary

The best snapshot boundary is:

```text
combat.turn == 1
combat.phase == Play
```

At this point:

- Neow is fully resolved.
- Map routing is fully resolved.
- The native encounter exists.
- enemies exist,
- initial enemy intent has been rolled,
- combat-entry relic hooks have run,
- opening card state exists,
- all relevant run RNG streams are in the correct positions.

After this point, future map/reward/shop state is irrelevant to first-combat training.

Immediately export:

```python
portable = worker.export_branch()
```

Then use the portable first-combat root for many combat-only rollouts.

---

## 15. Two-Tier Farm Architecture

The corpus generator should have two distinct execution tiers.

### Tier A — first-combat root generation

Relatively expensive.

```text
seed
→ run construction
→ map generation
→ Neow
→ nested choices
→ first map selection
→ native first combat
→ Turn 1 Play
→ portable snapshot
```

Each distinct branch produces one first-combat root.

### Tier B — massive combat rollout

Very cheap relative to full startup.

```text
portable first-combat root
   ├─ worker 1 rollout/search
   ├─ worker 2 rollout/search
   ├─ worker 3 rollout/search
   └─ ...
```

This lets Neow/map startup cost be amortized over:

- MCTS,
- beam search,
- random-policy exploration,
- teacher policy trajectories,
- value estimation,
- counterfactual action labels.

---

## 16. Suggested Corpus Record Schema

A robust root record should include at least:

```json
{
  "schema_version": "...",
  "game_build": {
    "version": "...",
    "assembly_sha256": "...",
    "pck_sha256": "..."
  },

  "seed": "...",
  "character": "IRONCLAD",
  "ascension": 0,

  "neow": {
    "option_index": 0,
    "option_model_id": "...",
    "subchoices": [...]
  },

  "route": {
    "map_coord": {"col": 0, "row": 0},
    "encounter_id": "..."
  },

  "root": {
    "state_hash": "...",
    "rng_counters": {...},
    "observation": {...},
    "legal_actions": [...]
  },

  "portable_branch": "... or separate blob reference ...",

  "labels": {
    "teacher_policy": null,
    "value": null,
    "victory": null,
    "hp_loss": null,
    "turns": null
  }
}
```

For large-scale storage, the portable branch may be better stored separately and referenced by content hash.

---

## 17. Train/Validation/Test Split Policy

Do **not** randomly split battle roots.

Split by seed.

Reason:

```text
seed A + Neow option 1
seed A + Neow option 2
seed A + Neow option 3
```

share substantial latent structure:

- generated map,
- encounter pools,
- initial seed-derived randomness,
- character loadout,
- potentially similar deck state.

If related branches are spread across train and validation, evaluation leakage becomes likely.

Recommended:

```text
hash(seed) % N
```

or a fixed seed partition manifest.

All Neow/map branches of one seed should stay in the same split.

---

## 18. Validation Against a Ground-Truth Environment

`divine-sts2` documents `full_application_native` as the **Primary Authority**.

That mode launches the shipped application headlessly and uses native run initialization and room/combat transitions.

It should serve as the golden reference for the new fast path.

### 18.1 Golden test matrix

Recommended initial matrix:

```text
100–1000 seeds
× 5 characters
× representative ascension levels
× representative Neow outcomes
```

Prioritize tricky Neow relics:

```text
Phial Holster
New Leaf
Leafy Poultice
Neow's Bones
Scroll Boxes
Small Capsule
Large Capsule
```

These cover:

- combat RNG mutation,
- `Niche`,
- player transformation RNG,
- player reward RNG,
- nested choices,
- relic generation,
- potion capacity,
- deck mutation.

### 18.2 First-combat root comparison

At Turn 1 / Play, compare:

```text
character
ascension
current/max HP
gold if exposed
deck cards + upgrades + native state
hand
draw pile order
discard/exhaust piles
relics
relic counters
relic native state
potion slot count
potion contents
encounter ID
enemy composition
enemy HP/block
enemy powers
initial enemy move / intent
player powers
orbs / stars / character-specific state
all Run RNG counters
legal actions
state hash where schemas are aligned
```

### 18.3 Full-combat deterministic replay

Root equality is not enough.

Feed both environments the same deterministic action policy until combat ends.

After every action compare:

```text
observation
legal actions
Run RNG counters
state hash
terminal/victory state
```

The strongest acceptance condition is:

```text
same root
+
same action sequence
=
same entire first-combat trajectory
```

---

## 19. Combat-Entry Hooks Are Important

The current reset protocol supports:

```text
invoke_combat_entry_hooks
```

The environment can execute native relic lifecycle hooks such as:

```text
AfterRoomEntered
BeforeCombatStart
BeforeCombatStartLate
BeforeSideTurnStart
```

For a naturally entered first combat in run mode, these hooks should be part of the native room transition, not manually reconstructed.

This is another reason to prefer:

```text
Neow → map → real room entry
```

over direct combat reset.

---

## 20. Interaction with `encounter = "first"`

`encounter = "first"` in direct combat reset should **not** be interpreted as:

> “the encounter that this seed would naturally see on the first map floor.”

In the current environment it resolves essentially to the first catalog encounter when doing direct reset.

Therefore it is useful for acceptance scenarios but not as the canonical method for producing seed-faithful first fights.

For real first-fight generation:

```text
GenerateMap
→ choose a reachable first-floor map node
→ let native run entry select/generate the encounter
```

---

## 21. Recommended API Shape

A clean Python-facing API could look like:

```python
state = worker.neow_run_reset({
    "seed": seed,
    "character": character,
    "ascension": ascension,
    "use_character_starting_loadout": True,
})
```

Expected state:

```text
decision.kind == "event_choice"
event.id == "NEOW"
```

Then:

```python
state = worker.run_step(neow_action)
```

If nested:

```text
option_choice
reward_choice
card_choice
...
```

resolve until:

```text
decision.kind == "map_choice"
```

Then:

```python
state = worker.run_step(first_map_action)
```

Advance internal transitions until:

```text
observation.combat.turn == 1
observation.combat.phase == "Play"
```

Finally:

```python
portable = worker.export_branch()
```

---

## 22. Suggested Corpus Generator Structure

High-level Python structure:

```python
for seed in seeds:
    root = worker.neow_run_reset(run_spec(seed))

    neow_branches = enumerate_neow_branches(root)

    for neow_branch in neow_branches:
        state = resolve_native_neow_branch(neow_branch)

        assert decision_kind(state) == "map_choice"

        for first_route in enumerate_first_combat_routes(state):
            combat = enter_route(first_route)

            combat = advance_until_player_play_phase(combat)

            assert combat["observation"]["combat"]["turn"] == 1
            assert combat["observation"]["combat"]["phase"] == "Play"

            portable = worker.export_branch()

            write_root_record(
                seed=seed,
                neow_trace=...,
                route=...,
                state=combat,
                portable=portable,
            )
```

For throughput, this should use a queue-based worker farm similar to `native_rollout_farm.py`.

---

## 23. Worker-Pool Considerations

`NativeWorkerPool.reset_all()` broadcasts one identical scenario to all workers.

For heterogeneous seeds, use the generic pool mapping mechanism rather than `reset_all`.

A production generator should preferably follow the queue/persistent-worker pattern already used by `native_rollout_farm.py`, because:

- seeds differ,
- Neow branching creates uneven workloads,
- nested choices have variable depth,
- some seeds produce more first-combat roots than others.

Static fixed-size batches may underutilize workers.

---

## 24. Important Correctness Risks

### 24.1 Game-version drift

All native behavior is version-sensitive.

Every root record should persist:

```text
game version
assembly SHA-256
PCK SHA-256
simulator commit
corpus schema version
```

Do not mix roots from different game builds without explicit version conditioning.

### 24.2 Reverse-engineered source mismatch

The Hexpion repository is useful for reading the game architecture, but the shipped assembly used by `divine-sts2` remains the authority.

Any disputed behavior should be resolved by:

1. shipped assembly execution,
2. FullAppBridge golden trace,
3. state-hash / trajectory comparison.

### 24.3 Hidden UI-only state

Avoid depending on UI state wherever possible.

Use model/run objects and native command/event paths.

### 24.4 Relic acquisition order

Neow's Bones demonstrates that pickup ordering can matter.

Do not normalize or sort nested acquisition sequences unless the shipped game does.

### 24.5 Branch identity

Different Neow subchoices can sometimes converge to visually similar inventories but distinct hidden states.

Deduplicate only by a sufficiently strong content/state hash, not by superficial deck/relic tuples.

---

## 25. What Does Not Need to Be Perfect for This Project

Because the scope is first combat only, the following can be deprioritized after the combat root has been captured:

```text
future PlayerRng.Rewards fidelity
future PlayerRng.Shops fidelity
future PlayerRng.Transformations fidelity
future relic grab-bag state
future event RNG
future card rewards
future treasure RNG
future map routing
```

They matter only if they can influence the current first combat.

The key invariant is:

> Do not reconstruct the player between Neow and the first combat.

Once the first fight has begun, preserve the native combat state and complete `RunRngSet`.

---

## 26. Recommended Implementation Milestones

### Milestone 1 — Refactor construction

Split:

```text
Construct
```

into:

```text
ConstructRun
ConstructCombat
```

without changing existing direct-combat behavior.

Add regression tests for all current reset acceptance suites.

### Milestone 2 — clean `run_reset`

Change `run_reset()` so it no longer creates a synthetic combat before generating the map.

Verify existing map/run acceptance behavior.

### Milestone 3 — Neow-in-run mode

Add a run stage such as:

```text
_runStage = "neow"
```

and initialize native Neow after map generation.

Reuse event action builders and nested-choice coordinators.

### Milestone 4 — first-fight root exporter

Add helper logic:

```text
resolve Neow
→ return to map
→ choose first combat
→ stop on Turn 1 Play
→ export portable branch
```

### Milestone 5 — golden validation

Compare new fast path to `full_application_native`.

Require full first-combat deterministic equality across a representative test matrix.

### Milestone 6 — corpus farm

Build:

```text
generate_first_combat_corpus.py
```

with options such as:

```bash
--workers 20
--episodes 100000
--characters IRONCLAD,SILENT,DEFECT,NECROBINDER,REGENT
--ascension 0
--neow-policy exhaustive
--first-route-policy exhaustive
--output roots.jsonl.gz
```

### Milestone 7 — training rollout farm

Consume portable roots and generate:

- policy labels,
- action-value estimates,
- complete trajectories,
- terminal outcome statistics.

---

## 27. Recommended Acceptance Tests

Add explicit tests for:

### A. Neow option determinism

Same seed/character/ascension:

```text
same Neow legal options
same option metadata
same state hash
```

### B. Neow fork isolation

Fork before choosing Neow option.

Resolve option A, restore, resolve option B.

Verify that inspecting A did not perturb B's run RNG counters.

### C. Phial Holster

Verify after native pickup:

```text
potion capacity
potion contents
CombatPotionGeneration counter
```

match FullAppBridge.

### D. New Leaf

Verify:

```text
deck transformation result
Niche counter
```

### E. Leafy Poultice

Verify transformed/basic-card behavior and downstream first-combat equality.

### F. Neow's Bones

Verify:

- generated relic identities,
- acquisition order,
- generated curse(s),
- resulting run RNG counters,
- resulting first combat.

### G. Scroll Boxes

Verify native nested choice replay and exact deck result.

### H. Ascension 10+

Verify `ASCENDERS_BANE` appears exactly once and first-combat root matches FullAppBridge.

### I. Full combat replay

For each representative root, run a fixed deterministic combat policy and compare every state to ground truth.

---

## 28. Performance Expectations

The optimal throughput strategy is to avoid replaying startup for every combat branch.

Approximate cost structure:

```text
run + map + Neow + first-room entry:
  relatively expensive

portable root restore:
  cheap

combat branch:
  cheap / highly parallel
```

Therefore one generated root should support many training samples.

For example:

```text
1 first-combat root
× 32 restored workers
× multiple candidate action branches
× complete trajectories
```

This can multiply training value per native startup by orders of magnitude.

---

## 29. Final Recommendation

For this project, the strongest practical design is:

> **Faithfully execute only the prefix that matters, then snapshot at the exact boundary where the learning problem begins.**

That prefix is:

```text
native run initialization
→ native map generation
→ native Neow
→ native Neow pickup/subchoices
→ native first map entry
→ native first combat initialization
```

The learning boundary is:

```text
Turn 1
PlayerTurnPhase.Play
```

At that point:

- export a portable branch,
- store the complete observation,
- store all Run RNG counters,
- store legal actions and provenance,
- use restored combat roots for all subsequent training rollouts.

Do **not** make synthetic post-Neow `ResetRequest` reconstruction the canonical corpus path.

Synthetic reset remains valuable for tests and controlled experiments, but the continuous native-run path removes an entire category of hidden-state and RNG-fidelity bugs.

The most important code change is therefore not “add more RNG counters.” It is:

> **Split run construction from combat construction so Neow and the first combat can share one unbroken native `RunState` and `Player`.**

---

## 30. Source References

### `favet/divine-sts2`

- Persistent environment:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs>

- Protocol messages / `ResetRequest`:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/src/Sts2.NativeSim.Protocol/Messages.cs>

- Trace exporter:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/src/Sts2.NativeSim.TraceExporter/TraceExporterMod.cs>

- Full application bridge:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/src/Sts2.NativeSim.FullAppBridge/FullAppBridgeMod.cs>

- Persistent environment documentation:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/docs/persistent-environment.md>

- Native rollout farm:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/native_rollout_farm.py>

- Run room-entry acceptance:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/run_room_entry_acceptance.py>

- Native relic-triggered option acceptance:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/run_option_reward_acceptance.py>

- Combat breadth acceptance:  
  <https://github.com/favet/divine-sts2/blob/7cb715916fc9abfb0281c0adf4939c74468e05a4/python/combat_breadth_acceptance.py>

### `hotwords123/StS2.RandomForeseer`

- Neow/relic pickup prediction:  
  <https://github.com/hotwords123/StS2.RandomForeseer/blob/86f1300b94c9efc24bd6793c59e5faabc2833bb7/RandomForeseerCode/OutOfCombat/RelicPickupPrediction.cs>

- Combat RNG set:  
  <https://github.com/hotwords123/StS2.RandomForeseer/blob/86f1300b94c9efc24bd6793c59e5faabc2833bb7/RandomForeseerCode/InCombat/Simulation/CombatPredictionRngSet.cs>

- Potion prediction:  
  <https://github.com/hotwords123/StS2.RandomForeseer/blob/86f1300b94c9efc24bd6793c59e5faabc2833bb7/RandomForeseerCode/Common/PotionPrediction.cs>

- Workshop behavior notes:  
  <https://github.com/hotwords123/StS2.RandomForeseer/blob/86f1300b94c9efc24bd6793c59e5faabc2833bb7/workshop/description.en.txt>

### `Hexpion/Slay-the-spire-2`

- Run RNG enum:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Entities/Rngs/RunRngType.cs>

- Player RNG enum:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Entities/Rngs/PlayerRngType.cs>

- Run RNG implementation:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Runs/RunRngSet.cs>

- Run state:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Runs/RunState.cs>

- Run manager:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Runs/RunManager.cs>

- Event model:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Models/EventModel.cs>

- Ancient event model:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Models/AncientEventModel.cs>

- Neow:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Models/Events/Neow.cs>

- Phial Holster:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Models/Relics/PhialHolster.cs>

- Monster model / AI RNG:  
  <https://github.com/Hexpion/Slay-the-spire-2/blob/64ed626b7ec9692bc54536b0123fc3cb580c28da/Slay%20the%20Spire%202/src/Core/Models/MonsterModel.cs>

---

## 31. Short Decision Record

**Decision:** Use a continuous native run from Neow through first combat, then snapshot at Turn 1 / Play.

**Rejected as canonical path:** Reconstructing a manually synthesized post-Neow `ResetRequest`.

**Primary reasons:**

1. incomplete player hidden-state serialization,
2. missing potion-capacity representation,
3. missing player RNG counters,
4. pickup-order sensitivity,
5. ascension reapplication risk,
6. unnecessary synthetic-combat construction in current `run_reset()`.

**Required core refactor:**

```text
Construct
→ ConstructRun + ConstructCombat
```

**Required new composition:**

```text
neow_run_reset
→ ConstructRun
→ GenerateRooms
→ GenerateMap
→ Begin Neow
```

**Corpus snapshot boundary:**

```text
first combat
turn == 1
phase == Play
```

**Validation authority:**

```text
full_application_native
```

**Dataset split unit:**

```text
seed
```

---

_End of report._
