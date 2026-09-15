# Act 1 combat 1 parity findings

**Question:** for a given run seed, what must the simulator reproduce for a generated "act 1 first combat" scenario to be reachable — and identical — in the shipped game?

**Answer (short):** the map and the encounter *choice* are already correct and provably immune to the missing Ancient room; two other things are not. `TotalFloor` is off by one, which changes randomized intra-encounter monster composition, and the act-1 variant (`Overgrowth` vs `Underdocks`) is rolled in the shipped game but hard-coded in the simulator, which changes the entire encounter/event/boss pool.

**Sources:** static reading of the shipped decompiled build (`sts2.dll` v0.107.1). Game citations are relative to the decompiled root `MegaCrit/sts2/`; repo citations are relative to the repo root. Nothing here has been confirmed at runtime yet.

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

Act 1 has two models, both `Index => 0`: `Overgrowth` (`IsDefault => true`, `Core/Models/Acts/Overgrowth.cs:49-51`) and `Underdocks` (`false`, `Core/Models/Acts/Underdocks.cs:44-46`). The shipped game rolls the variant with `new Rng(hash(seed), "act_selection")` (`Core/Multiplayer/Game/Lobby/StartRunLobby.cs:463-465`), with an override that forces an undiscovered non-default act (`Core/Models/ActModel.cs:550-554`) and a lobby setting that can pin it (`StartRunLobby.cs:495-506`). The simulator hard-codes `ActModel.GetDefaultList()` (`src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs:404`), so it always plays `Overgrowth`.

Map *topology* is variant-independent (identical `GetMapPointTypes`, `BaseNumberOfRooms`, `NumberOfWeakEncounters`), but the encounter pools (22 vs 20), event pools (13 vs 10) and bosses differ — so for a seed whose act 1 is `Underdocks`, every act-1 room the simulator plays is the wrong one.

Note the interaction with ADR-0001: the discovery override depends on `SaveManager.Progress.DiscoveredActs`, and "fully unlocked" deliberately does not imply discovered content, so the variant must be pinned explicitly rather than inherited from profile state.

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

## The oracle's own projection is thin

Parity can only be checked through the full-app bridge, so the bridge's combat observation is on the critical path. Inventoried against the contract, it is missing or wrong in roughly three dozen combat-relevant fields: the encounter id; ordered draw, discard, exhaust and play piles (draw/discard/exhaust are counts only, and the play pile has no representation at all); card instance ids, card type, cost-x, enchantment and native state; the full intent list, of which only the next move's id is present; a creature `side`; the player's own creature row; max energy; stars; the granular turn phase; RNG counters; act floor; map coordinate; relic counters and native states; potion slots (empty slots are skipped, which destroys the slot index); and game build.

Three of those are worse than absent because they look present: the act index is reported **one-based** where the rest of the system is zero-based, hand cards carry an upgrade-level field that is never populated so it always reads zero, and hand energy cost reads a different accessor than the other projections. A comparison that trusts these would report parity while comparing the wrong numbers.

The richest existing realization of the contract is the trace exporter's per-combat projection, which already carries almost all of it — the encounter id, the ordered draw pile, per-card identity, upgrades, enchantment, costs, intents and powers. The bridge should converge on that rather than become a third shape. The two encoders' state hashes are not comparable by construction (one is versioned and kernel-hashed, the other hashes its own DTO), so parity has to be compared field by field.

## Still open

- **No field-by-field parity comparison has been run yet.** The evidence above establishes that the oracle starts and can be driven; it does not compare a single field. Before it can, the bridge's own combat observation must carry every field of the parity contract — it does not today (the encounter id and the ordered draw pile are known gaps), which is why extending that seam belongs to this feature rather than to a prerequisite someone else owns.
- **The `TotalFloor` and Act-variant divergences remain static conclusions.** The cheapest empirical check is to compare the first combat's monster ids and HP for one seed between a real run and the simulator, and to repeat it for a seed whose act 1 is the non-default Act variant.
