# Act 1 combat 1 parity findings

**Question:** for a given run seed, what must the simulator reproduce for a generated "act 1 first combat" scenario to be reachable — and identical — in the shipped game?

**Answer (short):** the map and the encounter *choice* are already correct and provably immune to the missing Ancient room; two other things are not. `TotalFloor` is off by one, which changes randomized intra-encounter monster composition, and the act-1 variant (`Overgrowth` vs `Underdocks`) is rolled in the shipped game but hard-coded in the simulator, which changes the entire encounter/event/boss pool.

**Sources:** static reading of the shipped decompiled build (`sts2.dll` v0.107.1), plus the runtime observations under *Runtime evidence* and *The oracle's own projection is thin*, which say which of them were measured rather than read. Game citations are relative to the decompiled root `MegaCrit/sts2/`; repo citations are relative to the repo root. Every claim above the *Runtime evidence* heading is a static conclusion unless it says otherwise.

---

## Verified: the row-1 nodes are always normal monster nodes

`StandardActMap.AssignPointTypes` forces every row-1 point to `MapPointType.Monster` with `CanBeModified = false` (`Core/Map/StandardActMap.cs:271-275`), and `MapPathPruning.RepairPointType` only rewrites points already typed `Monster` with `CanBeModified == true` (`Core/Map/MapPathPruning.cs:61-63`); `MapPostProcessing` never touches `PointType` (`Core/Map/StandardActMap.cs:106-108`). So the first node travelled after the Ancient node is always a normal monster node, in every `StandardActMap` act.

It is also always a **weak** encounter: the pool order is fixed at run creation, with its first `NumberOfWeakEncounters` (=3) entries drawn from `AllWeakEncounters` (`Core/Models/ActModel.cs:348-359`; `NumberOfWeakEncounters` at `Core/Models/Acts/Overgrowth.cs:45` and `Underdocks.cs:40`), and the first monster node resolves to `normalEncounters[0]` (`Core/Rooms/RoomSet.cs:72`).

## Verified: skipping the Ancient room shifts no RNG stream

`EventModel.BeginEvent` gives every event its own `Rng` (`Core/Models/EventModel.cs:238`), keyed on the run seed + player slot + `hash(eventId)`, and `Neow.GenerateInitialOptions` draws only from it (`Core/Models/Events/Neow.cs:215-294`) — 16-19 draws, depending on the rolled curse. `AncientEventModel.BeforeEventStarted` consumes none (`Core/Models/AncientEventModel.cs:170-191`). Independently:

- **map layout** — `new Rng(runState.Rng.Seed, $"act_{n}_map")`, a fresh counter (`Core/Map/StandardActMap.cs:113`); the map is also generated *before* the Ancient is entered (`Core/Runs/RunManager.cs:1242-1249`).
- **encounter choice** — the ordered pools are filled at run creation from `Rng.UpFront` (`Core/Runs/RunManager.cs:681`, `Core/Models/ActModel.cs:331-386`), before any room is entered.
- **combat streams** — `Shuffle` (draw order), `MonsterAi` (intents) and `Niche` (enemy HP) are independent counters.

## Gap 1: `TotalFloor` is off by one

`TotalFloor => MapPointHistory.Sum(c => c.Count)` (`Core/Runs/RunState.cs:158`), and `EnterMapPointInternal` appends one entry per travelled point before entering the room (`Core/Runs/RunManager.cs:846`). At the first act-1 combat the shipped game has two entries — Ancient, then Monster — so `TotalFloor == 2`; the simulator has one, so `TotalFloor == 1` (`src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs:864`).

`TotalFloor` seeds the per-encounter Rng, `(uint)((int)Rng.Seed + TotalFloor + hash(encounterId))` (`Core/Models/EncounterModel.cs:268`), which drives *intra-encounter composition* (e.g. which small slimes, `Core/Models/Encounters/SlimesWeak.cs:48-58`). Fixed-composition encounters are unaffected; randomized ones are not. `TotalFloor` also gates events (`Core/Models/Events/PunchOff.cs:41-44`) and is stamped into relic metadata (`Core/Commands/RelicCmd.cs:52`).

Fixes: **(a)** enter the Ancient node for real, which appends the entry naturally; **(b)** synthesize the missing history entry before entering row 1.

## Gap 2: the act-1 variant is rolled, not fixed

Act 1 has two models, both `Index => 0`: `Overgrowth` (`IsDefault => true`, `Core/Models/Acts/Overgrowth.cs:49-51`) and `Underdocks` (`false`, `Core/Models/Acts/Underdocks.cs:44-46`). The shipped game rolls the variant with `new Rng(hash(seed), "act_selection")` (`Core/Multiplayer/Game/Lobby/StartRunLobby.cs:463-465`), with an override that forces an undiscovered non-default act (`Core/Models/ActModel.cs:550-554`) and a lobby setting that can pin it (`StartRunLobby.cs:495-506`). **Ticket 02 removed this gap**: the simulator now makes the same roll over the run's own unlock state (`ActListForSeed` in `src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs`), with the discovery override pinned off, and reports the result as `run.act_variant`.

Map *topology* is variant-independent (identical `GetMapPointTypes`, `BaseNumberOfRooms`, `NumberOfWeakEncounters`), but the encounter pools (22 vs 20), event pools (13 vs 10) and bosses differ — so for a seed whose act 1 is `Underdocks`, every act-1 room the simulator plays is the wrong one.

Note the interaction with ADR-0001: the discovery override depends on `SaveManager.Progress.DiscoveredActs`, and "fully unlocked" deliberately does not imply discovered content, so the variant must be pinned explicitly rather than inherited from profile state. ADR-0001 now records that pinning.

## Couplings worth knowing

- The act-1 map depends on **ascension** as well as seed: `AscensionLevel.SwarmingElites` (A1) changes the elite node count from 5 to `round(5 × 1.6) = 8` (`Core/Map/MapPointTypeCounts.cs:14`).
- `WearyTraveler` (A2) multiplies the Ancient heal by 0.8, so post-Ancient HP is `(int)(0.8 × MaxHp)`, not full (`Core/Models/AncientEventModel.cs:180-183`).
- `TightBelt` (A4) removes one potion slot and `AscendersBane` (A5) appends a curse to the starting deck (`Core/Entities/Ascension/AscensionManager.cs:56-65`).
- `ToughEnemies` (A8) and `DeadlyEnemies` (A9) change monster stats, not the encounter's identity.

## Settled since the first draft

- **The simulator does set `StartedWithNeow = true`.** `RunManager.SetStartedWithNeowFlag` (`Core/Runs/RunManager.cs:504-507`) has exactly one call site, inside `InitializeNewRun` (`:452`), which the simulator reaches through `SetUpTest` (`:368-379`). The simulator's player carries `UnlockState.all` (`src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs:364-365`) and `EpochModel.AllEpochIds` includes `NeowEpoch` (`Core/Models/EpochModel.cs:74,100`), so the flag is true, the downgrade at `RunManager.cs:748-751` never fires, and the node at coord `(3,0)` stays `Ancient` — the same type a fully unlocked shipped run gives it. An earlier draft of this note claimed the simulator typed that node `Monster`; that was wrong.
- **`ActFloor` is not the divergent value; `TotalFloor` is.** At the first row-1 combat `ActFloor == 2` on both paths (it comes from `coord.row + 1`, `Core/Runs/RunManager.cs:788-796`). `TotalFloor` counts map-point history entries, so the shipped game has 2 (Ancient, then Monster) and the simulator has 1. A shipped run on a profile where the Neow epoch is *not* revealed also reaches 2, because it too travels through `(3,0)` — as a `Monster` room (`RunManager.cs:1252-1257`). The simulator is the only path that never enters row 0 at all.

## Seed entry in the shipped game

There is exactly one seed widget, and it is on the **Custom Run** screen: `%SeedInput` (`Core/Nodes/Screens/NCustomRunScreen.cs:316`) passes its text through raw (`:382-392`, `:740-743`), and canonicalization happens once, at run start, in `StartRunLobby.BeginRunForAllPlayersIfAllReady` — `SeedHelper.CanonicalizeSeed(Seed)` (`Core/Multiplayer/Game/Lobby/StartRunLobby.cs:725`; the guard at `:722-723` covers both singleplayer and host). `CanonicalizeSeed` is `ToUpperInvariant` + `O→0` + `I→1` + `Trim` (`Core/Helpers/SeedHelper.cs:32-39`). **Standard (non-custom) single-player has no seed entry at all** — it always uses `SeedHelper.GetRandomSeed()`, and `NCharacterSelectScreen.SeedChanged()` throws `NotImplementedException` (`Core/Nodes/Screens/NCharacterSelectScreen.cs:990-992`). Two paths bypass canonicalization: `NGame.Instance.DebugSeedOverride` and the dev-only `--autoslay --seed` (`Core/Nodes/NGame.cs:663-669`).

Consequence for this feature: a record's seed must be stored in the canonical form the shipped game derives, or it cannot be reproduced by pasting it into the Custom Run screen.

## Runtime evidence

Gathered by running the bridge acceptance (`python/full_app_bridge_acceptance.py`) against the shipped install in a secondary Steam library. **The full-app oracle works**: with the game root configured, the bridge started real headless game processes and 3 of 4 workers answered `hello` (ports 52839 / 52998 / 53143, startup 4.8–5.2 s) before the fourth failed during sandbox preparation.

Two prerequisites became concrete:

- **Discovery ignores the registry.** `find_game_root()` raised `DiscoveryError` until `STS2_GAME_ROOT` was set, because `_steam_roots()` (`python/sts2_native_sim/paths.py:21-43`) derives Steam roots only from `%PROGRAMFILES(X86)%`, `%PROGRAMFILES%` and `STEAM_PATH`, never from the registry `SteamPath`. On this machine Steam lives at `E:\Program Files (x86)\Steam` while `%PROGRAMFILES(X86)%` is `C:\Program Files(X86)`.
- **The sandbox must sit on the game's volume.** `prepare_sandbox` (`python/sts2_native_sim/full_app_client.py:36-57`) hard-links the install into a per-worker sandbox; hard links cannot cross volumes (`WinError 17`), so it fell back to `shutil.copy2` (`:53`) and exhausted the local drive (`WinError 112`). `default_sandbox_root()` (`paths.py:159-161`) is pinned to `%LOCALAPPDATA%` with no environment override, so 11.3 GB of copied installs accumulated before the failure. With the sandbox root on the same volume as the game the hard links succeed and nothing is copied.

**Observed since: the bridge's combat block carries the contract's combat fields.** By
`python/bridge_combat_observation_acceptance.py` (one headless worker, seed `A1B2C3D4E5`, `IRONCLAD`,
Ascension 0) on game assembly `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`.
The drive reaches the row-1 fight through `event → event → map` and the fight reports
`encounter: "SLUDGE_SPINNER_WEAK"` at `turn` 1, `phase: "Play"`, `energy` 3 of `max_energy` 3,
`stars` 0, state hash `DC382F57D14B72A793AA142A469E8858F666D4AB1E06481F512E616BAA65A7D6`; its two
creature rows are `IRONCLAD`/`Player` (80/80, `combat_id` 0, no `next_move`) and
`SLUDGE_SPINNER`/`Enemy` (39/39) whose `next_move` is `OIL_SPRAY_MOVE` with a `SingleAttackIntent`
of damage 8 and 1 repeat plus a `DebuffIntent` carrying neither `damage` nor `repeats`. Playing the
fight on to turn 2 observes a power row on the player (`WEAK_POWER`, amount 1) and reproduces the
same state hash `3AB581115FD74B392F360F5C50ECF35BCA645D206D469CD805FA633691DC29DF` on a second
worker. This is a field-*presence* check against the contract, not a comparison against a generated
record — the encounter id, the granular phase, energy, max energy, stars and the creature rows are
reported, while the ordered piles, the per-card fields, the run block and the inventory were still
the gaps at that point (the first two are since repaired; the paragraph below says which run observed
it).

**Observed since: the fight's five ordered piles and every card's identity are on the bridge.** By
`python/bridge_combat_observation_acceptance.py` (one headless worker, seed `A1B2C3D4E5`,
`IRONCLAD`, Ascension 0, same game assembly) on the same drive to the row-1 fight. The fight reports
five piles in order — `Hand`/`Hand` 5 cards, `DrawPile`/`Draw` 5, `DiscardPile`/`Discard` 0,
`ExhaustPile`/`Exhaust` 0, `PlayPile`/`Play` 0 — so the play pile exists and the three counts are
gone. The hand's five cards are four `STRIKE_IRONCLAD` at `energy_cost` 1 and one `BASH` at 2, each
`costs_x: false`, `upgrades: 0`, `target_type: AnyEnemy`, `card_type: Attack`, `native_state: {}`,
with `instance_id` `dynamic-0-…` through `dynamic-4-…` and the game's own `net_id` 0 through 4; the
draw pile is four `DEFEND_IRONCLAD` and one `STRIKE_IRONCLAD` (`net_id` 5–9), so the resolved cost
accessor is observed to charge a real cost rather than a canonical zero. The five piles hold all ten
cards of the deck. Reading the same state twice returns the draw pile in the same order with the
same identities, and after the first turn ends — a rebuilt observation — **10 cards keep the
identity they were minted with**, which is what the registry exists for. Bridge state hash
`2E5DC5C5453C879FB06AABFD8222918E1E30B1FF8F1C15D7D019AA31870583B9` at the fight and
`FD5A4EEE77C864880AC002DEB2350DAED2FC51F365443A44DE2E928FCCA55ACB` once a power is reported (the
player's `WEAK_POWER`, amount 1); both differ from the hashes recorded before this change because the
bridge's schema version moved with the shape, which is expected of a DTO-covering hash rather than a
state-covering one.

**Observed since: the bridge's run block, map coordinate, inventory and build are on the bridge too.**
By the same `python/bridge_combat_observation_acceptance.py` on the same drive and the same game
assembly. The observation carries `game_build` — version
`0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314`, assembly `A1F9E653…`, pck `42520EB8…`, byte for
byte the build the recorded captures carry, and identical in the worker's `hello` reply. At the
Ancient the run reports `map_coord {col: 3, row: 0}`, `act_index` 0, `act_variant` **`UNDERDOCKS`**,
`act_floor` 1 and `total_floor` 1; at the row-1 fight it reports `map_coord {col: 1, row: 1}` and
both floors 2, so the Ancient room is observed advancing the counter the per-encounter generator is
seeded with — the gap this feature was scoped around, now a measurement rather than a reading. The
seed is the requested `A1B2C3D4E5` and `gold` is 99 at both stages. `rng_counters` carries all twelve
of the run's own counters with the game's names — `UpFront` 404 throughout, `Niche` and `Shuffle`
moving 0 → 1 and 0 → 9 with the fight — which is the counter set a field-by-field comparison lines up
against a record's. The relics are `BURNING_BLOOD` then `BOOMING_CONCH` — the starting relic and the
one the first Ancient choice grants — each an object carrying its model id, its native state
(`{"HasTriggered": false}` on the first) and a counter only where the game shows one; the belt is
`[null, null, null]`: three slots, none filled, which is exactly the slot index a list of occupied
slots would have destroyed. Reading the same state twice returns the same run block and the same
inventory. The act variant is worth noting on its own: the shipped roll for this seed is the
**non-default** variant, so a v1 scenario sample built on this seed is one where the simulator's
hard-coded default would have played the wrong act-1 rooms.

Two of this ticket's fields are not observable as measurements at runtime, and the acceptance says
so rather than implying otherwise: **the hand's cost agreeing with the repository's other
projections of the same card** needs two projections of one hand card, which only the field-by-field
parity run will have (ticket 15), and **a real upgrade count** needs an upgraded card, which a
starting deck does not contain. Both accessors are pinned offline by
`tests/test_bridge_observation_shape.py` against the simulator's own card projection, and the
acceptance observes the fields present, typed and non-zero where the game charges energy.

## The oracle's own projection is thin

Parity can only be checked through the full-app bridge, so the bridge's combat observation is on the critical path. Inventoried against the contract **before this feature's bridge work landed**, it was missing or wrong in roughly three dozen combat-relevant fields: the encounter id; ordered draw, discard, exhaust and play piles (draw/discard/exhaust are counts only, and the play pile has no representation at all); card instance ids, card type, cost-x, enchantment and native state; the full intent list, of which only the next move's id is present; a creature `side`; the player's own creature row; max energy; stars; the granular turn phase; RNG counters; act floor; map coordinate; relic counters and native states; potion slots (empty slots are skipped, which destroys the slot index); and game build.

Three of those were worse than absent because they look present: the act index is reported **one-based** where the rest of the system is zero-based, hand cards carry an upgrade-level field that is never populated so it always reads zero, and hand energy cost reads a different accessor than the other projections. A comparison that trusts these would report parity while comparing the wrong numbers.

The richest existing realization of the contract is the trace exporter's per-combat projection, which already carries almost all of it — the encounter id, the ordered draw pile, per-card identity, upgrades, enchantment, costs, intents and powers. The bridge should converge on that rather than become a third shape. The two encoders' state hashes are not comparable by construction (one is versioned and kernel-hashed, the other hashes its own DTO), so parity has to be compared field by field.

**Repaired since, in the bridge's combat block.** The encounter id, the granular turn phase, energy, max energy and stars inside the combat block, a `side` on every creature, the player's own creature row, the full ordered intent list with each intent's type, damage and repeat count, and powers as model id and amount — the combat block is now worded the way the trace exporter and the simulator word it, and `combat.enemies` is gone. **The fight's five ordered piles followed, with the hand list and the three pile counts replaced by `combat.piles`** — one row per pile in the order every projection reports them, carrying the game's own word for the pile's type and its ordered `cards` — **and every card is now the simulator's own card row**: `instance_id`, `net_id`, `model_id`, `card_type`, `target_type`, `energy_cost`, `costs_x`, `upgrades`, `enchantment` when the card carries one, and `native_state`. The two fields that looked present while reading the wrong thing are repaired with them: the hand's cost reads `CardEnergyCost.GetResolved()` — the accessor the simulator's and the trace exporter's projections read — and the upgrade count reads `CardModel.CurrentUpgradeLevel` instead of being declared and never assigned. Card `instance_id` is the bridge's own (`dynamic-<ordinal>-<model id>`, minted by a registry that recalls an id for a card it has already seen and starts over with a new fight), while `net_id` is the game's and is reported literally, which is the split the parity contract's identity rule asks for.

**Repaired since, in the bridge's run block and inventory — so nothing of the contract is now missing.**
The flat `seed`/`ascension`/`act`/`floor`/`gold`/`relics`/`potions` members are gone and a fight
carries `game_build`, `run`, `map_coord` and `inventory` instead, each worded as the simulator's own
block is worded. The act index is the run's zero-based `CurrentActIndex` rather than `+ 1`, with the
Act variant beside it; both the act floor and the run's total floor are reported; the coordinate the
run stands on is reported, the row-0 Ancient included; the RNG counters are the run's own named
counters; relics are objects carrying their counter and native state rather than bare model ids; and
potions are one entry per slot with an empty slot kept as `null`, so no slot index is destroyed. All
of it is recorded as observed under *Runtime evidence* above, including the Ancient's own row-0
coordinate and the first fight's two floors.

Two pieces of the bridge's new shape are the bridge's own and need a translation rather than a
comparison, and the projection layer is where that belongs. **The coordinate**: the bridge reports it as
`map_coord` (`{col, row}`), the simulator reports the same value as `map.current` in its map capture and
as `map_col`/`map_row` in its scoring features, and a record carries the node it drove to as
`recipe.node`. **The potion's native state**: the bridge reports `native_state` on every occupied slot
and it is always empty, because the shipped potion has no saved scalar state; the record's potion row and
the published schema have only `slot` and `model_id`, so a comparison reads the two members the record
has. Everything else in the new blocks is word for word the simulator's, which is what lets the
comparison be a normalisation rather than a guess.

## Still open

- **No field-by-field parity comparison has been run yet.** The evidence above establishes that the
  oracle starts, can be driven, and now carries every field the contract names — the combat block,
  the fight's ordered piles and card rows, and the run block, coordinate, inventory and build. It
  still does not compare a single field against a generated record, which is ticket 15's projection
  layer and comparison; the bridge seam it needs is now complete.

- **The `TotalFloor` divergence remains a static conclusion.** The cheapest empirical check is to compare the first combat's monster ids and HP for one seed between a real run and the simulator.
- **The Act-variant roll is no longer static, but has not been compared against the shipped game.** Ticket 02's `python/act_variant_acceptance.py` runs the shipped install and confirms, for 8 seeds, that the simulator's variant matches an independent port of the shipped roll (4 `Overgrowth`, 4 `Underdocks`), that the map and the run's own counters do not move, and that the variant is reported on the run observation. What is still unmeasured is the other side of the claim: that a shipped run on a non-default seed plays the same act-1 rooms, which needs the field-by-field parity run on a non-default seed (ticket 15).
