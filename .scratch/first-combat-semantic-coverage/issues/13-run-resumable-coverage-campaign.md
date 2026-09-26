# 13: Run a resumable coverage campaign

**What to build:** A user can start or resume an A10 campaign that turns its accepted seeds into immutable finite-seed generation requests and writes one corpus per request, recording enough progress that an interrupted campaign continues without changing an accepted seed, a completed row or a fixed request's bytes. Lower Ascensions can be run the same way as separate experiments.

Blocked by: 09 — Validate nested first-combat parity; 11 — Report first-combat content coverage; 12 — Draw a game-like run seed stream.

Status: ready-for-agent

- [ ] The campaign consumes only seeds it has accepted and invokes immutable finite-seed generation requests, recording each request's identity beside the corpus it produced.
- [ ] Progress is persisted as the campaign advances, and a resumed campaign continues the pending work without changing accepted seeds, completed rows or a fixed request's bytes.
- [ ] Progress names the game build, character, Ascension, accepted seeds and batches, covered and missing card models, scenario and failure counts, and descriptive relic, potion and monster coverage.
- [ ] A conflicting request in an existing artifact root, or a build or configuration mismatch, is refused rather than merged or overwritten, as a single corpus already refuses one.
- [ ] No campaign-owned artifact contains a wall-clock duration or a floating-point value.
- [ ] Public tests cover interruption and resume, request identity, a build mismatch, A10 against an experimental lower Ascension, and exact replay of the accepted seed sequence.
