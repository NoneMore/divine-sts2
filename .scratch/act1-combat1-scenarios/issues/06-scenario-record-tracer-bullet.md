# 06: Tracer bullet — one seed to one generated scenario

**What to build:** The existing console entry point gains a subcommand that, for one character, Ascension and run seed, drives the simulator through the act-1 Ancient room, takes the first Ancient choice that seed offers, resolves any nested choice by a fixed documented rule, travels to the first node of row 1, and writes one generated scenario. The record is a portable recipe before it is a snapshot: game build; the character, Ascension, canonical run seed and the raw seed when it differed; the Act variant; the ordered Ancient options that were offered; the Ancient choice taken; each nested choice resolved; the node's coordinate and point type; the encounter id; and then the combat initial state, the RNG counters and the state hash. The batch logic lives inside the Python package and the subcommand is a thin wrapper over it, so the behaviour is importable and testable rather than being another sibling script.

**Blocked by:** 02: Derive the act-1 Act variant from the run seed; 03: Offer and enter the act-1 Ancient room at run start; 04: Drive an Ancient choice and any nested choice to completion; 05: The combat observation names its encounter, act and floor.

**Status:** done

- [x] The console entry point runs the request and writes one record, and the function behind it takes a request and returns rows, so the behaviour is exercised without a shell.
- [x] The record carries every recipe field listed above, and the offered Ancient options keep the order the run offered them in.
- [x] The record carries the full combat initial state: the enemies with their generated HP, each ordered pile including the hand and the draw pile, the relics, the potions, the player's HP and gold, and the named RNG counters.
- [x] The row carries a versioned schema tag and a row-type discriminator.
- [x] The recorded run seed is the canonical form the shipped game derives, so pasting it into the shipped game's custom run screen reproduces the record.
- [x] The row-1 node is chosen by the documented fixed rule rather than left to the caller, and the coordinate and point type it picked are recorded.
- [x] The nested-choice rule that resolves a choice's second prompt is fixed and documented, and the choice it made is recorded so it can later be replaced.
- [x] The same request run twice produces the same record.
- [x] The record is a recipe, not a state snapshot: it stores no simulator state handle and no portable branch.

## Comments

**2026-09-17 — implemented.**

- **The behaviour is a package module, the subcommand is a wrapper.** `sts2_native_sim/scenarios.py`
  holds `ScenarioRequest`, `canonicalize_seed` and `generate_rows(request, worker) -> rows`; the
  existing console entry point gained a `scenario` subcommand
  (`divine-sts2 scenario --character IRONCLAD --ascension 0 --seed ANCIENT01 [--output PATH]`) that
  builds the request, runs it against one `NativeWorker` and writes the rows as JSONL — stdout by
  default. Nothing was added to `python/` as a sibling script except the acceptance script below,
  which is the repository's `*_acceptance.py` convention.
- **The row.** `schema` is `sts2-native-sim/scenario-record/1` and `record_type` is `scenario`;
  `game_build` is the shipped build the run was played on; `recipe` holds the character, Ascension,
  canonical seed (plus `raw_seed` exactly when the caller's form differed), Act variant, the offered
  Ancient options in offer order with their index and relic, the choice taken, every nested choice
  resolved, the node's coordinate and point type, and the encounter id; `combat_initial_state` is the
  fight's **canonical observation verbatim**; `state_hash` is the simulator's hash of that state.
  The ticket's "the RNG counters" are `combat_initial_state.run.rng_counters`, and the run's gold
  and floor position are beside them in `run` — the observation's own blocks are not duplicated at
  the top level, because a second copy of a fact is a second thing to keep true.
- **`combat_initial_state` is an observation, and that is deliberate.** Storing the capture as the
  environment emits it means the row's fight validates against the published
  `schemas/canonical-state.schema.json` (which ticket 07 wants to assert) and ticket 15's parity
  projection is a rename rather than a re-assembly. The row envelope around it is *not* an
  observation — it has no `decision`/`terminal`/`victory` and the schema forbids extra properties —
  so ticket 07's "every emitted row validates against the published observation schema" should be
  read as validating `row["combat_initial_state"]`, not the envelope. Worth knowing before 07 lands
  its check.
- **The three fixed rules, and where each is written down.** The Ancient choice is the first one the
  run offered; a nested prompt is answered with the first legal action the environment reports, one
  rule for every nested kind; the row-1 node is the first legal map action in the order the
  environment reports them. All three live in `scenarios.py`'s module docstring, not only in code.
  A nested choice is recorded as `{kind, selected_index, selected_option_ids}`. A reward pick is
  expressed by the environment as a reward *index* rather than option ids, so such a choice records
  an empty `selected_option_ids` and its `selected_index` is the identity of what it picked — that is
  a gap in the recorded data, stated rather than hidden, and the acceptance replays by index.
- **Canonicalisation is a real transform with a surprising reach.** `SeedHelper.CanonicalizeSeed` is
  upper-case, `O` → `0`, `I` → `1`, then trim — so **every `ANCIENT*` and `ACTVARIANT*` seed this
  repository's acceptance scripts use is non-canonical**, and `ANCIENT01` is the run of `ANC1ENT01`.
  The generator therefore starts the simulator with the canonical string (nothing else would make the
  record reproducible) and keeps the caller's string as a diagnostic. Before this change the
  simulator hashed whatever it was handed, so the canonical form is also what the Act-variant roll
  and every RNG stream must be derived from; ticket 07's collision rejection depends on that.
- **New Python shared with ticket 04's module.** `ancient.py` gained a `RunStepWorker` protocol —
  the driving loop never needed a native worker's resets or branch handles — and
  `drive_choice`/`leave_ancient` are typed against it, so `generate_rows` can be handed any
  run-stepping double; that is a typing change only. It also gained `map_actions` (the legal map
  actions in the order the environment reports them, which is the contract the row-1 rule reads and
  which `ancient_action` now reads too) and `LEAVE_EVENT_ACTION`, so the action id is spelled once.
  The generator steps `leave_event` itself rather than calling `leave_ancient`, deliberately:
  `leave_ancient` applies its own *prompt-free* choice rule, which is a reachability rule for
  callers that want the map and not the record's rule, so using it would record a different choice.
- **Observed** with the shipped game (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`) through the Godot-hosted
  native worker, by the new `python/scenario_record_acceptance.py --workers 3`. Six samples — both
  Act variants, `IRONCLAD` and `DEFECT`, Ascension 0 and 2, three already-canonical seeds and three
  the transform rewrites — passed, and the script's recorded table pins what each produced. Per
  sample it checks the canonical seed and the raw-seed diagnostic, the Act variant against an
  independent port of the shipped roll, the offered relic ids **in offer order** against an
  independent port of `Neow.GenerateInitialOptions`, that the choice taken is the first offered one,
  that the node is on row 1 and typed `Monster`, that the fight is at floor 2 and validates against
  the published schema, the enemies' HP, the ordered piles, the relics, the potion slots and the
  player's own row, and that a second worker produces the identical row.
- **Observed, and the claim the ticket is really about.** For every sample the script re-drives a
  fresh run **from the recorded fields alone** — canonical seed, Ancient choice *index*, each nested
  choice's *index*, node *coordinate* — and asserts it reaches the row's own state hash. Nothing in
  that replay comes from the generator, so the row carries enough to reproduce the situation and
  nothing a fresh run cannot reproduce. Example: `IRONCLAD@A0/ANCIENT01` reaches
  `92807FCE02322DEB374757D3089819469491647BD61436CEBB6338D7D02935B4` with `BOOMING_CONCH` taken and
  `TWIG_SLIME_S` 9 / `TWIG_SLIME_M` 27 / `LEAF_SLIME_S` 12 in the fight, and the console entry point
  run by hand on the same seed wrote the same hash.
- **Observed, nested-choice coverage on the sample:** `card_choice` (`PRECISE_SCISSORS` on
  `TRACERBULLET`, `NEW_LEAF` at Ascension 2 on `ANCIENT03`) and `custom_reward_choice` twice over on
  `ANCIENT06` (`LOST_COFFER`, where the first reward set's own reward opens a second). Three of the
  six samples offered a prompt-free first choice and recorded no nested choice at all. `option_choice`
  (the bundle pick) is the one nested kind this sample does not meet, so the fixed rule is unobserved
  there; the acceptance asserts the covered set equals the recorded one, so a change in coverage is a
  failure rather than a silent narrowing.
- **A caveat on "pastes back into the custom run screen".** `NCustomRunScreen.OnSeedInputSubmitted`
  passes the typed text to `SetSeed` and the run start canonicalises it, with no length or alphabet
  validation in between (`SeedHelper.seedDefaultLength = 10` is only what random generation uses),
  so pasting the recorded canonical seed reproduces the run. That is read from the decompiled build;
  what is *observed* here is the simulator-side half — the canonical string is what the run was
  started from and what the recipe replay uses. The shipped-client comparison is ticket 15's.
- **Tests.** `tests/test_scenarios.py` (18 tests) runs the whole generator against a fake run worker
  built from the recorded captures in `tests/fixtures/canonical-observations.json`, and routes every
  step by action id so taking an action the run never offered is a failure rather than a silent
  success — which is what makes "the fixed rule picked *this* node" observable. It asserts the
  envelope, the character and seed diagnostics, offer order, the nested rules (card select, bundle
  pick and reward set), the full combat initial state, the published-schema check, determinism, that
  no key of the row is a state handle or a portable branch, and the staged failures. The console
  test is also the envelope round-trip: the row is written as JSONL through the entry point and read
  back equal to what the generator returned. `python -m pytest -q` gives **57 passed, 22 errors**,
  where all 22 are the documented `tmp_path` sandbox refusal in
  `test_dev_environment.py`/`test_sandbox*.py` (39 passed / 22 errors before this change), and
  `ruff check` and `mypy` are clean on everything this change adds — the package keeps its 16
  pre-existing mypy findings and `cli.py`'s three pre-existing ruff findings.

**2026-09-17 — two-axis review, and what it changed.**

Standards and spec were reviewed in parallel against this working tree (a first pair of reviewers
stalled without reporting and was replaced by a bounded pair). What the review changed:

- **The stage label that misreported where the run stopped.** Leaving the Ancient room and getting
  something other than the map raised `ancient_room`; it now raises `leave_ancient`, so ticket 08's
  `stage` names the failure rather than the previous stage.
- **A silently empty nested selection is now a failure.** `selected_option_ids` was read with
  `.get("option_ids")` and defaulted to `[]`, which records "chose nothing" for a prompt that
  probably just reported its selection differently. An action that selects options and names none is
  now a staged error; only a reward pick (which the environment expresses as a reward index) may
  record an empty list.
- **Three deduplications.** The character canonicalisation is one `ScenarioRequest.character_model_id`
  property instead of `request.character.upper()` at two sites; the legal map actions are one
  `ancient.map_actions` used by both `ancient_action` and the row-1 rule instead of two loops with
  the same shape; and the `{option_index, relic_model_id}` pair is one `_choice_identity` used for
  both the offered options and the choice taken. `leave_event`'s action id moved to
  `ancient.LEAVE_EVENT_ACTION`.
- **Names.** `_Walk`/`_walk` became `_DrivenRun`/`_drive_to_first_fight`, and the stage constants
  carry a comment saying each names where the run stopped rather than where the generator meant to go.
- **Two more tests.** A bundle pick (`option_choice`) records the option ids it selected — the one
  nested kind the real sample does not meet — and a prompt that names no selection fails instead of
  recording an empty one.

What the review raised and this change deliberately did not do:

- **The `scenario` subcommand does not enforce `cli.SUPPORTED_BUILD`.** `doctor` does, and every
  acceptance script pins its own recorded build, but a *generator* must be able to produce a corpus
  for a game build the repository has not blessed yet — that is what the row's `game_build` is for,
  and refusing to run would make a new build unreachable instead of merely unverified. Pinning is the
  oracle's job, not the generator's.
- **Hoisting `from .client import NativeWorker` out of `doctor()` is safe.** `client` imports only the
  standard library and `.paths`, both of which the test suite already imports with no game installed;
  `tests/test_public_smoke.py` imports `cli` and CI runs it on a machine without the game, which is
  the proof. The local import was not load-bearing.
- **`generate_rows` returning rows rather than one row is the ticket's own wording**, not ticket 07's
  machinery: "the function behind it takes a request and returns rows". The JSONL writer follows the
  corpus convention ticket 09 builds on. `_reset_state` keeps taking the canonical seed beside the
  request on purpose — that is what makes starting a run with the caller's raw seed impossible.
- **`ScenarioGenerationError` and the stage labels stay.** Ticket 08 owns the failure *row* and the
  retry policy, but the only code that knows which stage a run died in is the code driving it, so the
  vocabulary is defined where it is observed; 08 consumes it instead of re-deriving it from a bare
  exception. `generate_rows` raising is this ticket's contract; 08 replaces the raise with a row.
- **`_row` keeps reading the environment's DTOs directly** (`observation["run"]["act_variant"]`,
  `node["parameters"]["col"]`). The record builder's whole job is to read those shapes; accessors for
  each path would be middle-men with no second caller.


