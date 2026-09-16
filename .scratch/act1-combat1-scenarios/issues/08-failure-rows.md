# 08: Failure rows

**What to build:** A seed that cannot produce a scenario is recorded as its own row rather than dropped or retried into silence, so the corpus cannot develop a silent bias and a caller can count what failed. The row names the stage that failed, an error kind and a message, and carries the recipe resolved so far — at least the character, Ascension and canonical seed, plus the Act variant and the Ancient choice once they are known. A failure row never carries a partial combat initial state.

**Blocked by:** 07: Batch request — expansion, canonicalisation, collision rejection, choice enumeration.

**Status:** done

- [x] An element that fails during generation produces a failure row with its own row-type discriminator, the stage that failed, an error kind and a message.
- [x] A failure row carries the recipe resolved so far and no partial combat initial state.
- [x] A failure is never retried silently, and the rest of the request still completes.
- [x] The summary reports how many rows succeeded and how many failed, so a biased corpus is visible.
- [x] The same element fails again with the same error kind on a re-run.
- [x] A forced failure is asserted through the public request-to-rows interface.

## Comments

**2026-09-16 — implemented.**

- **A failure is a row, and the row is built from a recipe that fills itself in.** `_Recipe` is one
  element's recipe as far as its drive got: the phase it is in, the Act variant the run reports, the
  choices the run offers, and the choice this element is for. `_drive_to_first_fight` stamps it phase
  by phase and hands its failure back through `_Stopped` rather than raising it, so
  `_rows_for_element` can see how far the drive got before deciding how many rows the element still
  owes. That is what makes a failure row's `stage`, `recipe` and `error` a record of what happened
  rather than a reconstruction of what was meant to.
- **A failure row is `record_type: "failure"`**: the same envelope as a scenario row — `schema`,
  `record_type`, `game_build` and `recipe` — then `stage`, then `error: {kind, message}`. Never
  `combat_initial_state` and never `state_hash`: there is no state to carry and no hash of one, and
  the key is absent rather than null. The recipe holds only what the element resolved — the
  character, the Ascension, the canonical seed (with `raw_seed` beside it when the caller's form
  differed), the Act variant the run reports, and the Ancient choice the element is for once the run
  has offered one — and nothing of the fight.
- **An error kind is an identity, not a text.** `error_kind` names `run` for a staged generation
  failure (the `stage` says where it stopped), the worker's own `NativeSimError.code` —
  `worker_crashed`, `protocol_desync` — for a worker failure, and the error's class name in
  snake_case otherwise. A message can name a path or a count that moves between builds; a kind
  cannot, which is what makes "the same element fails again with the same kind" a checkable claim.
  `NativeSimError` gained `message` beside `code` so a row can carry the two separately instead of
  repeating the code inside the text.
- **Nothing is retried, and nothing ends the batch.** Each drive's failure is recorded and the batch
  moves on. A first drive that stops *after* the offer was read still gives every offered choice its
  own row, because those elements are known; only a first drive that stops *before* the offer is
  known owes a single failure row, since how many choices the run offers is exactly what that failure
  prevented learning.
- **The summary is `summarize_rows(rows)`**: counts by row type, every declared type present even at
  zero, plus `succeeded`, `failed` and `total`, so a corpus that lost elements says so instead of
  looking complete. `divine-sts2 scenario` prints the two counts on stderr after writing the rows and
  still exits 0 — a failure row is a row, and the durable statement of a corpus's completeness is
  ticket 09's summary file, which extends this summary with the request, the build, the worker count
  and the shards.
- **Tests.** `tests/test_scenarios.py` is 44 tests (31 before). The fake worker can now die on a
  given action id and on a given 1-based reset ordinal, so a failure is forced at one step *or on one
  drive* of a batch. New: the failure-row envelope and recipe; no combat state and no hash; the
  declared-only recipe when the run never started; the raw-seed diagnostic on a failure; the worker's
  own code as the kind with its details not leaking into the row; one failure row for a first drive
  that stopped before the offer, and one row per choice for a first drive that stopped after it; a
  later drive that stops early naming the choice it is for while the choices after it are recorded; a
  failure in the middle of a request with the rest still driven, asserted by the attempt count; the
  summary counts with and without failures, and the summary refusing a row type it does not know; the
  same element failing identically on a re-run, row for row, with the same kind; and the CLI writing
  failure rows with the counts on stderr. `python -m pytest -q` gives **83 passed, 22 errors**, where
  all 22 are the documented `tmp_path` sandbox refusal (70 passed / 22 errors before this change);
  `ruff` and `mypy` are clean on everything this change adds.
- **Observed** with the shipped game (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`) through
  `python/scenario_record_acceptance.py --workers 3`: the same six samples × three offered choices =
  18 rows ticket 07 recorded, every one replaying from its own fields to its own state hash, with no
  failure row and the same state hashes as before this change. The oracle's rows are therefore
  unchanged by the refactor, and the script now fails closed by name — stage, kind and message — if a
  batch ever records a failure instead.

**2026-09-16 — two-axis review, and what it changed.**

Standards and spec were reviewed in parallel against this working tree. What the review changed:

- **The offer had to survive the failure.** `_rows_for_element` returned one failure row for *any*
  first-drive failure, so a seed whose first drive stopped at `leave_ancient`, `row_one_node` or
  `first_combat` — all of them after `_offered_choices` had already resolved the offer — lost its
  remaining choices with nothing but a count of one to show for it. That is exactly the silent bias
  this ticket forbids, and the module's own new docstring claimed the opposite. `_Recipe.offered` is
  now stamped when the offer is read, `_drive_safely` returns the failure instead of raising it, and
  the loop enumerates every choice the offer named. The new test pins one row per offered choice and
  one attempt each.
- **One envelope, built once.** `_row` and `_failure_row` repeated `schema`, `record_type`,
  `game_build` and a freshly resolved recipe; `_envelope` now builds that part for both, so the two
  row types cannot drift about the fields a reader uses to tell them apart.
- **The docstrings now say what the code does.** The pre-filled Ancient choice on a later drive is
  the element's identity — the run offered it — not a claim that that drive took it, and the docs
  previously promised a recipe that "stops where the run stopped" while the code pre-seeded a choice.
  The distinction is now stated and tested: the recipe says what the element resolved, `stage` says
  how far the drive got, and neither claims a field of a fight that was never reached.
- **The scenario row kept its own provenance.** `_row` reads the Act variant from the fight's own
  observation again, as ticket 07 had it, rather than from the recipe's stamp — a change this ticket
  had no reason to make. `game_build` comes from the worker for both row types: a failure row has no
  observation to read it from, and the acceptance oracle already compares rows against
  `worker.build`.
- **The acceptance script's contract was amended, not broken.** `_assert_no_failures` runs before
  `--snapshot`'s branch, which contradicted that flag's "instead of asserting" line; the docstring now
  says a failure row is refused in both modes, because there are no facts to record for a fight that
  does not exist. It also names the failure through `.get`, so a future third row type fails with the
  message rather than a `KeyError`.
- **CONTEXT.md gained `Failure row`**, and its `Generated scenario` entry now describes one of the two
  row types a batch emits rather than all of them.

What the review raised and this change deliberately did not do:

- **`_Recipe` keeps its name.** It holds `build` and `stage`, which are not recipe fields — its
  docstring now says why they ride along — but the suggested alternative loses the ticket's own
  language, "the recipe resolved so far".
- **Catching `Exception` stays.** A `KeyError` from a shape the environment did not deliver becomes a
  failure row with kind `key_error` rather than an exception out of a batch: visible and countable,
  which is the point of the ticket. Both sites carry `# noqa: BLE001` with the reason, and the `noqa`
  is load-bearing under this checkout's ruff 0.16.4, which does select BLE001.
- **`summarize_rows` keeps `rows` and `total` beside `succeeded`/`failed`,** and stays a plain dict.
  The dict is the shape of ticket 09's `summary.json`, and the per-type counts are the "record counts
  by row type" that summary is specified to report.
- **The fake worker keeps two crash knobs** — `crash_on` by action id, `crash_on_resets` by reset
  ordinal — rather than one map with a reserved reset key: the two name different things, and a
  mini-language inside a test double is worse than a second parameter.
