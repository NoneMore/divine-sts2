# 11: Report first-combat content coverage

**What to build:** One character and Ascension get an auditable coverage report led by that character's own card models found in the run decks of successful first-combat scenarios, with relic, potion and monster coverage beside them as descriptive counts, and no claim that a row count is an exact count of distinct NoSL scenarios.

Blocked by: 10 — Derive the eligible character card pool from the active build.

Status: ready-for-agent

- [ ] The run deck of a successful scenario is read from its recorded combat initial state; a card model counts once at its first appearance, and further copies, further appearances and failure rows add nothing.
- [ ] Other-character cards stay present in scenario rows and stay out of the character-card statistic, as do Ancient and multiplayer-only models.
- [ ] The report names the character, Ascension, game build, eligible and covered card identities, missing cards, successful and failed row counts, and relic, potion and monster counts.
- [ ] A10 training reports and lower-Ascension experimental reports are produced and read separately.
- [ ] The report holds deterministic integers and strings only, and the corpus summary carries its coverage block in declared key order so a fixed request still reproduces its bytes.
- [ ] Public corpus-output tests cover a first appearance, repeated copies, a cross-class reward, an excluded model and a failure row.
