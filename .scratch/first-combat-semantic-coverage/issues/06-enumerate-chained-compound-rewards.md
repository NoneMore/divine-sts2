# 06: Enumerate chained and compound Ancient rewards

**What to build:** Every retained legal non-skip branch is followed through all of its nested prompts to the first combat, including a reward prompt opened by another reward and a card-select prompt opened from inside one, so a scenario generation element yields as many first-combat scenarios as its choices actually entail. No fixed number of rows per seed is imposed, and a compound reward keeps the legal order the run presents it in.

This is where the prompts stop being one level deep: the traversal becomes a recursion that applies the card-select, removal and transformation policies at every prompt it meets, records the whole ordered path for replay, and bounds itself only by a stated ceiling rather than by silently truncating.

Blocked by: 01 — Enumerate single-prompt Ancient rewards; 03 — Record the chosen reward's identity at each reward step; 04 — Enumerate card selections with interchangeable-copy pruning; 05 — Enumerate removal and transformation with an ordinary-copy preference.

Status: ready-for-agent

- [ ] Nested options are enumerated recursively until the Ancient event completes, applying the card-selection, removal and transformation and skip policies at every prompt.
- [ ] A compound reward keeps its legal order, and no generic per-seed row cap or unmeasured order restriction is introduced.
- [ ] Every retained success row carries the ordered nested recipe needed for materialization and human replay, including each step's prompt kind and option identity.
- [ ] A failure after some selections yields one failure row with the recipe resolved so far, while the other branches complete.
- [ ] The nested-step ceiling and the path for a prompt that reports no legal action are stated and tested rather than truncating a branch silently.
- [ ] Any debug-only probe that mirrors the generator's default resolution follows the same prompt-kind vocabulary, so the two cannot drift apart.
- [ ] Compound fixed-seed examples produce the expected legal branch set, and deterministic bytes, corpus resume and a worker-count-independent row set still hold for elements that produce many rows.
- [ ] Existing descriptions of how many rows a seed produces are updated to the new public behaviour.
