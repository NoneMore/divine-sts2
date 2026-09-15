# 02: Derive the act-1 Act variant from the run seed

**What to build:** A simulated run started for a character, Ascension and run seed plays the same Act variant the shipped game rolls for that seed, instead of always playing the default one. For a seed whose act 1 is the non-default variant, every act-1 room the simulator plays comes from that variant's pools — encounters, events and boss alike — so the fight it produces is one the shipped game would reach. The variant in play is observable, so a caller never has to re-derive it.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] A run started for a seed whose act 1 is the non-default Act variant plays that variant: an act-1 encounter it produces belongs to the non-default variant's encounter pool.
- [x] A run started for a seed the shipped game resolves to the default variant still plays the default variant.
- [x] The variant in play is reported on the run observation.
- [x] Act 1's Ancient remains the act's own Ancient under both variants.
- [x] The variant is derived from the run seed and the run's own unlock state only; it does not silently depend on profile discovery state that can differ between machines.
- [x] The interaction between selecting a variant and ADR-0001's position that a fully unlocked run does not imply discovered content is recorded — as a clarifying sentence added to ADR-0001 or as a new ADR — rather than adopted silently.
- [x] Deriving the variant does not shift any RNG stream that the map, the encounter choice or a combat depends on.

## Comments

**2026-09-15 — implemented.**

- `PersistentNativeCombatEnvironment.ActListForSeed(seed, unlock)` replaces the hard-coded
  `ActModel.GetDefaultList()`. It reproduces the shipped roll exactly —
  `new Rng((uint)StringHelper.GetDeterministicHashCode(seed), "act_selection")` over
  `ActModel.GetRandomList` — with the local-progress consult pinned off, because the shipped
  singleplayer roll otherwise *forces* a non-default act the first time the machine's profile meets
  it (the save mock's `ProgressState.CreateDefault()` discovers no acts, so every seed would have
  played `Underdocks`). The run's own unlock state (`UnlockState.all`) decides eligibility; the seed
  alone decides which variant.
- The rolled list covers every act index, as the shipped roll does; acts 2 and 3 have exactly one
  candidate each (`Hive` `Index => 1`, `Glory` `Index => 2`, and `DeprecatedAct` is `Index => -1`,
  so it is not in `ActsByIndex`), so their outcome is unchanged and only act 1 can vary.
- The generator is created and discarded inside that call, so no run stream moves. The roll happens
  before `RunState.CreateForTest`, which builds the run's `RunRngSet` from the seed string. The
  shipped game canonicalises at `StartRunLobby.BeginRunForAllPlayersIfAllReady:725` and passes that
  string down to `BeginRunLocally:463`, whose roll is the one reproduced here; the simulator derives
  from the seed string it was handed, which is why the generator-side canonicalisation of ticket 07
  is what makes that the same string for a caller who passes a non-canonical seed.
- `ActVariant()` now reports the act in play as `run.act_variant` on the run observation, in every
  capture that reports run facts: combat, map, reward, rest, event, room rewards, and the shared
  `RunInventorySnapshot` (act transition, run terminal, treasure, shop, custom rewards). A caller
  never re-derives it.
- `sts2_native_sim.observations.extract_agent_observation` passes `act_variant` through to the
  agent projection, so the policy-facing view carries it while the seed stays masked.
- ADR-0001 gained a clarifying paragraph: Act variants are rolled from the run seed and the run's
  own unlock state, and discovery state is pinned off, because discovered content is profile
  history rather than unlocked content.
- `canonical-state.schema.json` now names `act_variant` in its `run` block, because v2 already
  under-documents what the environment emits. The observation and hash version bumps — and the full
  run-mode alignment — stay with ticket 05, which owns that work in the spec.
- **Observed** with the shipped game (a secondary Steam library install, build
  `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314`, assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`) through the Godot-hosted
  native worker, by the new `python/act_variant_acceptance.py`: 8 seeds resolved 4 `OVERGROWTH` /
  4 `UNDERDOCKS`, and every one agreed with an independent Python port of the shipped roll (the
  seed hash, the `act_selection` stream and xoshiro256\*\* arithmetic, over
  `ModelDb.ActsByIndex[0]` in database order). The same seed on a second worker reached the same
  variant, and the map, reward, item-reward, rest, event and custom-reward observations all reported
  the same variant as `run_reset`. The script pins the game-assembly hash its recorded baseline came
  from and fails closed on a mismatch, so a game update cannot silently re-baseline it.
- **Observed**, same run, for "no stream shifted": every seed's map digest is bit-identical to the
  one the pre-change build produced for that seed, and every run counter is identical too — the four
  default-variant seeds bit for bit, which is what rules the roll itself out, since the same roll ran
  for them. For the four seeds that flipped to `Underdocks` the only counter that moved is the
  encounter-pool draw (`UpFront`: 410/410/411/407 against 419/410/415/416), whose count follows the
  act's own encounter and event list sizes (22/13 for `Overgrowth`, 20/10 for `Underdocks`), exactly
  as the shipped game's does.
- **Partly observed**, for "an act-1 encounter comes from the non-default pool": the pools *are* the
  act in play's own lists (`ActModel.GenerateRooms` fills them from `Act`, and the two acts' weak
  pools name different monsters), and the pool draw above proves a different pool was built for the
  flipped seeds. The encounter's own identity cannot be asserted here — the combat observation does
  not name its encounter until ticket 05, and the row-1 travel it would need is ticket 03's — so that
  half is compared against the shipped game in ticket 15, on a non-default seed.
- Act 1's Ancient is `Neow` under both variants, by reading: `Overgrowth.AllAncients` and
  `Underdocks.AllAncients` are each `[Neow]` (`Core/Models/Acts/Overgrowth.cs:26`,
  `Underdocks.cs:22`), `GetUnlockedAncients` keeps it because `UnlockState.all` reveals
  `NeowEpoch`, and this change touches no Ancient selection. Not observable yet: the Ancient room is
  entered in ticket 03, which asserts it at the observation seam.

