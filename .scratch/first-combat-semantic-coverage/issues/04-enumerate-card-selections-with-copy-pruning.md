# 04: Enumerate card selections with interchangeable-copy pruning

**What to build:** Every legal non-skip card selection an Ancient choice opens — adding a card, upgrading a card — produces its own replayable first-combat scenario, with copies that share model, upgrade level, enchantment and native card state collapsed to one deterministic representative before branching. Distinct models and distinct card states stay distinct, so a seed's branch budget is spent on content rather than on choosing between indistinguishable copies.

Blocked by: 01 — Enumerate single-prompt Ancient rewards; 02 — Expose card variant state on selectable cards.

Status: ready-for-agent

- [ ] Each eligible card-select action at a single prompt produces a branch whose actual selected option is recorded and replayable; skip actions produce no branch.
- [ ] Copies sharing model, upgrade level, enchantment and native card state contribute exactly one deterministic representative, and which one is chosen is stable across runs and worker counts.
- [ ] Distinct models, distinct upgrade levels, distinct enchantments and distinct native states each remain a distinct branch.
- [ ] A card the prompt generates is offered as its own selectable option and is not folded into a pile card.
- [ ] A branch failure leaves a failure row and lets sibling choices complete; successful rows keep their full native combat initial state with no post-generation semantic deduplication.
- [ ] The pruning rule is stated where callers read it, and public generation and corpus tests use seeds or fixtures holding duplicate and variant cards while keeping deterministic row order and reproducible bytes.
