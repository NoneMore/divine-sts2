# 06: Report first-combat content coverage

**What to build:** Give a corpus user an auditable coverage report for one character and Ascension, led by the character's own card models found in successful first-combat run decks. Show relic, potion and monster coverage as descriptive counts, without treating row count as exact NoSL semantic diversity.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] The eligible card denominator is derived from the active game build's progression-complete, single-player character pool; Ancient and multiplayer-only models are excluded without hard-coded build counts.
- [ ] A character card model counts once after appearing in any successful scenario's run deck; copies, repeat appearances and failure rows do not increase coverage.
- [ ] Other-character cards remain present in scenario rows but do not enter character card coverage statistics.
- [ ] The report identifies character, Ascension, game build, eligible and covered card identities, missing cards, successful and failed row counts, and relic, potion and monster counts.
- [ ] A10 training reports and lower-Ascension experimental reports are kept separate; the report uses deterministic integer or string data and makes no claim of exact global semantic-unique row count.
- [ ] Public corpus-output tests cover a single appearance, repeated copies, cross-class rewards, exclusions, failures and build-derived eligibility.
