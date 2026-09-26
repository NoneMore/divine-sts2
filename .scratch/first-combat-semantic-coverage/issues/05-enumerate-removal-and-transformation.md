# 05: Enumerate removal and transformation with an ordinary-copy preference

**What to build:** Removal and transformation prompts enumerate their legal non-skip targets as ordinary branches, and for those two kinds only, a card model that has both ordinary and upgraded or enchanted copies available is explored through its ordinary copies alone. The variant target is a reachable, semantically distinct outcome that this policy deliberately gives up, because it is expected to overlap content the corpus already has; that sacrifice is stated to the user rather than left in the code.

Blocked by: 04 — Enumerate card selections with interchangeable-copy pruning.

Status: ready-for-agent

- [ ] Each eligible non-skip removal and transformation target produces a branch, with the interchangeable-copy rule applied first.
- [ ] When ordinary and variant copies of one model coexist, only ordinary copies are selected for that model, and which copy represents the model is stable across runs.
- [ ] A model that offers only variant copies still offers them; the preference never empties a prompt's legal targets.
- [ ] The policy and the reachable states it omits are stated in user-facing documentation.
- [ ] Failure rows, sibling completion, deterministic order and reproducible bytes behave as for any other card selection.
- [ ] Public tests cover mixed ordinary and variant copies, a variant-only model and a model with both, once for removal and once for transformation.
