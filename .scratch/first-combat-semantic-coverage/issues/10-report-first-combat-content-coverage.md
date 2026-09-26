# 10: Report first-combat content coverage

**What to build:** A corpus user gets an auditable coverage report for one character and Ascension whose headline is that character's own card models found in successful first-combat run decks. It names the eligible pool it measured against, the models still missing, the rows by content type, and relic, potion and monster coverage as descriptive counts — and it never presents a row count as an exact count of distinct NoSL scenarios.

Blocked by: 03 — Derive the eligible character card pool from the active build.

Status: ready-for-agent

- [ ] The eligible denominator is the active build's eligible character card pool for that character (03), and the report names the game build it belongs to.
- [ ] A character card model counts once after appearing in any successful scenario's run deck; repeated copies, repeated appearances and failure rows do not increase the numerator.
- [ ] Other-character cards stay present in scenario rows but never enter character card coverage.
- [ ] The report identifies the character, Ascension, eligible and covered model identities, missing models, successful and failed row counts, and relic, potion and monster counts.
- [ ] A10 training reports and lower-Ascension experimental reports are kept separate, every reported quantity is an integer or a string, and no duration or floating-point value appears.
- [ ] Tests over public corpus output cover a single appearance, repeated copies, cross-class rewards, each excluded card kind and failures, and assert the eligibility comes from the build rather than from a constant.
