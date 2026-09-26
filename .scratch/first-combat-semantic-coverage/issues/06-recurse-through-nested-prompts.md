# 06: Recurse through nested prompts to the first combat

**What to build:** A retained branch is followed through every prompt it opens, however deep, until the Ancient event completes — a bundle whose cards open nothing, a reward set whose reward opens a card select, a card select whose result opens another reward set. Each prompt on the way applies the same skip policy and the same selection-time pruning, and every branch that reaches the first combat keeps the ordered recipe that materializes it and that a person can replay in the shipped game. A branch that fails at any depth leaves one failure row naming how far it got, and its siblings continue.

Blocked by: 04 — Branch the generator at one reward or option prompt; 05 — Enumerate card selections with selection-time pruning.

Status: ready-for-agent

- [ ] Nested options are enumerated recursively until the Ancient event completes, with the skip policy and selection-time pruning applied at every prompt on the way.
- [ ] Every retained success row carries its complete ordered nested selections with option identities at each step, so it materializes into the same state and can be replayed by hand in the shipped game.
- [ ] A failure after some selections yields one failure row with the recipe resolved so far, and branches that were not yet explored are still explored.
- [ ] No generic per-seed row cap, step cap or depth truncation silently drops a reachable branch; the traversal's termination condition is the Ancient event completing.
- [ ] Compound fixed-seed examples produce their expected legal branch sets, and corpus resume, deterministic bytes and a worker-independent row set still hold for elements that now produce many rows.
- [ ] Descriptions of the superseded cardinality — one row per offered Ancient choice, and nested choices resolved by a fixed default rule — are updated to match the new public behaviour.
