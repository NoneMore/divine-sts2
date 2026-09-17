# 16: A run-mode reset must not build a combat the run never plays

**What to build:** The run-mode reset path must stop constructing a combat, because the combat it builds
consumes one monster-composition draw and one shuffle of the starting deck from streams the first real
fight reads. Measured by ticket 15's field-by-field parity run: at the reset the simulator's run already
reports `Niche` 1 and `Shuffle` 9 before the Ancient room is entered, unchanged through the Ancient, and
at the row-1 fight `Niche` 2 and `Shuffle` 20 — while the shipped game's whole first fight, counted from
zero, costs one `Niche` draw and those same eleven `Shuffle` draws. Every generated scenario therefore
records a first fight whose enemy HP and ordered piles are not the shipped game's, which is what the
parity gate reports at `$.run.rng_counters.Niche` and behind it at `$.creatures[].hp` and every card of
the hand and draw pile.

**Where:** `PersistentNativeCombatEnvironment.Reset` constructs `_combat`, calls
`GenerateMonstersWithSlots` and `PopulateCombatState(…, Shuffle)` unconditionally
(`src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs:455-466`), whatever the request is for.
A run-mode reset does not need a combat: the run stands on the map and the combat it will really fight is
built when it enters a monster room. A combat-mode reset still does.

**Status:** done

- [x] The request distinguishes a run reset from a combat reset, so the environment can know which one it
      is being asked for — an explicit field rather than an inference from which members happen to be set.
- [x] A run-mode reset consumes no `Niche` draw and no `Shuffle` draw: the counters at the reset equal
      the counters at run start, and entering the Ancient room and leaving it change neither.
- [x] A combat-mode reset is unchanged: the same state, the same hash, and the same counters as today.
- [x] The first row-1 fight of a generated scenario has the same `Niche` and `Shuffle` counters as the
      shipped game's for the same character, Ascension, seed, Act variant, Ancient choice and nested
      choices — which is ticket 15's parity run passing on fields that reach past the counters.
- [x] Every table recorded from a run reset is re-recorded, and the acceptances that own them say so:
      `python/scenario_record_acceptance.py`'s `_OBSERVED` and `_OBSERVED_CHOICES` state hashes,
      `python/act_variant_acceptance.py`'s `_BASELINE_COUNTERS` (`Niche` 1 / `Shuffle` 9 at reset), and
      any golden hash recorded from a run reset.
- [x] The observation schema version and the hash schema version are bumped only if a shape moved;
      values moving under a run reset is not a shape change.

**Why it is not ticket 15's:** the gate's job is to measure and localise, and it did. Repairing this is a
Core change whose blast radius is every table and golden hash recorded from a run reset, which is a
ticket of its own rather than a step inside the acceptance run.

## Comments

**2026-09-17 — implemented; the gate that was red is green.**

- **What was built.** `ResetRequest` gains `reset_mode` (`"combat"` or `"run"`, absent by default),
  declared by the Python client's `run_reset` and by the scenario generator's own run-start request,
  so the request says which reset it is instead of the environment inferring it from which members
  happen to be set. The declaration is optional and never overridden: a request that declares nothing
  is stood up as the reset the caller asked for by name, one that declares the *other* mode is
  refused (`invalid_reset`) rather than reinterpreted, and an unknown mode is refused too — which is
  why no protocol version moved, since a caller that omits the field (or a branch recorded before it
  existed) still gets exactly the reset it asked for. `PersistentNativeCombatEnvironment` splits
  `Reset` into `Declaring(request, mode)` — which resolves the mode onto the request that is stored,
  because a branch replays from that request and no method name survives it — `ResetState(request)`
  and its own capture. `RunReset` stands up the run and no combat, so `Construct` returns after the
  deck, relics, potions and run state are in place and never reaches `GenerateMonstersWithSlots` or
  `PopulateCombatState`. `_manager` stays the shipped singleton — the run's own room entry drives it
  — and holds no combat, because `CombatManager.SetUpCombat` refuses to set one up while it does;
  its `IsInProgress` and `IsStarting` flags are already false, because `Construct` ran the shipped
  `CombatManager.Reset(false)` first (as it does for every reset after the first), and `IsEnding`
  reads false while `IsInProgress` is false, so a `_state` of null is not read. The fight the run
  later enters is built by `RunManager.EnterMapPointInternal` → `CombatRoom.StartCombat`, which is
  where the shipped game builds it, and that path now names the cards it clones with the reset deck's
  own identities (`_deckInstanceIds`, consulted by `RebindEnteredCombat`), so a run-mode fight's card
  identity is what it was. Neither the observation schema version nor the hash schema version moved:
  no shape moved, only the values a run reset reports.
- **The three cases, asked of a live worker** (`artifacts/_reset_modes.py`): an undeclared
  `run_reset` stands up a run and still reports `Niche` 0 / `Shuffle` 0 (the compatibility case);
  `run_reset` declaring `combat`, `reset` declaring `run` and `run_reset` declaring `map` are each
  refused with `invalid_reset` and the worker stays usable.
- **The counters, measured stage by stage** with the generator's own run-start request
  (`ANC1ENT10`, IRONCLAD, A0, one native worker): the reset, the Ancient entered, its first choice
  taken and the Ancient left all report **no `Niche` and no `Shuffle` draw** — only `UpFront` 411,
  which is the run's own map — and at the row-1 fight the run reports `Niche` 1 and `Shuffle` 9,
  which is one monster-composition draw and one shuffle of the deck the run actually plays, counted
  from zero. Ticket 15's stage-by-stage measurement of the same drive before the repair read
  `Niche` 1 and `Shuffle` 9 at the reset itself, unchanged through the Ancient, and `Niche` 2 with
  `Shuffle` 18 at the fight — the reset's nine draws added to the fight's own nine.
  `python/ancient_room_acceptance.py` re-states the same property across its fifteen samples
  (the counters entering the Ancient equal the counters at the reset) and
  `python/act_variant_acceptance.py` holds the run's own counters at a run reset to the new
  baseline.
- **Ticket 15's gate passes: 14 of 14 samples matched field for field, 2 of 2 Act-variant probes
  measured the bound, `state_hashes_compared: 0`.** The enemy's generated HP, the ordered hand and
  draw pile, the counters and every other contract field now agree with the shipped game; the set of
  declared fields no sample exercised fell from the whole contract to the same four members ticket 15
  named (the potion slot and model and the two enchantment members), because a comparison that
  stopped at the first mismatch could not report what it reached. The report is in the gitignored
  `artifacts/parity-run/parity-run.json`; the oracle needed writes on the game's volume for the
  bridge's hard links, which this session's file policy refuses, so it ran under the same one-shot
  permission escalation ticket 15's run recorded. That run precedes the request-field redesign in the
  first bullet, which leaves a *declared* run reset exactly as it was — the client and the generator
  both declare it — and the run-mode state the final build stands up is re-evidenced there by the
  acceptances that drive it: `scenario_record_acceptance`, `portable_modes_acceptance`,
  `ancient_room_acceptance` and `act_variant_acceptance` all pass on it.
- **Every table recorded from a run reset was re-recorded, and each owner says why.**
  `scenario_record_acceptance.py`'s `_OBSERVED`/`_OBSERVED_CHOICES` (24 new state hashes; the recipes
  did not move, and its replay-from-the-record check still holds) and `act_variant_acceptance.py`'s
  `_BASELINE_COUNTERS` (`Niche` 1 / `Shuffle` 9 → 0 / 0, with every recorded map digest and every
  `UpFront` count unchanged — the act roll and map generation still consume nothing they should not).
  `observation_schema_acceptance.py --record` rewrote `tests/fixtures/canonical-observations.json`,
  which is also the cleanest evidence for "a combat-mode reset is unchanged": every `run_*` capture
  lost exactly the reset's 1 `Niche` and 9 `Shuffle` draws, and the five `standalone_*` captures —
  every one a combat-mode reset — are byte-identical to what they recorded before. The two remaining
  tables recorded on the old run-reset path did **not** move, and both acceptances assert that they
  did not: `act_variant_acceptance.py`'s `_BASELINE` (map digests and `UpFront` per seed) and
  `ancient_room_acceptance.py`'s `_PRE_CHANGE` (each seed's row-1 `entry_action` and its first-fight
  `composition`, recorded on the old path before the Ancient room was entered). They are baselines
  whose whole point is to stay put — the map and the act roll are RNG-independent of the reset, and a
  fixed-composition encounter's monsters do not randomise — and a run where either moves fails the
  acceptance that owns it. The evidence document
  `.scratch/act1-combat1-scenarios/parity-findings.md` now carries the repair, the re-measured
  counters and the green run in place of the red one.
- **"A combat-mode reset is unchanged" is a hash comparison now, not an argument.** One worker,
  every combat-mode reset the environment offers plus a played card, run against the build before
  this change and the build after it: `reset`, `reset` + a played card, `map_reset`,
  `reward_reset`, `item_reward_reset`, `custom_reward_reset`, `rest_reset` and `event_reset` all
  report the **same state hash on both builds** (for one fixed scenario, `34409767…` at the reset and
  `5807B698…` after the card). The repair touches only the run-mode branch, and this is the
  measurement that says so.
- **Verification.** `pwsh scripts/build-persistent-server.ps1` is clean in Debug and Release;
  `python -m pytest tests -q` is 181 passed and 22 errors, every one of them the documented `tmp_path`
  refusal, with the one new test among the 181; `ruff` and `mypy` report nothing on the changed files
  beyond the two findings those files already carried before this change
  (`client.py`'s pre-existing import order and blind excepts, and a pre-existing
  `append`-returning-`None` lambda in `tests/test_scenarios.py`). The acceptances that own the touched
  seams all pass: `act_variant_acceptance`, `scenario_record_acceptance`,
  `observation_schema_acceptance --record`, `portable_modes_acceptance` — which restores a run-mode
  branch on a second worker, so the repaired `Construct` is exercised through `RestoreAsync` too —
  `ancient_room_acceptance` and `parity_run_acceptance`.
