# 02: Enumerate card selections with selection-time pruning

**What to build:** Produce replayable first-combat scenarios for legal non-skip card selections opened by Ancient rewards, including adding, removing, transforming and upgrading cards. Prune equivalent selections before branching so duplicate card instances do not waste a seed's useful variations.

Blocked by: 01 — Enumerate single-prompt Ancient rewards.

Status: ready-for-agent

- [ ] Each eligible card-select action at a single prompt produces a branch with its actual selected option recorded and replayable; skip actions produce none.
- [ ] Copies with the same card model, upgrade level, enchantment and native state contribute one deterministic representative action at a prompt; distinct models or card states remain distinct.
- [ ] For removal and transformation, if ordinary and upgraded or enchanted copies of one card model coexist, only ordinary copies are selected for that model. The policy is explicit in user-facing documentation because it omits some reachable states.
- [ ] A branch failure leaves a failure row and allows sibling choices to complete; successful rows retain their full native combat initial state without post-generation semantic deduplication.
- [ ] Public scenario generation and corpus behavior, including deterministic row order and fixed-request bytes, are covered by tests using seeds or fixtures that exercise duplicate and variant cards.
