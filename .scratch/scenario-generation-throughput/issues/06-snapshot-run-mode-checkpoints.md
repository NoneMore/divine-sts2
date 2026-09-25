# 06: Snapshot run-mode checkpoints so a restore stops rebuilding the run

**What to build:** The change ticket `04` named but deliberately did not implement. Restoring the
checkpoint taken when a run entered the Ancient room costs a measured **163 ms per call (median;
205 ms mean)** on reference request A, of which **95.3%** is rebuilding the run's act — `RunManager.Reset`
+ `GenerateRooms` + `GenerateMap` inside `InitializeRunMap` — and **3.7%** is the single replayed
action. The resident-prefix fast path never fires for these restores (0 of 8, three rounds running),
because a rewind is never a hit. A **combat**-mode checkpoint already avoids exactly this work: it
carries a `CombatSnapshot`, and `RestoreAsync` applies it instead of calling `ReconstructAsync` and
replaying. A **run**-mode checkpoint carries no snapshot (`CaptureCombatSnapshot` returns null for
every run-mode recipe), so the same run that was resident in the process one step earlier is thrown
away and derived again — three times per element, for one run's one act.

**What to do:** give a run-mode branch the snapshot its combat-mode sibling has, capture it where the
checkpoint is taken, and have `RestoreAsync` apply it to the live run instead of reconstructing and
replaying. The shipped game already carries a restore path for this class of state — its own save/load
route (`SerializableRun` / `SetUpSavedSingleplayer`, and `SerializableActMap` through
`SavedMapsToLoad` in `GenerateMap`), which restores a run and its map **without** re-running
`GenerateRooms` — so the cheapest new surface is to build the snapshot on that rather than on another
hand-written field-by-field copy. Sizing, and whether the snapshot capture that a branch pays on every
step is cheaper than the restores it removes, are this ticket's first questions; the answer decides
whether the whole thing is worth landing.

**Why it is worth attempting (the gate this passed):** Q13 condition (ii) — removing `restore` is
worth ≥1.5×. `restore` is 41–43% of generation time (measured per round: 40.9% / 43.0% / 42.1%), so
removing it is 1.7× on generation; the diagnosis's robust lower bound puts it at ≥41% of batch wall
clock.

**Blocked by:** None. The measurement it rests on is `04`, which is done.

**Status:** done

- [x] A branch taken while a run-mode state is current carries what a restore needs to reach that
      state again without `ReconstructAsync`, and `RestoreAsync` uses it when it can.
- [x] The divergence check stays where it is: a snapshot that does not reproduce `ExpectedHash` falls
      back to the replay it does today, so a wrong snapshot is a slower restore rather than a wrong
      record.
- [x] The capture cost a branch pays on every step is measured, and the change is kept only if the
      generation time it removes is larger than the time it adds.
- [x] The native differential passes: `python tests/acceptance/scenario_handle_reuse_acceptance.py`
      — rows and encoded bytes equal to the native fork reference, on a configured game host.
- [x] The byte-identical corpus comparison passes: two runs of one request on one build with one
      worker count write identical shards and summary, shard bytes included.
- [x] The throughput diagnosis at `docs/research/act1-first-combat-scenario-generator-throughput.md`
      records the new `restore` cost measured the same way `04` measured the old one (the probe at
      `python/experiments/scenario_restore_profile.py`, profiled from outside a corpus).

## Comments

Written from ticket `04`'s verdict, which measured the reconstruction and named this as the narrowest
change that would remove it. Ticket `04`'s own comments carry the part-level numbers; the diagnosis's
"待查的那件事：已测" section carries the tables and the reproduction commands.

Implementation and measurement: [the throughput diagnosis](../../../docs/research/act1-first-combat-scenario-generator-throughput.md#工单-06run-mode-checkpoint-快照2026-09-25基线-head-acd1ccf). The snapshot is captured for the first entered Ancient room, which is the run-mode checkpoint this generator restores. Later run-mode branches with unsaved decision state retain reconstruction and replay. The code-review Spec axis called out this narrower scope; it is intentional under this ticket's measured capture-cost gate.

On reference request A, 24 restores over three rounds took 11.38 ms median / 13.65 ms mean in the worker, with no run/map rebuild or replay. Four snapshot captures per round cost 0.455 s median; eight restores fell from 1.720 s to 0.139 s median, saving more than capture adds. Native differential passed (6 elements, 18 rows, 12 restores). `scenario_record_acceptance.py --workers 1 --corpus ...` passed its recorded first-combat hashes and two-run compressed shard and summary byte comparison; `run_checkpoint_snapshot_acceptance.py` confirms the snapshot path and zero replay.
