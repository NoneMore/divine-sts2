# 05: Validate nested first-combat parity

**What to build:** Verify that representative newly enumerated first-combat scenarios can be replayed through the shipped game and have the same combat initial state field by field. The acceptance evidence names the exact choice kinds it covers.

Blocked by: 03 — Enumerate chained Ancient choices and NeowsBones; 04 — Drive option picks in the shipped-game bridge.

Status: ready-for-agent

- [ ] A bounded shipped-game sample covers each newly explored nested choice kind, representative chained prompts and both relevant `NeowsBones` orderings across appropriate characters and Ascensions.
- [ ] For each sample, the shipped run takes the recorded character, Ascension, canonical seed, Ancient choice, ordered nested selections and first row-one node.
- [ ] The established combat initial-state parity fields are compared individually; a mismatch reports its field path rather than relying on state-hash equality.
- [ ] The existing first-combat parity sample still passes, and the evidence states which nested choice kinds were actually exercised and which remain unmeasured.
