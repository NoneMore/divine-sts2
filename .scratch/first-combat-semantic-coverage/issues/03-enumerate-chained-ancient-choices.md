# 03: Enumerate chained Ancient choices and NeowsBones

**What to build:** Follow every retained legal non-skip Ancient branch through all nested prompts to the first combat, including reward prompts opened by other rewards and both legal `NeowsBones` reward orders. A seed may produce as many rows as these choices entail.

Blocked by: 01 — Enumerate single-prompt Ancient rewards; 02 — Enumerate card selections with selection-time pruning.

Status: ready-for-agent

- [ ] Nested options are enumerated recursively until the Ancient event completes, while applying the card-selection pruning and skip policy at each prompt.
- [ ] Both legal `NeowsBones` reward orders remain separate; no generic per-seed row cap or unmeasured order restriction is introduced.
- [ ] Every retained success row has the ordered nested recipe needed for materialization and human replay, including option identities at each step.
- [ ] A failure after some selections yields one failure row with the recipe resolved so far, while other branches continue.
- [ ] Compound fixed-seed examples produce the expected legal branch set, and corpus resume, deterministic bytes and worker-independent row set still hold for multirow elements.
- [ ] Existing default nested-choice cardinality descriptions are updated to match the new public behavior.
