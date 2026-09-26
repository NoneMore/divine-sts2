# 09: Validate nested first-combat parity

**What to build:** Verify that representative newly enumerated first-combat scenarios can be replayed through the shipped game and have the same combat initial state field by field, and state which nested choice kinds the evidence actually exercised. A full-app run for every row is not required and is not the point; the point is that each newly explored kind has been seen to match the shipped game before the corpus is trusted.

Blocked by: 06 — Enumerate chained and compound Ancient rewards; 07 — Enumerate both NeowsBones reward orders and measure branch cost; 08 — Drive option picks in the shipped-game bridge.

Status: ready-for-agent

- [ ] A bounded shipped-game sample covers each newly explored nested choice kind, representative chained prompts and both relevant NeowsBones orderings across appropriate characters and Ascensions.
- [ ] For each member of the sample, the shipped run takes the recorded character, Ascension, canonical run seed, Ancient choice, ordered nested selections and first row-one node.
- [ ] The established combat initial-state parity fields are compared individually, and a mismatch reports its field path rather than relying on state-hash equality.
- [ ] Choice legality and offering are part of parity: what the run offered and what the recipe selected agree.
- [ ] The existing first-combat parity evidence still passes as a regression gate.
- [ ] The evidence states which nested choice kinds were exercised and which remain unmeasured, so a passing subset is never reported as complete nested-choice parity.
