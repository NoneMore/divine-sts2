# 10: Byte-identical output

**What to build:** For a fixed request, game build and worker count, running the batch twice produces byte-identical output, so a corpus can be regenerated and diffed and any mismatch means a real change rather than clock drift. Keys are written in a declared order, encoding and separators are pinned, and every contract quantity is an integer or a string so no float formatting can drift. Compressed shards are byte-identical too, which means the gzip metadata the repository's existing corpus writers let the clock stamp — the embedded name and the timestamp — is pinned. Changing the worker count changes shard boundaries, so the byte guarantee is scoped to a fixed worker count; across worker counts the invariant is the row set.

**Blocked by:** 09: Sharded corpus output and summary.

**Status:** done

- [x] The same request, game build and worker count run twice produce byte-identical shard files, including their compressed bytes.
- [x] The same request run with a different worker count produces the same rows in the same relative order, with different shard boundaries.
- [x] No contract quantity is serialised as a floating-point number.
- [x] Key order is declared rather than inherited from a dictionary's iteration order, and encoding and separators are pinned.
- [x] Record order and shard assignment are a property of the request alone, so completion timing cannot influence the output.
- [x] A test asserts byte-identity through the generator's public request-to-rows interface and is collected by CI.

## Comments

**2026-09-16 — implemented.**

- **The gzip metadata is pinned, and the defect it repairs was measured before it was repaired.** A shard
  is now written as a `gzip.GzipFile` with `filename=""` and `mtime=0` (`_shard_writer`) instead of
  through `gzip.open`, which stamps the clock and the file's own name into the member header. Ticket 09
  left two corpora of one request on this host — `artifacts/scenario-corpus-acceptance` (3 workers) and
  `-acceptance-4` (4 workers) — and their shared `worker-00.jsonl.gz`, the same element written 25
  seconds apart, differed in exactly the four header bytes at offset 4 (`21a5aa6a` vs `3aa5aa6a`, the
  modification time). Those two corpora also read back as the same nine rows in the same order, which is
  the cross-worker-count invariant this ticket scopes byte-identity against, measured rather than
  assumed.
- **A third defect fell out of the same measurement: the line ending was the host's.** The old writer
  wrote through a text-mode handle, and `io.TextIOWrapper` translates `\n` to `os.linesep`, so every row
  of a Windows-written corpus carried a `\r` that no reader sees, because readers decode with universal
  newlines. The same three rows decompressed: 15584 bytes with three `\r` in the old shard, 15581 with
  none in the new one, and the rows equal once the `\r` is stripped. `encode_row` now encodes each line
  itself under `ROW_ENCODING` and the writer writes those bytes, so a row's line ending is the record's
  and not the platform's.
- **Key order is declared, and every one of the record's own documents is projected onto the declaration
  as it is written.** `ROW_KEY_ORDER` and its siblings — the recipe, a choice's identity, a nested
  choice, the node, the error, the summary, a shard entry, the request — are the record format;
  `encode_row` orders a row by them, and `RowFormatError` refuses a key no declaration names, so a field
  a record gained without its order being extended is a loud failure rather than a byte that moved in a
  diff. A test reverses every one of those dictionaries and asserts the same bytes, and pins the written
  order literally, failure rows included. `_write_summary` writes the same declared document it returns,
  so the file and the reported manifest are one document.
- **The two values the *worker* owns are written as the capture reported them, and the boundary is
  asserted rather than implied.** The combat observation and the game build are the capture's documents:
  their shape is the published canonical-state schema's, which is not a serialisation order, and their
  order is fixed by the same game build that fixes their values, which is the scope the byte guarantee
  names. A test asserts that the observation's key order *is* the capture's, so this is a decision a
  reader can find and argue with rather than an omission. Ordering them here would mean this module
  re-declaring a schema it does not own — and the schema's free-form maps (`rng_counters`,
  `native_state`, `legal_action.parameters`) have no declared order to take.
- **No quantity is a float, and the check is the record's own.** `_refuse_floats` walks the row where it
  is built, and a fractional quantity becomes that element's failure row — stage `record`, kind `run`,
  the path named — instead of a corpus that drifts. The schema cannot catch one: the published schema
  declares no `number` at all, and jsonschema accepts `1.0` for `{"type": "integer"}` (measured, 4.26.0).
  Refusing at the row rather than at the file keeps a capture the record cannot hold as one element's
  row instead of a dead batch, and the failure row carries no partial state, as ticket 08 requires.
- **Encoding and separators are pinned once.** `ROW_ENCODING`, `ROW_SEPARATORS`, `ROW_ESCAPE_NON_ASCII`
  and the summary's own separators are declared and used by the writer and by `read_corpus`; escaping
  non-ASCII also keeps a failure row's message the same bytes whatever language the tool that raised it
  speaks. `sort_keys` stays off: sorting is a declaration too, but the wrong one — it would write a
  record alphabetically instead of in the order a reader reads it.
- **Worker count and completion timing.** Four elements at 1, 2, 3 and 4 workers read back as the same
  rows with boundaries `[[0,1,2,3]]`, `[[0,1],[2,3]]`, `[[0,1],[2],[3]]`, `[[0],[1],[2],[3]]`. A corpus
  written with the first shard slow and one written with the second slow are byte-identical, so
  completion timing reaches neither a row's position nor a byte.
- **Tests.** `tests/test_scenarios.py` is 70 tests (61 before). New: a corpus written twice with the
  clock moved from 1e6 to 2e6 is byte-identical, shards and summary both; a shard's gzip header carries
  no FNAME and a zero timestamp; a shard's uncompressed payload is exactly the serialised rows with no
  `\r`; one request at four worker counts; a corpus byte-identical under the other completion order; no
  row serialises a float; a float in a capture is a failure row; the declared key order plus the
  reversed-dictionary equality; and the same request serialised through `generate_rows` + `encode_row` is
  the same bytes. The five that pin the repaired behaviour were run against `HEAD`'s `scenarios.py` from
  a copy on `PYTHONPATH` and each fails there — the byte-identical corpus, the shard's uncompressed
  bytes and line ending, the gzip metadata, the declared key order, and the float in a capture — while
  the other four assert properties that already held (the timing comparison, four worker counts, the
  no-floats walk, the row format) and so are guards rather than evidence. `python -m pytest -q` gives
  **109 passed, 22 errors** (100/22 before this change), where all 22 are the documented `tmp_path`
  refusal, measured as one `PermissionError: [WinError 5]` per test on a `%TEMP%` directory. `ruff` is
  clean on the files this change touches and `mypy` is clean on everything it adds;
  `tests/test_scenarios.py` carries one pre-existing mypy error
  (`lambda **_: started.append(1) or FakeRunWorker()`, present at `HEAD`), left alone.
- **Observed** with the shipped game (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`) through
  `python/scenario_record_acceptance.py --workers 3 --corpus artifacts/scenario-corpus-ticket10`. The
  script's corpus check now writes the same request a second time beside the corpus, compares every
  file's bytes and leaves the copy in place, so byte-identity is checked against the game's own rows
  and not only offline. It passed: `success: true`, six samples, three nested-prompt kinds, 9 scenario
  rows and 0 failures in each of the two roots, and the shards begin `1f8b08000000000000ff` — no
  embedded name, a zero timestamp. The parity run itself is unchanged: the same samples, the same 18
  rows, the same state hashes and the same recorded tables.

What this change deliberately did not do:

- **No schema-driven re-ordering of the combat observation.** It is the capture's document, the schema is
  not a serialisation order, and its free-form maps have none; the boundary is asserted by a test.
- **The summary is written by declaration, but `worker_replacements` is still what happened.** A crash in
  one run and not the other is a real difference in the batch, not clock drift; the guarantee is about
  the same request run the same way.
- **`read_corpus` still reads through `gzip.open`.** The metadata is a writer's problem: a reader that
  decodes a member carrying a name and a timestamp is reading the format rather than depending on the
  writer.

**2026-09-16 — two-axis review, and what it changed.**

Standards and spec were reviewed in parallel against this working tree. What the review changed:

- **The declared-order helpers became one family.** `_declared_row`, `_declared_recipe` and
  `_declared_summary` sat beside `_element_recipe`, which does a different job — the recipe fields one
  declaration resolves — as a near-homonym of the projection. They are `_row_in_declared_order`,
  `_recipe_in_declared_order` and `_summary_in_declared_order` now, so the name says what they do and
  the builder stands on its own.
- **The summary's encoder settings are declared too**, which was the review's best find:
  `_summary_in_declared_order`'s docstring claimed a summary "is written the same way" as a row while
  `_write_summary` still passed `indent=2` and left the separators and escaping to the encoder's
  defaults. `SUMMARY_SEPARATORS` is declared beside `ROW_SEPARATORS` and the escaping is passed
  explicitly, so neither corpus document depends on a default. `CONTEXT.md`'s *Corpus summary* entry
  gained the byte guarantee its shard sibling already had.
- **The row-seam test says what it is.** `test_the_same_request_serialises_to_the_same_bytes_through_the_rows_interface`
  was measured to pass against `HEAD`'s serialiser — two runs of a deterministic generator serialised
  the same way are the same bytes whatever the serialiser does — so its docstring now calls it the row
  *format* pin (one compact UTF-8 line, the declared separators) and names the corpus-level test as the
  discriminator. It stays because the ticket asks for a test at that seam; it is not offered as
  evidence of the fix.
- **The no-floats test reads the bytes rather than the parsed row.** It parses each line with
  `parse_float` set to a refusal, so a float *token* is what fails it, which is what its docstring
  claimed; the `_floats` path-walking helper went with it. It still passes against `HEAD`, where the
  fixture holds no float — it is a guard, and the discriminating test is the capture with a float in it
  becoming a failure row.
- **The acceptance check keeps its evidence.** The second corpus was written into `<root>-repeat` and
  deleted in a `finally`, so a mismatch destroyed the thing it was reporting on. It is written beside
  the corpus and left there now, and only a stale copy is removed first, because a resumed root would
  be compared with itself instead of written again. `del started[:]` became `started.clear()`.

What the review raised and this change deliberately did not do:

- **The declared order does not cover the combat observation or the game build, and that stands.** Both
  reviewers named it; it is the one narrowing of "keys are written in a declared order", and it is
  recorded here and in `encode_row`'s docstring. Re-ordering them would mean this module re-declaring
  the published schema, which is not a serialisation order, whose free-form maps (`rng_counters`,
  `native_state`, `legal_action.parameters`) have no order to take, and whose two documents' order is
  fixed by the game build the corpus records the hash of and the byte guarantee is scoped to. A test
  asserts the observation's order is the capture's, so the boundary cannot drift silently.
- **A float stays an element's failure row while an undeclared key stops the batch.** The asymmetry is
  now stated on `RowFormatError`: no capture can make a row carry an undeclared key — only this module
  can, and that is a bug — while a capture can report a quantity the format cannot hold, which is data,
  and "an element that could not produce a scenario" is ticket 08's own vocabulary for it.
- **`_corpus_bytes` in the acceptance script and `_corpus_files` in the tests stay two functions.** A
  test cannot import an acceptance script, and these are the two places a corpus's bytes are compared.
- **The four `if "<key>" in recipe` blocks in `_recipe_in_declared_order` stay blocks.** A
  `{key: (order, is_list)}` table would hide the list/scalar distinction behind a boolean.
