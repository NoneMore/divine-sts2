# 04: Decide whether the Ancient-choice restore can skip reconstruction

**What to build:** The measured answer to one question, which decides whether the largest single cost in scenario generation is removable. Restoring the checkpoint taken when a run entered the Ancient room costs about **215 ms** per call — 46.9% of generation time on one worker, and at least **41%** of a batch's wall clock. A run-mode branch holds no combat snapshot, so the restore falls through to rebuilding the run and its map and replaying action history; but the same code also contains a resident-prefix fast path that reports its own elapsed time as zero when it hits. This ticket delivers which of the two is happening for the Ancient-entry checkpoint, and therefore whether the reconstruction is avoidable — the fact the throughput gate's "removing it is worth at least 1.5×" condition is waiting on.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] For the restores in the small reference request, it is measured how often the resident-prefix fast path is taken, stated as a count of the eight.
- [ ] The per-restore cost is attributed to named parts of the restore — fast-path hit, run rebuild, map rebuild, history replay — by timing those parts, not by inference from the total.
- [ ] The verdict is stated as exactly one of two outcomes: the reconstruction is avoidable and removing it is worth at least the gate's 1.5×; or it is not avoidable, in which case the gate fails and the optimization is dropped with its reasons recorded in the throughput diagnosis.
- [ ] If it is avoidable, the narrowest change that would make it so is named, together with the acceptance that already gates it — the native differential and the byte-identical corpus comparison — leaving the implementation to a ticket written at that point.
- [ ] Every timing used here is external to a corpus: no duration enters a shard or a summary, per ADR-0008.
