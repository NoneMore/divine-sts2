# 07: Enumerate both NeowsBones reward orders and measure branch cost

**What to build:** NeowsBones' two legal reward orders both stay enumerated as separate branches, and the measurement needed to decide whether that remains affordable is produced alongside them. Fully unlocked NeowsBones can pair an addition effect with a removal or transformation effect, so its two orders can expand a seed sharply; the project keeps both orders until branch frequency or cost is measured, and that measurement is this ticket's second deliverable.

Blocked by: 06 — Enumerate chained and compound Ancient rewards.

Status: ready-for-agent

- [ ] Both legal NeowsBones reward orders appear as separate replayable branches with their own ordered recipes; neither is collapsed into the other.
- [ ] The measured branch frequency and the per-element cost of fully enumerated NeowsBones are recorded beside the existing element throughput figures, on a stated fixed request.
- [ ] The measurement is stated with the decision it supports: keep full enumeration, or open a separate explicit change that trades named reachable scenarios for cost. A restriction is not taken inside this ticket.
- [ ] No order restriction and no per-seed branch cap is introduced anywhere without such a measurement.
- [ ] Public tests cover both orderings on a fixed seed and assert that the two rows differ in the order recorded and in the state they reach.
- [ ] Corpus determinism, resume and the worker-count-independent row set still hold for the enlarged branch set.
