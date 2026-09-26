# 14: Stop the campaign at the character-card coverage target

**What to build:** The A10 campaign keeps scheduling seeds until every eligible card model of its character has appeared in the run deck of at least one successful first-combat scenario, then stops scheduling. A batch already in flight may finish, and the seeds it used stay visible in the record rather than being discarded to make the count tidy.

Blocked by: 13 — Run a resumable coverage campaign.

Status: ready-for-agent

- [ ] Coverage advances from successful rows only: a failure row never covers a card.
- [ ] Scheduling stops once the eligible character-card target is reached, and a batch already in flight may complete and remains recorded with its corpus and seeds.
- [ ] A campaign resumed after reaching the target schedules no further seed and does not reinterpret already completed rows.
- [ ] A lower-Ascension experimental campaign is tracked separately and can neither end the A10 training campaign nor contribute to its coverage.
- [ ] Public tests cover reaching the target, stopping with a batch in flight, and resuming a campaign whose target is already met.
- [ ] The campaign's record makes no claim of an exact count of distinct NoSL scenarios; it reports generated rows and measured coverage as separate things.
