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

**Status:** ready-for-agent

- [ ] The request distinguishes a run reset from a combat reset, so the environment can know which one it
      is being asked for — an explicit field rather than an inference from which members happen to be set.
- [ ] A run-mode reset consumes no `Niche` draw and no `Shuffle` draw: the counters at the reset equal
      the counters at run start, and entering the Ancient room and leaving it change neither.
- [ ] A combat-mode reset is unchanged: the same state, the same hash, and the same counters as today.
- [ ] The first row-1 fight of a generated scenario has the same `Niche` and `Shuffle` counters as the
      shipped game's for the same character, Ascension, seed, Act variant, Ancient choice and nested
      choices — which is ticket 15's parity run passing on fields that reach past the counters.
- [ ] Every table recorded from a run reset is re-recorded, and the acceptances that own them say so:
      `python/scenario_record_acceptance.py`'s `_OBSERVED` and `_OBSERVED_CHOICES` state hashes,
      `python/act_variant_acceptance.py`'s `_BASELINE_COUNTERS` (`Niche` 1 / `Shuffle` 9 at reset), and
      any golden hash recorded from a run reset.
- [ ] The observation schema version and the hash schema version are bumped only if a shape moved;
      values moving under a run reset is not a shape change.

**Why it is not ticket 15's:** the gate's job is to measure and localise, and it did. Repairing this is a
Core change whose blast radius is every table and golden hash recorded from a run reset, which is a
ticket of its own rather than a step inside the acceptance run.
