# 07: Run a resumable A10 character-card coverage campaign

**What to build:** Let a user start or resume an A10 campaign that draws game-like random run seeds, generates fixed-request first-combat corpora and keeps going until every eligible character card model has appeared in a successful run deck. Lower Ascensions can be run separately for experiments.

Blocked by: 03 — Enumerate chained Ancient choices and NeowsBones; 06 — Report first-combat content coverage.

Status: ready-for-agent

- [ ] New seeds follow the shipped game's random-seed convention, are canonicalized and are accepted only once per campaign; the exact accepted sequence is recorded for replay.
- [ ] The campaign invokes immutable finite-seed corpus requests, records their identities and resumes interrupted work without changing accepted seeds, completed rows or fixed-request bytes.
- [ ] Coverage advances from successful rows only and stops scheduling new seeds at 100% eligible character-card coverage. Completed in-flight batches and their seeds remain visible.
- [ ] Campaign progress identifies game build, character, Ascension, generated seeds and batches, covered and missing card models, scenario and failure counts, and descriptive relic, potion and monster coverage.
- [ ] A build or campaign-configuration mismatch is rejected rather than merged into existing progress; no corpus-owned artifact contains a duration or floating-point value.
- [ ] Tests of the public campaign behavior cover collision handling, interruption and resume, target completion, A10 versus experimental lower Ascension, and exact replay of the accepted seed sequence.
