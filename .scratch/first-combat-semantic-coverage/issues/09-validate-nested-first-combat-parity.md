# 09: Validate nested first-combat parity field by field

**What to build:** Representative newly enumerated first-combat scenarios are replayed through the shipped game and compared field by field with the recorded combat initial state. The acceptance evidence names exactly which nested choice kinds and which reward orderings it exercised, so a passing subset is never reported as complete nested-choice parity.

Blocked by: 06 — Recurse through nested prompts to the first combat; 07 — Enumerate compound-reward orderings and measure branch fan-out; 08 — Drive option picks and card copy identity in the shipped-game bridge.

Status: ready-for-agent

- [ ] A bounded shipped-game sample covers each newly explored nested choice kind, representative chained prompts, and both relevant `NeowsBones` orderings, across characters and Ascensions as appropriate.
- [ ] For each sample the shipped run takes the recorded character, Ascension, canonical seed, Ancient choice, ordered nested selections and first row-one node.
- [ ] The established combat-initial-state fields are compared individually, and a mismatch reports its field path rather than relying on state-hash equality.
- [ ] Choice legality and offering are part of the comparison: an option the simulator recorded as offered is offered by the game, and no skip action appears as a retained branch.
- [ ] The existing first-combat parity sample still passes, and the evidence states which nested choice kinds were actually exercised and which remain unmeasured.
- [ ] A full-app run for every corpus row is not required, and the evidence says so rather than implying whole-corpus validation.
