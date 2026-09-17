# 13: Run, inventory and act identity on the bridge

**What to build:** The bridge's run and inventory blocks gain what a parity contract needs, and stop reporting the wrong numbers where they already look present. The bridge reports the game build it is running; the act index in the same base as the rest of the system instead of one-based; the Act variant alongside it; the act floor as well as the run's total floor; the map coordinate the run is on, including the row-0 Ancient coordinate once the run has travelled there; the named RNG counters; relics in order as objects carrying their counter and native state rather than bare model ids; and potions by slot with their native state, keeping empty slots so a slot index is never destroyed.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] The bridge reports the game build it is running.
- [x] The act index is reported in the same base as the rest of the system, and the Act variant is reported alongside it, so neither has to be re-derived by a comparison.
- [x] Both the act floor and the run's total floor are reported.
- [x] The current map coordinate is reported, including the row-0 Ancient coordinate once the run has travelled to it.
- [x] The named RNG counters are reported, with the same names the simulator uses.
- [x] Relics are reported in order as objects carrying model id, counter and native state, not as bare model ids.
- [x] Potions are reported by slot with model id and native state, and empty slots are retained so the slot index survives.
- [x] A bridged shipped run reports these fields end to end, not only in static reading.

## Comments

**2026-09-16 — implemented.**

- **The bridge's flat run and inventory members became the repository's two blocks.** `seed`,
  `ascension`, `act`, `floor`, `gold`, `relics` and `potions` are gone from `ObservationDto`, and a
  fight now carries `run`, `map_coord`, `inventory` and `game_build` beside it. The names are the
  simulator's own — `run`'s eight members are word for word the combat-run block
  `PersistentNativeCombatEnvironment` emits (`seed`, `ascension`, `gold`, `act_variant`, `act_index`,
  `act_floor`, `total_floor`, `rng_counters`), the relic row is its `relics` row
  (`model_id`, `counter`, `native_state`), and the potion row is its `potions` row plus the
  `native_state` a potion carries — so the ticket-15 projection layer has a shape to normalise to
  rather than a third vocabulary to translate. The bridge's `schema_version` moved 4 → 5 with the
  shape, as ticket 12's comment said it would, and the bridge's DTO-covering state hash moved with it.
- **Two of the repairs are of values that looked present while reading the wrong thing.** `act` was
  `CurrentActIndex + 1` while the rest of the system is zero-based, so a comparison that trusted it
  compared the wrong number; `relics` and `potions` were bare model ids, and skipping an empty potion
  slot destroyed the slot index of every potion behind it. All three are now the run's own values:
  `run.act_index` is `CurrentActIndex`, `act_variant` is `Act.Id.Entry` — the model the seed rolls,
  which no bridge projection reported before — and the potion list is one entry per slot with `null`
  where the slot is empty, which is how the simulator's own inventory reports an empty belt.
- **The map coordinate is read from `RunState.CurrentMapCoord`**, the last visited coordinate. That
  is what makes the row-0 Ancient reachable rather than a special case: `RunManager.EnterRun` travels
  to the act's `StartingMapPoint` at run start (`RunManager.cs:1249`), so the coordinate the first
  decision of a run stands on *is* the Ancient's. Ticket 15 can therefore check the node the oracle
  reached, which the fight's own block cannot say. `map_coord` is the bridge's own member name for a
  value the repository already names twice elsewhere — the simulator reports it as `map.current`
  inside its map capture and as `map_col`/`map_row` in its scoring features, and the record carries
  the node it drove to as `recipe.node` (`col`, `row`, `point_type`). A partial `map` block was not an
  option: the published schema's `map` requires `points` and `visited` beside `current`, and a combat
  observation has neither. The projection layer therefore maps three names onto one value, and this is
  the name the bridge's side of that mapping uses.
- **`GameBuild.cs` fingerprints the install the way the simulator's worker and the trace exporter
  already do** — the `sts2` assembly's product version, the SHA-256 of the assembly, and the SHA-256
  of `SlayTheSpire2.pck` beside its directory — measured once per process, because the pack is
  gigabytes and the answer cannot change while one process lives. The observed values are byte for
  byte the ones the recorded captures carry (`A1F9E653…`, `42520EB8…`,
  `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314`), which is what lets a parity run attribute a
  mismatch to a build. The `hello` reply reports the same block, replacing a version string that had
  been hardcoded to one build — and reporting the build *once* in the worker's handshake rather than
  once as a block and once as a flat `version`, which is the shape the simulator's own `hello`
  reports. Measuring it costs one read of the 1.77 GB data pack, 4.0 s measured on this host, paid
  once per worker process on the first handshake or observation.
- **A potion's native state is reported and is always empty, and that is a deliberate superset.** The
  shipped `SerializablePotion` saves its model and its slot index and nothing else, so an occupied slot
  carries `native_state: {}` — the field exists because the ticket asks for it and because the trace
  exporter's own reset projection reports the same empty state for the same reason. It is worth being
  explicit about the seam it creates: the feature spec's parity contract lists a potion as "model id"
  only, and the published schema's potion row allows `slot` and `model_id` under
  `additionalProperties: false`, so ticket 15's projection compares the two members the record has and
  ignores this one rather than expecting a counterpart. It is the only member of the new blocks that
  the record side has no home for.
- **Observed with the shipped game** (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`), by the extended
  `python/bridge_combat_observation_acceptance.py`: one headless worker, seed `A1B2C3D4E5`,
  `IRONCLAD`, Ascension 0, driven `event → event → map → combat` by the first legal action at each
  boundary. At the Ancient the run reports `map_coord {col: 3, row: 0}`, `act_index` 0,
  `act_variant` `UNDERDOCKS`, `act_floor` 1 and `total_floor` 1; at the row-1 fight
  (`SLUDGE_SPINNER_WEAK`) it reports `map_coord {col: 1, row: 1}` and both floors 2, so the Ancient
  room is observed advancing the counter the per-encounter generator is seeded with. `gold` is 99 at
  both, the seed is the requested `A1B2C3D4E5`, and `rng_counters` carries all twelve of the run's
  own counters, `UpFront` 404 throughout and `Niche`/`Shuffle` moving 0/0 → 1/9 with the fight. The
  relics are `BURNING_BLOOD` then `BOOMING_CONCH` — the starting relic, then the one the first
  Ancient choice grants — each an object with its native state (`{"HasTriggered": false}` on the
  first), and the belt is `[null, null, null]`: three slots, none filled, which is exactly the slot
  index an empty list would have destroyed. The build block is identical in `hello` and in the
  observation. Reading the same state twice returns the same run block and the same inventory, so
  neither is reassembled differently on a rebuild. Bridge state hash
  `1F49ECE13760D40EB3E82538289AE46A0146792329816F1A66C2CB72FB7651B4` at the fight and
  `828CFA312C33DD227DF37E2848D2730E5DD5A7C799590EF2B9BFAA2EB9DDE0F1` once a power is reported
  (the player's `WEAK_POWER`); both differ from ticket 12's hashes because the schema version moved
  with the shape.
- **Nine Python readers were migrated, and one of the migrations is a real behaviour repair.** The
  belt's shape change alone would have silently inverted every "is the belt full" decision: a
  three-slot list is length 3 whether it holds three potions or none, so
  `full_act_bridge_acceptance.py`, `a1_champion_policy.py` and `pure_neural_agent.py` now count the
  entries that hold a potion. The rest read the run block through two new accessors,
  `bridge_run`/`bridge_inventory` in `sts2_native_sim/full_app_client.py`, which state the block
  names once for nine call sites (`full_act_bridge_acceptance.py`,
  `generate_full_act_trajectories.py`, `densify_community_runs.py`,
  `run_a1_champion_benchmark.py`, `trace_single_run.py`, `full_app_unlock_acceptance.py`,
  `pure_neural_agent.py`, `agentic_macro_prior.py`, `a1_champion_policy.py`). Two of those readers
  had been re-deriving the act from the floor (`((floor - 1) // 16) + 1`); both now read
  `run.act_index`, which is what the ticket asks a comparison never to have to do. The
  `neural_*`/`train_*`/`expert_*` scripts that read a flat `floor` stay as they are: they are fed by
  the V10 supervision corpus, not by the bridge.
- **Offline, `tests/test_bridge_observation_shape.py` (29 tests, 13 new)** compares the bridge's DTO
  declarations against the recorded capture `run_combat_action` and against the simulator's own
  projections: the run block is word for word the recorded one and no member the simulator does not
  have, the relic row is the simulator's row key for key, the potion row is that row plus the state
  it carries, the coordinate is the schema's `{col, row}`, the build is the recorded build, the act
  index is read from `CurrentActIndex` with no `+ 1` left anywhere, the counters come from
  `RunRngSet.ToSerializable().Counters` keyed by the enum's own name, and an empty potion slot is a
  null entry rather than a hole. Two more pin what a declaration cannot: the one method that builds a
  snapshot actually assigns `run`, `map_coord`, `inventory` and `game_build`, and the relic counter
  reads the two members the trace exporter's and the simulator's inventories read. One test also pins
  that the replaced flat members are gone, so the duplicate cannot come back as a second source of a
  number the blocks already report.
- **Gates.** `python -m pytest tests -q` gives **165 passed, 22 errors**, where all 22 are the
  documented `tmp_path` sandbox refusal in `test_dev_environment.py`/`test_sandbox*.py` — files this
  change does not touch. `ruff check` reports exactly the findings the pre-change tree had for every
  file this change touches (linted side by side against `HEAD` copies of those files: 236 findings,
  identical per-file and per-rule counts, both before and after the change), and `mypy` reports only
  the pre-existing findings of the surrounding code, with nothing on a line this change adds — the
  acceptance script this change rewrites (`bridge_combat_observation_acceptance.py`) is clean under
  both. The bridge builds in `Release` with 0 warnings and 0 errors under `TreatWarningsAsErrors`, and
  `pwsh scripts/test-public-tree.ps1` passes.
- **Deliberately not in this ticket.** The `deck_cards` seam stays flat: the deck is not part of the
  parity contract's run block, and a fight's five piles already carry it. `orbs` is still in neither
  the bridge nor the contract. The bridge's own `map_coord` name is not added to
  `schemas/canonical-state.schema.json`: that schema describes the simulator's captures, which carry
  the coordinate inside their `map` block, and the bridge's DTO is a separate shape — no test
  validates a bridge observation against it. Nothing here maps the bridge's phase words onto the
  simulator's decision kinds or compares two projections field by field — that is ticket 15, whose
  projection layer is now the only thing between this bridge and a first real comparison.

**2026-09-16 — two-axis review, and what it changed.**

Standards and spec were reviewed in parallel against this working tree by two reviewers who could read
it and run what they could; neither could produce the runtime evidence, because the review runs under a
workspace-write policy and the acceptance hard-links its sandbox onto the game's volume. Summary:
**Standards — no documented standard breached, six baseline-smell judgement calls. Spec — four of the
eight checklist items confirmed cleanly (the build, the act index and variant, both floors, the named
counters), four met but qualified (the coordinate's name needs a translation in ticket 15's projection,
the relic counter's present case is unobserved at runtime, the potion row carries one member the record
side has no home for, and the end-to-end item was protected only by a script outside `pytest`), plus two
implementation defects, both since fixed.**

What the review changed:

- **Two real defects in the migration, both found by the spec axis and both now fixed.**
  `agentic_macro_prior.select_event` and `select_potion` still built their fallback state key from the
  flat `seed`/`floor` this change removes, so a policy that fell back to a key (only when an
  observation carries no `state_hash`) would have lost the run's identity and its floor while the
  functions around them had been migrated — a missed edit inside a file the change does touch, and the
  kind of silent default the ticket exists to remove. And `run_a1_champion_benchmark` had lost the
  `min(3, …)` clamp when its act derivation became `act_index + 1`, so its `max_act_reached` metric
  could report an act it never scored; the clamp is back.
- **The handshake reports the build once.** `hello` carried both a `game_build` block and a flat
  `version` holding the same string, which is one build represented twice; the flat member is gone and
  the reply has the shape the simulator's own `hello` has. The standards axis raised it and no reader
  in the repository read the flat member.
- **Two offline pins added, because a declared member is not a reported one.** The spec axis observed
  that deleting `obs.Inventory = InventoryObservation(player)` — or either of the other two block
  assignments — left every test in the file green (27 of them at the time of review), with only the
  shipped-game acceptance to catch it. A test now
  pins that the one method that builds a snapshot reaches `run`, `map_coord`, `inventory` and
  `game_build`. A second pins the relic counter's accessor (`ShowCounter ? DisplayAmount : null`) against
  the trace exporter's and the simulator's own inventory rows, because the counter's *present* case is
  not observable on this run: neither relic the drive holds shows one, so the acceptance observes the
  absent case and its shape, and the accessor is what is pinned offline. That limit is stated in both
  places rather than implied.
- **The belt's occupancy got one name instead of three copies.** The
  `sum(1 for potion in … if potion)` idiom, with the same explanatory comment, had been repeated in
  three consumers; `bridge_potion_count` in `sts2_native_sim/full_app_client.py` is now the one place
  that says an empty slot is a null entry and not a potion.
- **The block readers were tidied.** `bridge_run` and `bridge_inventory` share one private
  `_bridge_block`, and the readers that walked `bridge_run(obs)` twice inside one expression hold one
  local. `derived_act` in the benchmark is `act_number`, which is what it now is.
- **What the review raised and this change deliberately did not do.** The potion's `native_state` stays
  (above). `map_coord` keeps its bridge-local name (above). The accessors keep returning an empty block
  for a missing one, because their callers are demo policies whose defaults are their own and the
  acceptance is the reader that fails loudly — that difference in failure contract is now stated in
  both docstrings rather than left to be inferred.


