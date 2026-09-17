# 15: Field-by-field parity run against the shipped game

**What to build:** The acceptance gate for the feature. For a fixed sample of about a dozen generated scenarios spanning characters and Ascensions, the shipped game is driven with the same character, Ascension, run seed, Act variant, Ancient choice and nested choices, and every field of the parity contract is compared against the record's combat initial state. The comparison goes through a projection layer that normalises the bridge's observation and the record into one shape — including the phase and decision-kind vocabulary mapping and the act-index base — and then uses the repository's existing per-path comparison helper, which was built for exactly this and currently has no caller. A mismatch names the field path that differed. The two encoders' state hashes are never compared, because they are incomparable by construction and a hash match would prove nothing. The evidence document records what has actually been observed at runtime, so a static conclusion is never mistaken for a measurement, and the sample states which nested-choice kinds it covers rather than implying complete coverage.

**Blocked by:** 01: Configurable sandbox root for the full-app bridge; 06: Tracer bullet — one seed to one generated scenario; 11: The bridge's combat block carries the full parity contract; 12: Ordered piles and per-card identity on the bridge; 13: Run, inventory and act identity on the bridge.

**Status:** done

- [x] A fixed sample of about a dozen scenarios, spanning characters and Ascensions, drives the shipped game through the same Ancient room and row-1 node each record describes, and compares the full contract field list.
- [x] The comparison is field by field and reports the first differing field path; no state hash is compared at any point.
- [x] The projection layer maps the bridge's phase words onto the simulator's decision kinds and normalises the act-index base, so neither difference is reported as a false mismatch.
- [x] The contract fields covered are stated explicitly, so a field that is not compared cannot be mistaken for one that is.
- [x] The oracle runs on a machine whose shipped-game install and local app-data live on different drives, with the sandbox on the game's own volume.
- [x] The sample states which nested-choice kinds it covers and names any kind it cannot drive, rather than implying complete Ancient-choice coverage.
- [x] The comparison routes through the repository's existing per-path comparison helper instead of a third comparator, and that helper gains a real caller.
- [x] The evidence document separates what has been read from the decompiled build from what has actually been observed at runtime, and records the result of this run.
- [x] Offline tests assert the same contract field list the oracle compares, so the two seams cannot drift apart.

## Comments

**2026-09-17 — implemented, and the gate it makes is red.**

- **The feature is not accepted by this run.** The spec's gate is "the fixed sample passes field by
  field", and this run's sample does not: 14 of 14 drove to their fights and 0 of 14 matched. Everything
  the ticket itself asks for is built, run and recorded below; what the run *measures* is a defect in
  the environment, filed as ticket 16. Ticket 15 is done in the sense its own checklist means — the
  oracle exists, ran, and its result is evidence — and the feature stays unaccepted until 16 lands.
- **What was built.** `sts2_native_sim/parity_projection.py` turns either encoder's observation into one
  declared shape of 50 field paths, names the three things it deliberately does not compare
  (`instance_id`, an intent's implementing class, and either `state_hash`) with their reasons, maps the
  bridge's stage word and granular turn phase onto the simulator's decision kind through
  `decision_vocabulary`, and declares the act-index base once, zero-based, for both encoders — no
  per-side conversion, because converting would absorb the regression the declaration exists to catch.
  `python/parity_run_acceptance.py` is the oracle: fourteen fixed scenarios (IRONCLAD and DEFECT,
  Ascensions 0 and 2, ten runs, every Ancient choice whose pick-up this seam can drive) are recorded
  through `generate_rows`, then driven on a real headless `SlayTheSpire2.exe` — same character,
  Ascension and canonical seed, the recorded Ancient choice by index, the prompt it opens answered by the
  record's own rule, out to the recorded row-1 node — and compared with
  `sts2_native_sim.parity.compare_snapshots`, the per-path helper the architecture review found with no
  caller and which this comparison is now the caller of. `tests/test_parity_projection.py` holds the
  projection to the same list the oracle reports, on a fully populated fixture, holds the oracle's own
  report to it, and pins that neither hash nor instance id can move a comparison.
- **The result: 14 of 14 samples drove to their fights and 0 of 14 matched.** Every sample differs in 15
  to 37 leaf paths, and every one of those sets contains `$.run.rng_counters.Niche` one draw higher on
  the record's side (2/1, 3/2, 4/3 seed by seed) and `$.run.rng_counters.Shuffle` beside it. Because the
  helper keeps every mismatch, the report names the first in its sorted order — the enemy's `hp` in
  eleven of the fourteen, a hand card's `card_type`/`model_id` in the other three — with the count and
  the whole set next to it; the enemy HP and the ordered hand and draw pile are what the one extra draw
  moves. Nothing else in the run block differed, the two floors included, so entering the Ancient room
  really does repair the bookkeeping this feature was scoped around. The report also names the four
  declared fields no sample exercised (the potion slot and the enchantment members: a turn-1 fight holds
  no potion and enchants no card), so a declared field that was never read cannot be counted as compared.
  Nothing was lost to chance: the shipped side drove a card prompt in eight of the fourteen — seven on
  the first pass (a one-card removal, a two-card removal, and Hefty Tablet's skippable pick-up among
  them) and the re-driven sample, whose record opens a one-card pick-up — while the other six ran
  `event → event → map`; and all fourteen stood on the recorded node, held the recorded relic and
  reported the recorded encounter. One sample lost its game process mid-drive on the first pass and was
  re-driven alone (`--only`), where it reached its fight like the rest.
- **The cause, measured stage by stage rather than inferred.** A run-mode reset already reports `Niche` 1
  and `Shuffle` 9 before the Ancient room is entered, unchanged through the room, and at the fight
  `Niche` 2 and `Shuffle` 20; the shipped run's whole fight costs one `Niche` draw and those same eleven
  `Shuffle` draws from zero. `PersistentNativeCombatEnvironment.Reset` builds a combat unconditionally
  (`:455-466`), so the reset spends one monster-composition draw and one deck shuffle on a fight the run
  never plays, and the first real fight reads both streams one draw ahead. That is a defect in the
  environment, not in the bridge, and it is filed as **ticket 16** rather than repaired here: repairing it
  is a Core change, and every table recorded from a run reset — the generator's `_OBSERVED`/
  `_OBSERVED_CHOICES` state hashes and `act_variant_acceptance`'s counter baseline among them — moves with
  it. This ticket measured and localised; it did not widen into that change.
- **The Act-variant dimension is bounded by the shipped side, and the bound is measured in the same run.**
  Two probes (`SCENAR10A01`, `ANC1ENT01`, both recorded `OVERGROWTH`) were driven to the Ancient and both
  report `UNDERDOCKS`: the shipped game forces act 1's non-default variant until a profile has met it
  (`ActModel.GetRandomList` reads `SaveManager.Progress.DiscoveredActs`) and the bridge's sandbox profile
  is fresh, while the simulator pins that check off (ADR-0001). So the fourteen compared scenarios are the
  seeds that roll `UNDERDOCKS` — the variant a shipped run on this oracle can actually play — and the
  report says so rather than quietly comparing a different Act. A probe that ever stops coming out that
  way fails the run, so the bound cannot close unnoticed.
- **The nested-choice bound is stated, not implied.** `card_choice` is measured as covered — the run's
  own report says `measured: ["card_choice"]`, `declared: ["card_choice"]`, `agrees: true` — and the two
  kinds it does not cover are named with their reasons: `option_choice`, a bundle or relic pick, which
  ticket 14 measured as answered by the shipped autoplay off-bridge and which none of the sample's offers
  even reaches, and `custom_reward_choice`, a reward set, which `SMALL_CAPSULE` opens for two of the
  sample's runs and whose two choices are deliberately not taken. The rest of the choices left out are
  prompt-free ones dropped for breadth, not for reachability, and the run's `nested_choice_kinds` block
  says which is which.
- **Two corrections the review of this work produced, both kept.** The first: the ticket's "per-path
  comparison helper ... which currently has no caller" is `sts2_native_sim.parity.compare_snapshots` —
  the one `docs/architecture-review.md:630` calls dead — and not `differential_replay.first_difference`,
  which its own module's replay path already called; the comparison was moved onto the callerless helper,
  which is also what makes "that helper gains a real caller" true and what removes a packaged module's
  dependency on an unpackaged script. The second: an intent's implementing class is not on the contract's
  field list (`type, damage, repeats`), so it is now named as excluded rather than quietly compared. The
  review also caught two tests that asserted on source text instead of behaviour; they now hold the
  oracle's own report document to the projection's declaration and the helper's own counts. The run was
  repeated after both corrections and came out the same way: 0 of 14 matched, 2 of 2 probes.
- **One bug in the oracle's own drive was found and fixed before the measurement was trusted.** The first
  version took the Ancient room's *first* legal action, which is always `choose_event:0`, so three
  samples all played choice 0 and reported nonsense (a missing relic, a prompt the record did not
  describe). The drive now takes `choose_event:{option_index}` and checks the room offers it.
- **Verification.** `pytest tests -q` is 180 passed and 22 errors, every one of them the documented
  `tmp_path` refusal, and the ten tests this ticket adds are among the 180; `ruff` and `mypy` are clean on
  every Python file this ticket changed (`differential_replay.py` carries one pre-existing blind-`except`
  report under this ruff version, on a line the change did not touch). The run left its report in the
  gitignored `artifacts/parity-run/parity-run.json`, and the two observations and projections of every
  mismatching sample under `artifacts/parity-run/dump/`, because the comparison names paths and a
  maintainer needs the values behind them; the numbers that matter are in the paragraph above and in
  `parity-findings.md`. The oracle needs writes on the game's volume for the bridge's hard links, which
  this session's file policy refuses, so it was run under a one-shot permission escalation — the machine's
  install is on `F:` and its local app data is not, which is the case the ticket asks the oracle to be
  runnable on.
- **The evidence document was rewritten around this run.**
  `.scratch/act1-combat1-scenarios/parity-findings.md` now records the comparison as runtime evidence, the
  reset defect with its stage-by-stage counters, and the Act-variant bound as a measurement; its "Still
  open" list no longer says no field-by-field comparison has run, and its `TotalFloor` entry is closed by
  measurement rather than left as a static conclusion.

**2026-09-17 — the gate is green now.** The defect this run localised was repaired by ticket 16, which
  made a run-mode reset stop building a combat, and the same sample was re-run on the repaired build:
  **14 of 14 samples matched field for field and 2 of 2 probes measured the bound**, so the feature this
  ticket gates is accepted. What the re-run measured, and what moved with the repair, is recorded in
  `parity-findings.md` and in ticket 16's own comment; the sample, the declared contract, the three
  exclusions and the nested-choice bound are all unchanged from the run above.
