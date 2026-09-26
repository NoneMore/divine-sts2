# 07: Enumerate compound-reward orderings and measure branch fan-out

**What to build:** A compound reward keeps its legal order. When one Ancient choice grants several rewards as a single set — `NeowsBones` grants two relics — each legal order of taking them is its own branch, so one ordered effect is not silently collapsed with the other. How much a seed's branch count grows is measured and reported per element, so keeping full enumeration or restricting it stays an evidence-based decision instead of a guess.

Blocked by: 06 — Recurse through nested prompts to the first combat.

Status: ready-for-agent

- [ ] At a reward set opened by a retained branch, each legal order of taking its rewards yields its own branch, including both `NeowsBones` orderings at the progression-complete baseline.
- [ ] A reward that opens a further prompt inside the set is enumerated under the same recursion and pruning rules as any other prompt.
- [ ] No generic order restriction or per-seed branch cap is introduced, and no `NeowsBones` ordering is dropped without measured justification recorded beside the decision.
- [ ] The branch fan-out a seed produces is reported as counts — elements, branches, rows by content type, deepest nesting reached — in integers, with no duration or floating-point value.
- [ ] Fixed seeds that pair an addition effect with a removal or transformation effect produce their expected ordered branch sets, and a repeated run reproduces the same set byte for byte.
