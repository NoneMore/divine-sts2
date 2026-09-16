# 05: The combat observation names its encounter, act and floor

**What to build:** A run-mode combat observation becomes self-describing. It names the encounter it is, which act and Act variant it is in, the act floor and the run's total floor — so a parity check has something to compare, an audit can identify a fight, and the floor the Ancient room advances is directly observable instead of inferred from a hash difference. The published canonical-state schema is brought in line with what run-mode captures actually emit, instead of describing only the combat-mode shape. Because the observation's shape changes, the observation schema version and the state-hash schema version both move, and every existing golden hash and determinism assertion is regenerated once — which is cheapest now, while no generated corpus depends on them.

**Blocked by:** 02: Derive the act-1 Act variant from the run seed; 03: Offer and enter the act-1 Ancient room at run start.

**Status:** done

- [x] A run-mode combat observation carries the encounter id, the act index, the Act variant, the act floor and the run's total floor.
- [x] The act index is reported in the same base as the rest of the system, so a comparison cannot read it one-off.
- [x] The new fields are inside the state hash, so a restore that fails to reproduce them is detected as divergence rather than passing silently.
- [x] The observation schema version and the hash schema version are both bumped, and every golden hash and determinism assertion in the repository is regenerated in the same change.
- [x] The published canonical-state schema describes the shape run-mode captures emit, including the run stages that carry no combat block, and a run-mode capture validates against it.
- [x] Validating the observation against the published schema is a real check in the test suite rather than a parse of the schema file.
- [x] The observation that the Python agent seam derives stays consistent with the canonical one, so the two do not drift apart.

## Comments

**2026-09-17 — implemented.**

- **A run-mode combat observation now names its fight and its place in the run.** `combat.encounter`
  is the encounter's own id (`EncounterModel.Id.Entry` — the identity `catalog` lists and the trace
  exporter already reports), and the combat `run` block gained `act_index`, `act_floor` and
  `total_floor` beside `act_variant`. The act index is `RunState.CurrentActIndex` verbatim:
  zero-based, the same base the map observation and `scoring_features` report, so a comparison reads
  it instead of reading it one-off. `CaptureMap` gained `total_floor` too, because it already
  reported `act_index`/`act_floor`; that makes the Ancient room's floor advance directly observable
  at the seam — 0 at run start, 1 at the map after the room, 2 at the row-1 fight — instead of
  inferred from a hash difference, which is the gap that motivated this ticket.
- **All of it is inside the state hash.** `ComputeStateHash` hashes the whole observation plus the
  transition kernel, so a restore that fails to reproduce the encounter or the floors is a
  `replay_divergence`, not a silent pass; nothing had to change for that, which is the point of
  putting the fields on the observation rather than beside it.
- **Both versions moved: observation 2 → 3 (`ProtocolConstants.ObservationSchemaVersion`), hash
  3 → 4 (`hash_schema_version`).** Every determinism assertion in the repository compares two live
  values — a second worker, a restore, or a re-run — and no tracked file pins a literal state hash
  (checked: `git grep -E '[0-9A-Fa-f]{40,}'` over the tracked `.cs`/`.ps1`/`.json`/`.md` finds the
  game version string and the assembly-hash pins, and nothing else), so nothing needed re-recording;
  what the bump required was proving the assertions still hold, and 17 of the 18 run-driving
  acceptance scripts pass, below.
- **The published schema is now the run-mode shape.** `canonical-state.schema.json` is v3:
  `combat` and `inventory` are optional, every stage block a capture can emit is described (`run`,
  `map`, `event`, `rest_site`, `reward`, `room_rewards`, `custom_rewards`, `outstanding_choice`,
  `outstanding_rewards`, `shop`, `treasure`, `decision`), and the `$defs` describe the nested rows
  (creatures, intents, powers, piles, cards, orbs, coordinates, reward and event options). A capture
  that carries a `combat` block must also place the run — an `allOf`/`if`/`then` requires
  `run.act_index`, `act_floor` and `total_floor` of it and of nothing else — and `encounter` is a
  non-empty string, so a fight that cannot name itself fails. Because the C# options drop nulls on
  the wire, a field that can be null is described as absent rather than as `null`, which is why
  `combat.encounter` is required while `next_move` and `enchantment` are not. The standalone blocks
  that no run stage emits (a `reset` battle, an item reward's `reward`, a reward set) are described
  by the same definitions.
- **`jsonschema>=4.18` is now a dependency, and validating is real.**
  `python/sts2_native_sim/schema.py` loads the published file and validates one observation against
  it, reporting the offending JSON path; `tests/test_observation_schema.py` uses it on captures
  recorded from the worker. It is a runtime dependency rather than a dev extra because the module
  that validates is in the package, where the batch generator's row check (the spec's testing
  decisions) will call it. The check has teeth: dropping `combat.encounter`, dropping a fight's act
  position, or adding a block the schema does not describe, is asserted to fail — and a stage with no
  combat block is asserted to stay valid without a position. One test pins the schema's `const` to
  `ProtocolConstants.ObservationSchemaVersion` read out of `Messages.cs`, and `hash_schema_version`
  out of the environment, so neither half of the version bump can be reverted silently.
- **`tests/fixtures/canonical-observations.json`** holds 19 captures recorded from two real runs by
  the new `python/observation_schema_acceptance.py --record`: the act map at run start and the map the
  Ancient room hands back, the room's choice and completion, a run-mode fight, a fight the player
  loses, its room rewards, a rest site, a shop, a treasure room, an act transition, plus the standalone
  combat (orbs, an occupied and an empty potion slot, a relic counter and native state), card reward,
  item reward, custom reward set and card select. ~105 KB, and byte-identical on a second `--record`,
  which is what makes it a fixture rather than a snapshot. The acceptance script validates the same
  captures live before writing them.
- **The Python agent seam reports the new facts instead of dropping them.**
  `extract_agent_observation` passes `act_variant`, `act_index`, `act_floor` and `total_floor`
  through from `run`, and `encounter` through from `combat`, each only when the canonical
  observation carries it. `test_observations.py` asserts that every field of a canonical `run` and
  `combat` block reaches the agent projection — so a new canonical field fails a test until the
  projection reports it *and* the fixture is re-recorded, which is what keeps the two from drifting.
- **Observed** with the shipped game (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`) through the Godot-hosted
  native worker: `python/observation_schema_acceptance.py --record` validated all 19 captures against
  the schema and wrote the fixture. For `ANCIENT01` the first run-mode fight reports
  `encounter: "CORPSE_SLUGS_WEAK"` with `act_index` 0, `act_floor` 2 and `total_floor` 2. The
  recorded `run_map_choice` → `run_map_after_ancient` → `run_combat_action` sequence is the floor
  advance itself, read off the observations: `act_floor` and `total_floor` go 0 → 1 → 2, and the
  test asserts exactly that rather than inferring it. The recorded conditional
  (`run_seeded_full_act_corpus.py --seeds 1`) reaches victory on this build, so the environment is
  healthy across all three acts.
- **Acceptance scripts.** 17 of the 18 run-driving scripts pass against the new hash and observation
  schema: `acceptance.py`, `run_room_entry_acceptance.py`, `run_room_cycle_acceptance.py`,
  `run_composed_utility_rooms_acceptance.py`, `run_event_combat_acceptance.py`,
  `choice_acceptance.py`, `combat_breadth_acceptance.py`, `portable_modes_acceptance.py`,
  `run_map_acceptance.py`, `run_event_acceptance.py`, `run_rest_acceptance.py`,
  `run_option_reward_acceptance.py`, `run_item_reward_acceptance.py`,
  `run_reward_acceptance.py`, `ancient_choice_acceptance.py`, `ancient_room_acceptance.py` and
  `act_variant_acceptance.py`. The exception is `run_custom_reward_acceptance.py`, which fails at
  its first `worker.restore(ordinary_handle)` with `unknown_state_handle` — **the same failure at
  the same line on `HEAD` without this change**, verified by stashing `src/`, rebuilding and
  re-running, and already recorded as ticket 04's separate branch/restore defect.
- `python -m pytest tests -q` gives **39 passed, 22 errors**, where every error is the documented
  `tmp_path` sandbox refusal in `test_dev_environment.py`/`test_sandbox*.py` — files this change does
  not touch — and not a failure. `python -m compileall -q python tests`,
  `pwsh scripts/test-public-tree.ps1`, `ruff check` and `mypy` are clean on everything this change
  adds; the package keeps its 16 pre-existing mypy findings.
- **Not changed, deliberately.** The full-app bridge's own observation is untouched (tickets 11–13
  own it), and with it the bridge's `SchemaVersion = 2` and the two incomparable hashes the review
  describes. `scoring_features.schema_version` stays 3 because its shape did not move. The
  stale `kind` enum in `legal-action.schema.json` is left alone; the canonical schema describes a
  legal action's shape inline rather than referencing a file whose enum contradicts the actions the
  environment emits. `uv.lock` is left alone too: it was already inconsistent with `pyproject.toml`
  before this change (`numpy` and `gymnasium` are absent from it), and regenerating it here would
  land ~400 lines of unrelated resolution and marker churn.
- **Two things a reviewer should know.** The recorded drive stops at the act transition rather than
  walking into act 2, because act 2's Ancient opens nested prompts this run-mode walk cannot answer
  (it errors with `internal_error`) — acts beyond act 1 are out of scope for this feature.
  And `docs/agents/dev-environment.md` gained one line that cost time here and that ticket 04 had
  recorded only in its own comment: the Godot worker loads GodotHost's **Debug** output, so
  `build-persistent-server.ps1`'s default `Release` build alone leaves it answering from stale
  assemblies, with no error.

**2026-09-17 — two-axis review, and what it changed.**

Standards and spec were reviewed in parallel against this working tree. What the review changed:

- **A false sentence in the new dev-environment bullet.** It had claimed "every script that starts a
  worker already passes `-Configuration Debug`"; `bootstrap.ps1:27` passes `Release`, and
  `doctor.ps1` builds nothing. The bullet now says what each of those two does and names the four
  PowerShell Godot scripts that do build Debug themselves.
- **Two missing run stages.** The `terminal` combat capture (a fight the player loses) is now recorded
  — `drive_fatal_run` walks a 1 HP run into the first row-1 fight — and the map capture the Ancient
  room hands back is recorded separately as `run_map_after_ancient`, so the floor advance the ticket
  exists for is a capture in the fixture (`0 → 1 → 2`, asserted) rather than a claim about a capture
  that was overwritten by `record`'s keep-the-first rule. The fixture's own description of "every run
  stage" is now accurate about which ones it covers. `run_terminal` proper — a run that ends outside
  combat — is not reached by any drive; `_runStage` only becomes `run_terminal` while the player is
  dead and not in a combat, and its observation is the act-transition shape with a different
  `decision.kind`.
- **The version bump is now pinned on both halves.** One test reads
  `ObservationSchemaVersion` out of `Messages.cs` (which must equal the schema's `const`) and
  `hash_schema_version` out of the environment (which has no other home), so reverting either is a
  test failure. `tests/test_public_smoke.py` stopped carrying a third copy of the observation
  version and checks only that the two published files parse.
- **Duplicated drive logic removed.** The decision-kind → action cascade and the act-clearing run both
  now come from `run_seeded_full_act_corpus`, which walks whole acts; this script adds only the
  planned map steps that put a shop, a rest site and a treasure room in front of that walk. The
  `record` helper was renamed `record_first` so the keep-the-first rule is in the name.

What the review raised and this change deliberately did not do:

- **`run.deck`'s two shapes stay two.** The standalone reward and room-reward captures emit bare model
  ids while every other run block emits `{model_id, upgrades}`. The schema describes both, and now
  says in a `description` that the union is what the environment emits and that unifying them is a
  change to the environment, not to the schema — making the divergence visible rather than silently
  tolerated.
- **`jsonschema` stays a runtime dependency.** The review read it as test-only; the module that
  validates lives in the package, and the spec's testing decisions put the row check in the generator,
  which is also in the package.
- **The three `act_*`/`total_floor` reads stay bare integers** travelling through C#, the schema and
  `observations.py`. A named group for them would be a type with no behaviour, and the schema's
  conditional requirement is where the grouping actually matters.
- **`total_floor` on the map capture stays.** The spec's bullet asks for the combat observation's run
  block, and this is one field more; it is what makes the floor advance observable at all, which is
  the ticket's own motivation, and it is additive.
- **`AGENTS.md` is not part of this change.** It was already modified in the working tree before this
  work started; that edit is someone else's and is left uncommitted.
- The review also noted `docs/architecture-review.md`'s other staleness (its date and its "no
  `CONTEXT.md`" note) and the pre-existing I001 finding in `tests/test_public_smoke.py`. Both predate
  this change and are left alone.
