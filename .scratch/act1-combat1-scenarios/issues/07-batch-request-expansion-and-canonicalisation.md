# 07: Batch request — expansion, canonicalisation, collision rejection, choice enumeration

**What to build:** A request is a Cartesian product of characters, Ascensions and run seeds, and it expands to a deterministically ordered element list — character, then Ascension, then seed, then Ancient choice index — so a caller enumerates in one command instead of scripting the loop. A caller who passes a seed in a form the game does not store still gets a usable corpus: the request is canonicalised exactly as the shipped game canonicalises a seed when a run begins, and the raw string is preserved on the record as a diagnostic, so a seed read off a screenshot works. If two requested seeds collapse to the same canonical seed the whole request fails with an input error naming both, because silent deduplication would change the size and the balance of a corpus without telling anyone. Every Ancient choice the run seed actually offers becomes its own record, so coverage over openings is complete rather than sampled.

**Blocked by:** 06: Tracer bullet — one seed to one generated scenario.

**Status:** done

- [x] A request expressed as character, Ascension and seed sets produces one record per element, in the declared order.
- [x] A record's identity is its character, Ascension, canonical run seed, Act variant, Ancient choice index, nested choices and node coordinate; two records for the same character, Ascension and seed differ only in the Ancient choice.
- [x] A non-canonical requested seed yields records whose recorded seed is the canonical form, with the raw string present as a diagnostic field.
- [x] A request of a single already-canonical seed records no raw-seed diagnostic.
- [x] Two requested seeds that canonicalise to the same value fail the whole request with an input error naming both, and no output is written.
- [x] The number of records a seed produces equals the number of Ancient choices its run actually offers; no Ancient choice is invented and none is skipped.
- [x] Every emitted row validates against the published observation schema.
- [x] Expansion, canonicalisation and collision rejection are asserted through this public request-to-rows interface, not by calling internal helpers.

## Comments

**2026-09-16 — implemented.**

- **The request is three declared sets and one discovered dimension.** `ScenarioRequest(characters,
  ascensions, seeds)` keeps each set in the caller's declared order (a list declaration is
  normalised to a tuple), and `generate_rows` expands character → Ascension → seed → Ancient choice
  index, one row per element. The Ancient choice dimension is not declared: it is what the seed's
  run offers, so `_rows_for_seed` drives the run once per choice — the first drive both records
  choice 0 and says how many choices there are, and each remaining choice is taken by driving the
  run again from its start. A row is therefore the record of the drive that made *its* choice, not
  a projection of the first drive's state, which is also how ticket 06's acceptance replays it.
- **Collision rejection is one rule, not three.** `ScenarioRequestError(ValueError)` is raised
  before any run is driven when two declarations resolve alike: two seeds that canonicalise the
  same (the ticket's case, naming both raw forms *and* the canonical value), one character in two
  cases, or one Ascension twice — plus a dimension that declares nothing at all. The spec's
  argument for seeds is the argument for the other three: each would put rows sharing one identity,
  or no rows at all, into a corpus while looking like it had worked. `divine-sts2 scenario` catches
  the error, prints it on stderr and exits 2 without calling the writer.
- **The subcommand's flags became repeatable** (`--character`, `--ascension`, `--seed`, all
  `action="append"`, Ascension defaulting to 0) so one command enumerates the product; a single
  occurrence each is the old invocation verbatim.
- **Tests.** `tests/test_scenarios.py` is 29 tests (18 before). New: element order for a 2×2×2
  request, list declarations reading back as tuples, the row count equalling the offered-choice
  count for 1, 2 and 3 offered choices, two records of one seed differing only in the Ancient
  choice, batch canonicalisation with the raw diagnostic on exactly the rewritten seeds, both
  collision shapes rejecting without driving anything, a dimension declared empty, every row's
  `combat_initial_state` validating against the published schema, the CLI writing every row, and
  the CLI refusing a colliding request with exit 2, empty stdout and `_write_rows` never called.
  The fake worker now routes *every* offered choice and derives its state hash from the observation
  — a hash is a function of the state — so "the recorded hash is the fight's own" survives
  enumeration. `python -m pytest -q` gives **68 passed, 22 errors**, where all 22 are the
  documented `tmp_path` sandbox refusal (57 passed / 22 errors before this change); `ruff` and
  `mypy` are clean on everything this change adds.
- **Observed** with the shipped game (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`) through
  `python/scenario_record_acceptance.py --workers 3`: six samples × three offered choices = 18 rows.
  Every row re-drives a fresh run **from its own recorded fields** — canonical seed, Ancient choice
  *index*, each nested choice's *index*, node *coordinate* — and reaches its own recorded state
  hash, so the batch is reproducible element by element and not merely in aggregate. Each sample's
  three rows share the character, Ascension, seed, Act variant and node and differ only in the
  Ancient choice, and the choice indices are exactly the offered options in offer order. The
  choice-0 rows are unchanged from ticket 06's recorded table, which is why that table still passes
  untouched. Enumeration also reached two nested paths ticket 06 could not: `option_choice`
  (`SCROLL_BOXES` on `GYMSCENAR10`, choice 1) and a three-prompt chain
  (`custom_reward_choice` → `card_choice` → `custom_reward_choice` for `NEOWS_BONES` on
  `ANCIENT03`, choice 2). All 18 rows' choice, nested kinds, node and state hash are recorded in the
  script's `_OBSERVED_CHOICES`, so the enumeration claim is a pinned observation rather than a
  sentence.
- **The acceptance script's coverage check changed shape.** Comparing the sample's nested-prompt
  kinds for equality was right while a sample met one choice; with every choice recorded it can only
  widen, so the per-choice table is now the pin (`_assert_observed_choices`) and `_assert_coverage`
  is gone. The recorded widening is visible in that table rather than swallowed by a loose floor.

What this change deliberately did not do:

- **No failure rows, no shards, no pinned serialiser.** Tickets 08, 09 and 10 own those.
  `generate_rows` still drives every element on one worker, serially.
- **No branch restore between choices.** Taking choice *k* on a restored branch would save a run
  drive per choice, but the record's whole claim is that a *fresh* run reproduces it; `restore` is
  also not part of the `RunStepWorker` protocol the driving loop is typed against. Enumeration
  therefore costs one extra drive per additional choice, which ticket 09's worker pool is the right
  place to pay for.
- **The CLI still starts a worker before the request is validated**, so a colliding request is
  reported only after a worker exists. A lazily started worker would report it on a host without the
  game, and is a deliberate deferral: ticket 09 rebuilds the worker layer around a pool, and the
  input error already precedes any run, any row and any write.

**2026-09-16 — two-axis review, and what it changed.**

Standards and spec were reviewed in parallel against this working tree. What the review changed:

- **The (character, Ascension, seed) triple travelled as loose parameters** through the expansion,
  the drive, the reset request and the row builder, with the caller's seed sitting next to the
  canonical one in transposable positions. `_Element` now carries the four values an element needs —
  `character_model_id`, `ascension`, `declared_seed`, `seed` — and is built once per element by
  `_Element.declared(...)`, so canonicalisation happens once and no call site can swap the two seed
  forms.
- **The row count was anchored to the wrong list.** `_rows_for_seed` took the dimension's length from
  the event's `options` while indexing the legal `choose_event` actions, and nothing checked that the
  two agreed — an option no action could take would have been skipped silently, which is exactly the
  "none is skipped" claim the ticket makes. `_offered_choices` now matches the two views by option
  index and fails the stage when they disagree in either direction (a reported option no action can
  take, or a legal choice the event does not report), and two new tests drive one direction each.
  That is what makes the offline count a checked claim rather than the generator grading itself.
- **The identity test was vacuous.** "Two records differ only in the Ancient choice" passed only
  because the double routed every choice to the same nested chain. The double now opens the nested
  prompts for one choice only, and the test asserts the honest property: the rows share character,
  Ascension, seed, Act variant, the offer, the node and the encounter, and differ in the choice — the
  nested choices a choice resolved being that row's own record. The recorded real-game table says the
  same thing (`PRECARIOUS_SHEARS` opens a `card_choice`, its two neighbours open none), so the
  ticket's sentence is the loose form of "the choice is the dimension the rows differ by".
- **Smaller ones.** The three "declares nothing" guards are now one loop; the test helper's `**kwargs`
  plumbing became an explicit `worker` parameter; `_facts`'s unused `sample` parameter is gone;
  `_assert_enumeration` no longer overclaims in its docstring and now also pins the shared offer.

What the review raised and this change deliberately did not do:

- **`_reject_collapsed` stays generic, identity call site and all.** The three dimensions genuinely
  phrase their collisions differently — a seed canonicalises, a character resolves, an Ascension is
  simply listed twice — and the identity lambda is the price of one checked rule rather than three
  near-copies.
- **The two recorded tables keep their four shared fields.** `_OBSERVED[label]` is ticket 06's
  observation, kept verbatim so it stays comparable to the evidence that ticket was accepted on; the
  per-choice table is this ticket's. `--snapshot` prints `first_choice` beside `choices` for the same
  reason: the first row at a glance.
- **"Sample" stays in the acceptance script.** CONTEXT.md avoids the word for a *generated scenario*;
  in that script it names an acceptance sample — the `Sample` dataclass ticket 06 introduced — and the
  new prose means the same thing by it.
- **The ticket's identity sentence is left as written**, with the honest property recorded here and
  asserted in the tests: nested choices are part of a record's identity *because* they are what its
  choice resolved, not a second dimension of the request.

