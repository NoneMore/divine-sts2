# 11: Run a resumable A10 character-card coverage campaign

**What to build:** A user can start or resume an A10 campaign that draws game-like random run seeds, generates fixed-request first-combat corpora, and keeps going until every eligible character card model has appeared in a successful run deck. Interrupted work resumes without changing an accepted seed or a completed row, and lower Ascensions can be run separately as experiments.

Blocked by: 02 — Port the shipped random-run-seed convention and record the stream; 06 — Recurse through nested prompts to the first combat; 10 — Report first-combat content coverage. (A campaign expected to cover compound reward ordering also needs 07.)

Status: ready-for-agent

- [ ] New seeds follow the shipped random-seed convention and are canonicalized; the accepted sequence is recorded, and a resumed campaign continues that sequence instead of redrawing it.
- [ ] A drawn seed that canonicalizes onto a seed the campaign already accepted is handled explicitly rather than creating a second element for the same run.
- [ ] The campaign invokes immutable finite-seed corpus requests, records their identities, and resumes interrupted work without changing accepted seeds, completed rows or fixed-request bytes.
- [ ] Coverage advances from successful rows only and stops scheduling new seeds at 100% eligible character card coverage; a batch already in flight may finish, and the seeds it used stay recorded.
- [ ] Campaign progress identifies the game build, character, Ascension, generated seeds and batches, covered and missing card models, scenario and failure counts, and descriptive relic, potion and monster coverage.
- [ ] A build or campaign-configuration mismatch is refused rather than merged into existing progress, and no campaign-owned artifact carries a duration or floating-point value.
- [ ] Tests of the public campaign behaviour cover canonical-seed collisions, interruption and resume, target completion, A10 versus experimental lower Ascension, and exact replay of an accepted seed sequence.
