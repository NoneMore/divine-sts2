# 01: Enumerate single-prompt Ancient rewards

**What to build:** For one character, Ascension and run seed, produce a replayable first-combat scenario for every legal non-skip option of an offered Ancient reward that opens one reward or option prompt. Other prompt kinds can retain their current deterministic resolution until later tickets. The added rows remain ordinary fixed-request corpus rows.

Blocked by: None (can start immediately).

Status: done

- [x] Every offered non-skip Ancient choice and every legal non-skip option at a single reward or option prompt produces a recorded branch; skip choices produce none.
- [x] Each success row records the offered Ancient choice, selected option index and identity, node and complete pre-action combat initial state; its recipe materializes the same state.
- [x] A failed option produces its own failure row with the resolved recipe and does not suppress sibling options.
- [x] Branch, row and shard order are deterministic; a fixed request, build and worker count produces byte-identical artifacts, and worker count changes do not change the row set.
- [x] Existing first-combat scenarios that need no nested reward option remain reachable and reproducible.

## Comments

Implemented on `feat/first-combat-generator`.

**What changed.** `_scenario_driver` drives each offered Ancient choice once to find the prompt its
pick-up opens. When that is a *single* reward or option prompt — the drive met exactly one prompt and
its kind is `custom_reward_choice` or `option_choice` — every non-skip option of it is driven as its
own branch from the state the Ancient offer was left in, in the order the prompt offered them, and the
drive that found the prompt is reused as its own option's row rather than driven twice. The reading is
the ticket's own: a choice that opens a reward prompt *and then another* — `LOST_COFFER` and
`NEOWS_BONES` in this build — is a chain, not "one prompt", so it keeps the one row its own drive
produced and ticket 03 owns its recursion. A choice whose drive met no prompt, or met a card select,
keeps that row too, so the card-selection cardinality stays with ticket 02. A skip is never a branch:
a `skip*` kind, an option pick that selects nothing (the empty selection a minimum-zero prompt emits
first), and a proceed option on the Ancient's own offer all produce none.

**Record.** `nested_choices` gained an optional `selected_reward` identity — the reward's indices, kind
and model, in a declared key order of its own — recorded wherever a pick took a reward and checked
again on `materialize_scenario`, so a replay refuses a reward the prompt no longer offers at the
recorded index. A reward set's actions keep their true `reward_index` after a sibling is taken
(`LOST_COFFER` on `ANCIENT06` records the second pick at `selected_index` 0 and `reward_index` 1),
which is what the identity is for. Failure rows now carry the nested choices resolved so far, so one
failed option is not the same row as its sibling's failure.

**Evidence.**

- `tests/test_scenarios.py`: fourteen new tests at the public `generate_rows`, `generate_corpus` and
  `materialize_scenario` seams — reward and skippable-option branches, recorded identities, the
  card-select and chained-prompt boundaries, a prompt with no option to take, a proceed option on the
  offer, per-option failure rows (including one that fails before it is taken), and a branched
  corpus's byte identity and worker-count-independent rows. Full offline suite: 294 passed; `ruff` and
  `mypy` clean on the changed modules.
- `tests/acceptance/scenario_record_acceptance.py`, re-recorded with `--snapshot` and then run in
  asserting mode against the shipped game (also with `--corpus`): `GYMSCENAR10`'s `SCROLL_BOXES` now
  records two branches, one per offered bundle, with distinct fight hashes, and every other sample
  keeps its row count, its nested kinds and its state hashes — including the corpus byte-identity and
  resume checks. Its per-row enumeration check is now group-aware, and its observed table pins one
  entry per row. No sample reaches a single-prompt *reward* set — this build's reward-set relics offer
  one reward or chain — so the reward-branch path is exercised by the double, and the reward identity
  is exercised on the chained rows of `ANCIENT03` and `ANCIENT06`; shipped-game reward-prompt parity is
  ticket 05's sample.
- `tests/acceptance/parity_run_acceptance.py` keeps a choice's rows as a list and fails loudly when a
  sample names a choice that owns several branches, since such a sample declares no option; the nested
  branches belong to ticket 05's sample. Its own sample takes no branched choice, so the records it
  compares are unchanged.

**Not verified here.** The full-app parity gate itself was attempted (`--limit 2 --process-mode fresh`)
and could not compare a fight: this host's existing full-app sandbox is refused at hello
(`Progression-complete baseline failed: Existing full-app sandbox progress does not match ...`) before
any game process reaches the Ancient room. That is a sandbox-tree condition of this machine, not a
generator difference — the compared records are the ones the native acceptance re-validated above with
unchanged hashes — and ticket 05 owns shipped-game validation of the new branches.
