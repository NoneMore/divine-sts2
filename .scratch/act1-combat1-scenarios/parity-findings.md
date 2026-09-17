# Act 1 combat 1 parity findings

**Question:** for a given run seed, what must the simulator reproduce for a generated "act 1 first combat" scenario to be reachable — and identical — in the shipped game?

**Answer (short):** the map and the encounter *choice* are already correct and provably immune to the missing Ancient room; three other things are not. `TotalFloor` was off by one and is repaired by entering the Ancient room — measured, the floors now agree at the first fight. The act-1 variant (`Overgrowth` vs `Underdocks`) is rolled in the shipped game and was hard-coded in the simulator, which is repaired by deriving it from the seed; what a field-by-field run adds is that the *shipped* side is the constrained one, because a fresh profile forces the non-default variant. And the first fight was not the same fight on the two sides until ticket 16: the run-mode reset built a throwaway combat the shipped game never builds, so the record's first fight was one `Niche` draw and one deck shuffle further along its streams than the game's, and the enemy HP and the whole draw order differed with it. That reset is now repaired and measured — a run-mode reset spends neither draw, and the fourteen-scenario parity run matches the shipped game field for field.

**Sources:** static reading of the shipped decompiled build (`sts2.dll` v0.107.1), plus the runtime observations under *Runtime evidence* and *The oracle's own projection is thin*, which say which of them were measured rather than read. The field-by-field parity run belongs to the runtime observations: it drove real shipped-game processes and compared 51 contract fields per scenario. Game citations are relative to the decompiled root `MegaCrit/sts2/`; repo citations are relative to the repo root. Every claim above the *Runtime evidence* heading is a static conclusion unless it says otherwise.

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
inventory, and the potion rows carry their slot and their model and no more, which is the record's own
row. The act variant is worth noting on its own: the shipped roll for this seed is the
**non-default** variant, so a v1 scenario sample built on this seed is one where the simulator's
hard-coded default would have played the wrong act-1 rooms. Bridge state hash
`8C6638C1768F703CE36E9BCF4DB6400EDCF28F0E9A899E29D2CA2B7991A5401F` at the fight and
`37F1CB880C8EE96CAEDD2D0529CA3649363779FDA52B1A8C534BB48B9D63717E` on the turn a power is reported
(bridge schema version 6, the one whose potion row is the record's row).

Two of this ticket's fields are not observable as measurements at runtime, and the acceptance says
so rather than implying otherwise: **the hand's cost agreeing with the repository's other
projections of the same card** needs two projections of one hand card, which only the field-by-field
parity run will have (ticket 15), and **a real upgrade count** needs an upgraded card, which a
starting deck does not contain. A third is the relic counter's *present* case: neither relic this
drive holds shows one, so what is measured here is the absent case and the shape of the member. All
three accessors are pinned offline by
`tests/test_bridge_observation_shape.py` against the simulator's own card projection, and the
acceptance observes the fields present, typed and non-zero where the game charges energy.

**Observed since: the card-select prompt an Ancient choice opens is on the bridge (ticket 14).** Two
runs, both against game assembly `A1F9E653…`, and one before-and-after pair that is the whole point
of the ticket.

*Before the seam existed*, the bridge reported nothing at this prompt, and the game log says what
answered it instead. On `TRACERBULLET` (`DEFECT`, Ascension 0), whose first Ancient choice is
`PRECISE_SCISSORS`, the run's own autoplay log carries `Auto-selected 1 card(s) for selection
prompt` — the random selector `AutoSlayer` installs, which the game consults before it would push any
card-selection screen, so the removal was decided before any bridge stage saw it. On `GYMSCENAR10`
(`IRONCLAD`, Ascension 0), whose second Ancient choice is `SCROLL_BOXES`, the log carries
`Handling screen: NChooseABundleSelectionScreen` twice and then `Action: Selecting card bundle` — a
bundle pick has no selector branch in the shipped game, so its screen appears and the shipped
autoplay's own handler answers it, not the bridge. Either way the run continued with the relic
granted and no observation naming the prompt: no room, no legal actions.

*With the seam*, by `python/bridge_card_select_acceptance.py` (four headless workers: three prompts and
the bundle bound): the bridge takes the card selector the game consults, reports the offered cards as
a stage of their own, and applies the caller's selection. Three Ancient choices are driven, one per
prompt kind the choices in this repository's sweep open:

- `TRACERBULLET`'s first choice grants `PRECISE_SCISSORS`, a one-card removal. The prompt is reported
  at stage `simple_card_select`, room `SimpleCardSelect`, offering the deck's ten cards in deck order —
  five `STRIKE_DEFECT`, four `DEFEND_DEFECT`, `ZAP`, `DUALCAST` — with ten
  `choose_card_select:{i}:{model}` actions naming each one and `details`
  `{min_select: 1, max_select: 1, selected: []}`. Selecting `choose_card_select:0:STRIKE_DEFECT` cost
  the deck exactly that card (10 → 9, three `STRIKE_DEFECT` left), the stages ran
  `event → simple_card_select → event → map`, and the prompt's own observation hashed
  `AAFDCB93B88451C7A7CB75BE184F051BF889C1B30347B5F4B786E6F155B85726`.
- `ANC1ENT01`'s third choice grants `PRECARIOUS_SHEARS`, which asks for **two** cards: the prompt
  reports `{min_select: 2, max_select: 2}` over the same ten, the second report offers the remaining
  nine with `selected: [STRIKE_IRONCLAD]`, the two selections cost the deck 10 → 8 with three
  `STRIKE_IRONCLAD` left, and the prompt's first observation hashed
  `7E1F39AB70A879E6807083B4260D0C1FC522FAEEF5A89271A9AF323D986F070B`.
- `ANCIENT01`'s third choice grants `HEFTY_TABLET`, whose pick-up offers a handful of rare cards to
  *add* and lets the player skip. Its prompt reports `{min_select: 0, max_select: 1}` over
  `[DEMON_FORM, FEED, MANGLE]`, offers the three card actions **and** `finish_card_select` — which is
  how a minimum of zero is skipped — and answering with `finish_card_select` advanced the run with an
  empty selection: the deck gained only the `Injury` Hefty Tablet adds whatever the player chooses
  (10 → 11) and none of the three offered cards, stages `event → simple_card_select → event → map`,
  prompt observation
  `02FD391C88F2A808A03FFD909FDAF992B5E5C47E68A3774BC4A0F2F0C5A0465E`. `ANCIENT01` is not a
  canonical seed — the shipped game canonicalises it to `ANC1ENT01`, whose offer is the one above —
  which is why both forms appear here.

All three reached the map afterwards, so the prompts and their resolutions are observed end to end
rather than inferred. What is *not* measured is the upgrade, transform and discard prompt the same
selector answers: they are read from the decompiled build's own call sites (every one of the thirteen
card-selection entry points in `CardSelectCmd` consults `Selector` before it would push a screen).

Two consequences worth stating plainly. **The deck card-select screen stage is untouched and is not
observed**: the shipped autoplay's selector answers before `NDeckCardSelectScreen` or
`NSimpleCardSelectScreen` is ever pushed — before this ticket as much as after it — so the bridge's
screen stages are not what a bridged run reaches for a card choice; the selector seam is. Its handler
is unmodified, and its stage block now reports the offered cards through the same helper the new stage
uses, so what it reports is unchanged while the two can no longer drift apart. **The bundle pick stays
undrivable, and that is now a measurement**: the same acceptance drives `GYMSCENAR10` to
`SCROLL_BOXES` and records that the only stage seen is `event`, `bundle_stage_reported` false, with the
relic granted — so `nested_kinds_this_seam_does_not_drive` names `option_choice` and ticket 15's
sample must state it. A relic pick (`RelicSelectCmd.FromChooseARelicScreen`) is the same kind and the
same gap. Neither `card_choice` nor the observation's shape moved the `schema_version`, which stays 6:
no DTO member changed, and the stage table in `python/sts2_native_sim/decision_vocabulary.py` lost
`card_choice` from `combat` and `card_reward` because a card select now reports that stage of its own.

Two more repairs came with it, and they are why the prompt is answerable at all. **The bridge's
decision boundaries are now serialised.** A room's loop re-reports the room while a prompt an effect
inside it opened is still open, and with two boundaries live at once the caller's action completed
whichever published last — so a caller that took longer than the room loop's 50 ms to answer a card
prompt would have had its answer delivered to the room and left the game blocked on the prompt. A
boundary now waits its turn, which keeps the caller's action with the decision it was shown. **A card
action that names nothing the prompt offers is refused to the caller**, because such an action is
answered by the game's own flow rather than by the loop that consumes every other action: the tracker
would throw on the game's task and the caller would wait for a boundary that never comes, so `step`
now checks a card action against the actions the bridge is reporting and answers with an error
instead. That the already-handled path is unchanged is measured too: the
`python/bridge_combat_observation_acceptance.py` control run after these changes reproduces the state
hashes recorded above for schema version 6 byte for byte —
`8C6638C1768F703CE36E9BCF4DB6400EDCF28F0E9A899E29D2CA2B7991A5401F` at the fight and
`37F1CB880C8EE96CAEDD2D0529CA3649363779FDA52B1A8C534BB48B9D63717E` on the turn a power is
reported.

**Observed since: the field-by-field parity run has been made, and it does not pass (ticket 15).** By
`python/parity_run_acceptance.py` on game assembly `A1F9E653…`, over a fixed sample of **fourteen**
generated scenarios — two characters (IRONCLAD, DEFECT), Ascensions 0 and 2, ten runs, every Ancient
choice whose pick-up this seam can drive — driven end to end: the generator records the row on a
native worker, a real headless game is started with the same character, Ascension and canonical seed,
travels the Ancient room, takes the choice at the index the record holds, answers the card prompt that
choice opens with the same rule the record used, travels to the recorded row-1 node, and stops at the
first fight.

*Every one reached a fight to compare* — the fourteenth, `IRONCLAD@A2/ANC1ENT19#1`, was lost to a
dropped game process on the first pass and re-driven on its own with `--only`, where it reached the
fight like the rest — and every one of them stood on the node the record names, held the relic its
choice grants and reported the encounter the record names. The card prompts were driven on the shipped
side in eight of them: a one-card removal (min 1, max 1), a two-card removal (min 2, max 2) and Hefty
Tablet's skippable pick-up (min 0, max 1), the stages running `event → simple_card_select → event →
map` each time; the prompt-free choices ran `event → event → map`.

**Every one differed, in 15 to 37 leaf paths, and the same one draw is in all of them.** Every sample's
differing set contains `$.run.rng_counters.Niche` one higher on the record than on the shipped run — 2
against 1, 3 against 2, 4 against 3, seed by seed — and `$.run.rng_counters.Shuffle` beside it. The
helper the comparison runs through keeps every mismatch, so the report names the *first* one in its own
sorted order and the count next to it; that first path is the enemy's `hp` in eleven of the fourteen
(44 against 45, 25 against 26, 26 against 25 — the sign follows the roll) and a hand card's
`card_type`/`model_id` in the other three. Nothing else in the run block differed: canonical seed,
Ascension, gold, Act variant, act index, act floor and total floor all agreed, so entering the Ancient
room does repair the floor bookkeeping this feature was scoped around. Behind the counters, the same
root cause moves the two things a policy actually reads — measured by keeping both sides of
`IRONCLAD@A0/ANC1ENT10#2`, the prompt-free `LARGE_CAPSULE` row: the enemy's `hp`/`max_hp` are 44 on the
record and 45 in the game, and the ordered piles differ outright (the record's hand holds `BASH` where
the game's holds `STRIKE_IRONCLAD`, and the draw pile is a different permutation, `Shuffle` 20 against
11 — a difference of exactly the nine draws the record had already spent before the fight).

**The root cause is the run-mode reset's throwaway combat, and it is measured stage by stage.** The
simulator's counters at each stage of one drive (`ANC1ENT10`, one native worker): at the *reset* — the
run sitting on the act map, before the Ancient and before any room — `Niche` is already 1 and `Shuffle`
already 9; they are unchanged at the Ancient and after leaving it; and at the fight they are 2 and 20
(18 for the choice that removes a card; the rows that draw a third `Niche` show 3 and 21). The shipped
run's whole fight costs one `Niche` draw and the same eleven `Shuffle` draws, counted from zero. So the
reset has already built a combat — one monster-composition draw and one shuffle of the starting deck —
that the shipped game has not built and will never play, and every stream the first real fight reads is
one draw ahead from that moment on. Read from the environment:
`PersistentNativeCombatEnvironment.Reset` constructs `_combat`, calls `GenerateMonstersWithSlots` and
`PopulateCombatState(…, Shuffle)` unconditionally (`:455-466`) whatever the request is for, a scenario
run's reset included.

That is a defect in the environment's reset path, not in the bridge, and it was filed as ticket 16
rather than repaired in that run: the fix is a Core change, and every table recorded from a run
reset moves with it — the generator's `_OBSERVED`/`_OBSERVED_CHOICES` state hashes and
`act_variant_acceptance`'s counter baseline among them. **Ticket 16 has since landed**, and the
entry below records the repair, the re-measured counters and the parity run that now passes.

**The Act-variant bound is a measurement now too, and it is why the compared sample is one variant.**
The shipped game forces act 1's non-default variant until a profile has met it
(`ActModel.GetRandomList` reads `SaveManager.Progress.DiscoveredActs`, `Core/Models/ActModel.cs:550`),
the bridge's sandbox profile is a fresh one, and the simulator pins that check off and lets the seed
alone decide (ADR-0001; ticket 02). Two probes — `SCENAR10A01` and `ANC1ENT01`, whose records are
`OVERGROWTH` — were driven to the Ancient on the shipped side and both report `UNDERDOCKS`, each on the
row-0 coordinate `{col: 3, row: 0}`. So on this oracle a shipped run plays `UNDERDOCKS` whatever the
seed rolls, and the fourteen compared scenarios are therefore the seeds whose roll is that variant;
the default-variant half of the dimension is unreachable here until the discovered-acts question the
spec's Further Notes defers is settled.

**What the comparison is, and what it is not.** Both observations go through one projection
(`sts2_native_sim/parity_projection.py`) into one shape of **50 declared field paths** and are compared
with the repository's existing per-path helper, `sts2_native_sim.parity.compare_snapshots` — the helper
the architecture review found with no caller, and which this comparison is now the caller of. It
flattens both projections into leaf paths and keeps *every* mismatch, so a turn-1 fight compares 134 to
172 leaves (every card and creature instance is one), and the report names the first field that moved in
the helper's own sorted order with the count and the whole set beside it — which is what makes a root
cause visible rather than only its first symptom. The projection is where the two encoders' vocabulary
is reconciled: the bridge's stage word and its granular turn phase are mapped onto the simulator's
decision kind through `decision_vocabulary`, and the act-index base is declared once, zero-based, for
both sides. Three things are named as **not** compared, each with its reason: the per-card
`instance_id`, which each encoder mints for itself (a card is compared as its position in an ordered
pile plus its attributes); an intent's implementing class, which the contract does not name; and either
side's `state_hash`. No hash is compared at any point — the report states `state_hashes_compared: 0` —
and it also names the four declared fields **no sample exercised** (the potion slot and the
enchantment members: a turn-1 fight holds no potion and enchants no card), so a field that is declared
and never read cannot be mistaken for one that was.

**Observed since: the reset defect is repaired, and the field-by-field run passes (ticket 16).** The
repair is the one this document localised: a reset request now declares what it is for
(`reset_mode`), and a *run* reset builds no combat at all — the run stands on its act map and the
fight it will really play is built by the shipped `CombatRoom` when the run travels into a monster
room, which is where that encounter's monsters are generated and the deck is shuffled. So the two
draws the old reset spent on a fight nobody played are not spent, and the first real fight reads
both streams where the shipped game does.

*The stage-by-stage counters, re-measured on the repaired build with the generator's own run-start
request* (`ANC1ENT10`, IRONCLAD, Ascension 0, one native worker): the reset, the Ancient entered,
the Ancient's first choice taken (a `card_choice`) and the Ancient left all report **no `Niche` and
no `Shuffle` draw at all** — the only counter that has moved is `UpFront` 411, which is the run's
own map — and at the row-1 fight the run reports `Niche` 1 and `Shuffle` 9. Counted from zero, that
is one monster-composition draw and one shuffle of the deck the run actually plays, which is what
the shipped run's whole first fight costs; the same drive measured before the repair (above) read 1
and 9 at the reset itself and 2 with 18 at the fight for this choice, the reset's nine draws added
to the fight's own nine.

*The parity run, re-run on the same sample and the same game assembly*, now reports **14 of 14
samples matched field for field** and **2 of 2 Act-variant probes measured the bound**, with
`state_hashes_compared: 0` and the same 50 declared field paths, the same three exclusions and the
same nested-choice coverage statement (`card_choice` measured, `option_choice` and
`custom_reward_choice` named as not covered) as the failing run above. The fight itself is what
matches now: the enemy's generated HP, the hand and the ordered draw pile, the counters and every
other contract field agree, where before every sample differed at
`$.run.rng_counters.Niche` with the HP and the piles behind it. The set of declared fields no
sample *exercised* fell from the whole contract to the same four members ticket 15 named — the
potion slot and model and the two enchantment members, none of which a turn-1 fight holds — because
a comparison that stops at the first mismatch cannot report which fields it reached.

*What moved with it, and was re-recorded.* `python/scenario_record_acceptance.py`'s `_OBSERVED` and
`_OBSERVED_CHOICES` (24 state hashes; the recipes — offer, choice, nested kinds, node, encounter —
did not move, and neither did the replay check that drives each row from its own fields).
`python/act_variant_acceptance.py`'s `_BASELINE_COUNTERS`, whose `Niche` 1 / `Shuffle` 9 became
`0` / `0`, with every recorded map digest and every `UpFront` count unchanged — which is also the
measurement that the act roll and the map generation still consume nothing they should not.
`tests/fixtures/canonical-observations.json`, re-recorded by
`python/observation_schema_acceptance.py --record`: the run-mode captures at the run's start and at
the Ancient lost exactly those 1 `Niche` and 9 `Shuffle` draws, the run-mode captures at the fight
and beyond lost the same 1 and 9 beside the state those streams generate (the fight's own enemy HP
and pile order), and the five `standalone_*` captures — every one of them a *combat*-mode reset —
are byte-identical, which is the shape of "a combat-mode reset is unchanged" as a measurement
rather than a claim. One thing that did **not** move: a run-mode fight's cards keep the deck
identities the record names them with (`starter-0-STRIKE_IRONCLAD` and so on) rather than being
minted fresh, so a corpus row's card identity is unchanged by the repair.

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
`recipe.node`. **Nothing else**: the relic row is the simulator's row key for key, and the potion row is
the simulator's row exactly — the one member that had no counterpart on the record side, a potion's
always-empty native state, was dropped rather than left for the comparison to ignore. Everything else in
the new blocks is word for word the simulator's, which is what lets the comparison be a normalisation
rather than a guess.

## Still open

- **The field-by-field parity comparison passes now that the reset defect is repaired.** The same
  fourteen-scenario sample, re-run on the same build after ticket 16, matched the shipped game field
  for field in all fourteen, with both Act-variant probes measuring the bound and no hash compared;
  the state that had been one `Niche` draw and one deck shuffle ahead — the enemy HP and the ordered
  piles — is the shipped state. What remains open is coverage rather than parity: the bundle and
  relic *option* picks are still undrivable, so eight of the sample's choices open a card select and
  the rest open nothing, and complete Ancient-choice coverage waits on that seam.

- **The `TotalFloor` divergence is measured now, and it is closed by entering the room.** At the first
  fight of every sample the run's act floor and total floor matched the shipped game's — both 2 — and
  the first differing contract field came after them. So repair (a) from the *Runtime evidence* entry
  above is what the record needs; the synthesize-a-history-entry fallback is not.

- **The Act-variant roll is measured on both sides now, and the shipped side is the constrained one.**
  Ticket 02's `python/act_variant_acceptance.py` confirms the simulator's variant matches an independent
  port of the shipped roll; ticket 15's probes confirm the other side of the claim is *not* reproduced by
  a shipped run on a fresh profile, which forces the non-default variant until its profile has met it.
  A shipped run that plays the seed's own variant needs a profile that has met `UNDERDOCKS` (or a
  multiplayer run, where the game skips the discovery check) — the discovered-acts question the spec's
  Further Notes records as an open ADR decision.
