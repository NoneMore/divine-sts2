# 09: Sharded corpus output and summary

**What to build:** A batch writes a corpus rather than a single file: one compressed shard per worker under an artifact root, plus a summary file, following the convention the repository already uses for corpora so existing readers can consume it. Work is assigned to shards by the element's index in the expanded request, not by which worker finished first, so a slow worker changes when a row appears but never where it lands. One failed seed does not destroy the batch, and a large batch is resumable.

**Blocked by:** 07: Batch request — expansion, canonicalisation, collision rejection, choice enumeration.

**Status:** done

- [x] A batch run with N workers writes N shards under an artifact root plus a summary file naming them.
- [x] Shard assignment and row order within a shard are fixed by the expanded request, not by completion timing; deliberately delaying one worker moves no row to another shard and changes no row's position.
- [x] The summary reports the request, the game build, the worker count, the record counts by row type and the shards written.
- [x] A seed that fails leaves the other shards intact and the batch continues to completion.
- [x] A batch can be resumed without redoing completed shards and without changing the records already written.
- [x] The written corpus is readable back by the repository's existing corpus readers.
- [x] Worker crashes are replaced rather than failing the batch, and the replacement is visible in the summary.

## Comments

**2026-09-16 — implemented.**

- **The corpus is a file layout, not a new format.** `generate_corpus(request, workers, output_dir)`
  writes one gzip-compressed JSONL shard per worker — `worker-NN.jsonl.gz`, the name
  `python/native_rollout_farm.py` already writes and `python/compile_native_rollouts.py` already
  collects — plus `summary.json` beside them, and a shard holds the rows `generate_rows` already
  produces: `encode_row` is the one serialiser, so a shard is a corpus reader's records and nothing
  else. `read_corpus(path)` reads a corpus (or one shard) back through the same convention, so no
  caller needs a second implementation of the walk.
- **A shard is a contiguous block of the expanded request.** Element *i* belongs to the shard that
  owns the block *i* falls in (`_shards`: blocks within one element of each other, the earlier
  shards longer), so which shard a row lands in and its position inside it are functions of the
  request and the worker count alone — never of which worker finished first. Because the blocks are
  contiguous, reading the shards in name order is the request in element order for *any* worker
  count, which is the invariant ticket 10 scopes byte-identity to. Names are padded to the widest
  index of the batch (`worker-000` from 101 shards up), because name order is how every reader
  collects a corpus and `worker-100` otherwise sorts before `worker-11`.
- **The Ancient choice index cannot index a shard.** Ticket 07 made the choice dimension the one the
  *run* supplies rather than the request: how many choices a seed offers is discovered by driving it,
  so a shard's block is a block of (character, Ascension, seed) elements and all of one seed's choice
  rows travel together. A batch with more workers than elements therefore leaves the shards after the
  last element empty — they are still written, so the worker count still names the corpus, and the
  summary says `elements: []`, `total: 0` for them. The spec's ordering sentence ("character, then
  Ascension, then seed, then Ancient choice index") is the row order within a seed, which the corpus
  has.
- **The summary is the corpus's manifest, and it is written after every shard.** `summary.json` holds
  the schema tag, the request in resolved form, the game build, the worker count, the gzip level, the
  element count, the row counts by type in `summarize_rows`'s shape, and one entry per shard — index,
  file, the elements it owns, its own counts, its replacements and whether it is complete. It is
  rewritten in a single `os.replace` every time a shard lands, so a batch that was killed still says
  what it wrote and the next run resumes it: a shard the summary records complete *and* whose file
  exists is neither driven again nor rewritten (`_resume`). A shard that landed after the last
  summary write is redone, which costs one shard and cannot change the corpus, because the generator
  is deterministic. Rows go to a temporary beside the shard's name and are moved into place once the
  shard is whole, so a shard file is always a whole shard and an interrupted batch leaves the shards
  that landed readable.
- **A refusal, not a merge.** Resuming into another request, another worker count, another gzip level
  or another game build is a `CorpusConflictError` (a `ScenarioRequestError`) raised before any run is
  driven and before any shard is written; a `summary.json` this module did not write — the rollout
  farm writes one — is refused rather than adopted or overwritten. Ticket 10 scopes byte-identity to
  "a fixed request, game build and worker count", and a corpus of two of any of those is not one
  corpus.
- **A worker that dies, or that never comes up, is replaced.** `NativeWorker` gained `alive()`; after
  each element a shard asks whether its worker is still there, closes it and starts another, counting
  the replacement for the summary. The element the dead worker failed is already a failure row, so
  nothing is retried and nothing is lost. A worker that cannot start is given one second attempt for
  the same reason — a process that will not come up is a worker, not a corpus — and a second failure
  stops the batch with the worker's own error.
- **`divine-sts2 scenario` is the shard writer now.** `--workers`, `--output-dir` (required) and
  `--compression` replace `--output`: the spec's flag shape is "worker count, character list,
  Ascension, output directory, compression", and JSONL on stdout was ticket 07's stopgap, as its own
  comment says. The subcommand passes no worker factory, so the batch builds its workers lazily, one
  per shard it still has to write — which closes ticket 07's deferred item: a colliding or
  unresumable request is now reported with exit 2 on a host with no game installed, instead of after
  a worker had been started for a batch that cannot run.
- **Tests.** `tests/test_scenarios.py` is 61 tests (44 before). New: N workers writing N shards plus a
  summary naming them (request, build, worker count, per-type counts, per-shard elements and counts);
  a deliberately delayed worker moving no row to another shard and no row's position; a failing seed
  leaving the other shard intact and the batch complete; a batch stopped mid-flight resuming without
  redoing the recorded shard or changing its bytes; a fully recorded batch re-run starting no worker
  and reporting the same summary; a crashed worker replaced with the replacement in the summary and
  the element after it still recorded; a worker that will not start replaced, and one that will not
  start twice stopping the batch; more workers than elements still writing one shard per worker; 101
  shards staying in shard order by name; the repository's own `compile_native_rollouts.shard_paths`
  collecting the shards; another request, another worker count, another compression level and a
  foreign `summary.json` each refused before a worker starts; and the CLI writing a corpus, reporting
  `1 shard under <dir>: 6 scenario rows, 0 failure rows`, and refusing a colliding request with exit 2
  and nothing written. `python -m pytest -q` gives **100 passed, 22 errors**, all 22 the documented
  `tmp_path` sandbox refusal (83 passed / 22 errors before this change); `ruff` and `mypy` are clean
  on everything this change adds.
- **Observed** with the shipped game (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`) through
  `python/scenario_record_acceptance.py --workers 3 --corpus artifacts/scenario-corpus-acceptance`,
  which now also runs the corpus: the sample's three IRONCLAD@A0 seeds are written as a 3-shard
  corpus, the shards read back as exactly the rows the same run compared field by field with the
  game, the request is recorded resolved (`ANCIENT01` → `ANC1ENT01`), `compile_native_rollouts`'s own
  collector finds exactly those three files, and a second call resumes the corpus without starting a
  worker, rewriting a shard or changing the summary. Repeated at `--workers 4` into
  `artifacts/scenario-corpus-acceptance-4`: four shards, the fourth owning no element — it starts no
  worker and is still written (49 bytes, an empty gzip member) — with the summary's `rows` still
  `{scenario: 9, failure: 0}`. The parity run itself is unchanged: same six samples, same 18 rows,
  same state hashes, and the recorded tables still pass untouched.

What this change deliberately did not do:

- **No pinned gzip metadata, so no byte-identity guarantee.** Ticket 10 owns that. The shards go
  through `gzip.open`, which stamps the current time and embeds the temporary's name, so two runs of
  one request are equal row for row but not byte for byte. The writer is two small functions —
  `encode_row` for a row and `_Corpus.write` for a file — which is exactly where that ticket's
  pinning goes.
- **No choice-level sharding.** A seed's rows are one block. Splitting them would need the offer
  discovered before the shards are planned, i.e. one extra drive per seed whose row is then thrown
  away, and the split would only matter when the worker count exceeds the element count. Deferred
  until a corpus that cares exists.
- **No retry of a failed element.** A failure is a row; only the *worker* is replaced.
- **Nothing was added to `scripts/`.** Enumeration, sharding, resumption and output live in
  `sts2_native_sim.scenarios`; the CLI is the wrapper, and the acceptance script is the oracle.

**2026-09-16 — two-axis review, and what it changed.**

Standards and spec were reviewed in parallel against this working tree. What the review changed:

- **The acceptance check assumed one worker per shard.** `_assert_corpus` required
  `started == range(workers)`, which is false as soon as a shard owns no element: at `--workers 4`
  over three seeds the fourth shard starts nothing and the documented `--corpus` check aborted. It now
  expects a worker for each shard that owns an element, which is what the offline test
  `test_a_batch_with_more_workers_than_elements_still_writes_one_shard_per_worker` already asserted —
  the two surfaces had disagreed.
- **The shard names broke their own ordering claim.** `worker-{index:02d}` puts `worker-100` before
  `worker-11` in the name order every reader collects a corpus in, so past 100 shards the corpus no
  longer read back as the request. The padding is now the width of the batch's widest index, and
  `test_shard_names_stay_in_shard_order_past_the_second_digit` drives 101 shards through the seam.
- **The gzip level was not part of the resume identity.** A resumed root could hold shards at two
  levels with a summary reporting only the current one, because `compression` was written fresh each
  call. `_resume` now refuses a different level, like a different worker count.
- **A worker that never came up failed the batch.** Only a death noticed after an element was
  replaced, and a `NativeWorker` that could not be constructed propagated out of the shard task. A
  worker that cannot start is now given one second attempt, counted as a replacement, and a second
  failure is the only thing that stops the batch.
- **The corpus fixture wrote into the repository tree.** Every corpus now goes to the host's temporary
  area instead.
- **Smaller ones.** The counting helpers were `_count`/`_tally`/`_empty_counts`/`_counts_of`, and
  `_counts_of` was handed a counts mapping under a parameter named `rows`; they are `_counts`,
  `_tally`, `_empty_counts` and `_recorded_counts`. `_Corpus` took seven positional arguments
  including both the request and its elements; it now takes the elements and derives its own shards.
  `_write_shard(corpus, ...)` reached into the corpus's data for its root, elements, compression and
  recording, and became `_Corpus.write`. The CLI restated the default worker factory; it passes none,
  which is also what makes the lazy-worker claim true. `read_corpus` replaced the two hand-written
  readers (the test's and the acceptance script's), which removes the duplicated docstring with it.
  `NativeWorker.alive()` moved beside `memory_bytes`/`close`, where the other process questions are.
  `CONTEXT.md` gained **Corpus shard** and **Corpus summary**.

What the review raised and this change deliberately did not do:

- **`_native_worker` ignores its shard index, and `read_corpus`/`encode_row` are public with one
  internal caller each.** The index is what a factory *may* use, and the acceptance script counts
  shards by it; the reader and the row encoding are halves of the corpus contract that a caller and
  ticket 10 need, not shared helpers that happen to be public.
- **The summary stays a `dict[str, Any]`, re-parsed on read.** It is a JSON document in the shape the
  readers parse; a type for it would be a second schema to keep in step with the file.
- **`--output` is gone rather than kept beside `--output-dir`.** Ticket 07 recorded it as a stopgap,
  the spec's flag list has no stdout mode, and a corpus is a directory with a manifest.
- **The unresumable-root refusals stay** (foreign `summary.json`, game build, worker count, gzip
  level). Each of them protects the same claim — one root holds one corpus — and each is raised
  before a worker is built, so a caller learns immediately rather than after a wasted batch.
