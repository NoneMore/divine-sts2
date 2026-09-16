# 11: The bridge's combat block carries the full parity contract

**What to build:** The full-app bridge's combat observation stops being a subset of the state it stands for, so the oracle can compare a shipped run against a generated scenario instead of comparing whatever the bridge happened to expose. A combat observation gains the encounter id, the granular turn phase, stars, and max energy with energy inside the combat block; every creature reports its side, its complete ordered intent list with each intent's type, damage and repeat count, and its powers as model id and amount; and the player appears as a creature row of its own rather than only as flattened scalars.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] A combat observation names its encounter, so a parity check has something to compare and an audit can identify a fight.
- [x] A combat observation distinguishes the granular turn phase rather than only a turn number, and its phase words map onto the simulator's decision kinds through one explicit, documented mapping.
- [x] Energy, max energy and stars all sit inside the combat block, and the energy value comes from the same accessor the repository's other projections use.
- [x] Every creature row reports its side, and the player is one of those rows.
- [x] Every creature reports its complete intent list rather than only the next move's id, with each intent's type, damage and repeat count.
- [x] Every creature reports its powers as model id and amount.
- [x] Fields the bridge can reach only by reflection are reached through helpers that live with the bridge, without the bridge referencing the simulator's own assembly.
- [x] The combat shape converges on the repository's existing rich per-combat projection rather than becoming a third shape.
- [x] A bridged shipped run reports these fields end to end, not only in static reading.

## Comments

**2026-09-16 — implemented.**

- **The bridge's combat block is now the repository's per-combat projection rather than a subset of
  it.** `combat.encounter` is the encounter's own id (`ICombatState.Encounter.Id.Entry` — the
  identity `catalog` lists, the trace exporter reports and the simulator's `combat.encounter`
  carries); `combat.phase` is `PlayerCombatState.Phase.ToString()`, the shipped `PlayerTurnPhase`
  word the simulator reports verbatim; `combat.energy`, `combat.max_energy` and `combat.stars` came
  inside the block from the same accessors the other projections read; and `combat.enemies` is gone,
  replaced by `combat.creatures` — every creature in native order, the player's own row included,
  every row worded exactly as the simulator's `Creature` row is (`combat_id`, `model_id`, `side`,
  `hp`, `max_hp`, `block`, `alive`, `next_move{id,intents[{intent_type,implementation,damage,repeats}]}`,
  `powers[{model_id,amount}]`). `next_move` carries the whole ordered intent list instead of the
  next move's id, and an attack intent's damage is `AttackIntent.GetSingleDamage`, the number the
  shipped hook chain resolves. The bridge's own `schema_version` moved 2 → 3 with the shape; tickets
  12 and 13 move it again for the ordered piles and the run block.
- **Nothing needed reflection, so nothing reached for the simulator's assembly.** Every member this
  ticket reads — `ICombatState.Creatures`/`Encounter`, `Creature.Side`/`Powers`/`Monster.NextMove`,
  `MoveState.Intents`, `AbstractIntent.IntentType`, `AttackIntent.GetSingleDamage`/`Repeats` — is a
  public member of the game assembly the bridge already references, so the rows are built with typed
  access and no helper layer. `tests/test_bridge_observation_shape.py` asserts the constraint that
  motivated the ticket's reflection bullet instead: the bridge's project file and every one of its
  `.cs` files must not mention `Sts2.NativeSim.Core`.
- **One explicit phase vocabulary, with tests that have teeth.** `python/sts2_native_sim/decision_vocabulary.py`
  holds the mapping in both directions the repository needs: a bridge observation phase word → the
  simulator decision kinds reported while the bridge is there, and a `combat.phase` word → the
  decision kinds it is a boundary for (`Play` is where both drivers offer actions, `None` is the
  phase the terminal capture is observed in, and the four automatic phases and `End` are no decision
  boundary at all). `tests/test_decision_vocabulary.py` (25 tests) reads the phase words out of the
  bridge's own two emit sites, checks every mapped kind is a kind the simulator's source actually
  reports, and checks each pairing against the recorded captures that pin it — a wrong pairing in
  the observed part is a failure, and the unobserved entries (the smith screen, the simple card
  select, the run-terminal stage the fixture never reaches) say so in the module's docstring.
  Ticket 15's projection layer is the intended caller. Nothing else in the repository maps these
  words, and an unknown word raises rather than defaulting to "no decision".
- **Null members are dropped, which is what "absent" means in every other projection.** The native
  worker and the trace exporter both serialize with `JsonIgnoreCondition.WhenWritingNull`, so a
  field that can be null — the player's `next_move`, a non-attack intent's `damage`/`repeats` — is
  absent in their captures. The bridge wrote `null` instead, which would have made a field-by-field
  comparison report a difference for a state the two encoders agree on. One `BridgeJson.Options`
  now serves both the observation writer and the state hash, and the acceptance asserts the
  difference: a non-attack intent must not carry `damage` or `repeats` at all.
- **Observed with the shipped game** (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`), by the new
  `python/bridge_combat_observation_acceptance.py`: one headless worker, seed `A1B2C3D4E5`,
  `IRONCLAD`, Ascension 0, driven `event → event → map → combat` by the first legal action at each
  boundary. The row-1 fight reports `encounter: "SLUDGE_SPINNER_WEAK"`, `turn` 1, `phase: "Play"`,
  `energy` 3 of `max_energy` 3, `stars` 0, bridge state hash
  `DC382F57D14B72A793AA142A469E8858F666D4AB1E06481F512E616BAA65A7D6`, and two creature rows:
  `IRONCLAD`/`Player` at 80/80 with `combat_id` 0 and no `next_move`, and `SLUDGE_SPINNER`/`Enemy` at
  39/39 whose `next_move` is `OIL_SPRAY_MOVE` with `SingleAttackIntent` damage 8 repeats 1 **and** a
  `DebuffIntent` carrying neither `damage` nor `repeats`. The script plays the fight on until a power
  is reported, which is the only way the power row is observed rather than declared: on turn 2 the
  player carries `WEAK_POWER` amount 1, with the state hash
  `3AB581115FD74B392F360F5C50ECF35BCA645D206D469CD805FA633691DC29DF` — the same hash on a second
  worker's run, which is also the determinism check for these fields. Every observation on the way is
  checked, and the checks include the two cross-accessor ones the ticket is about — `combat.energy`
  equals the observation's `player_energy`, and the player row's `hp`/`max_hp`/`block` and powers
  equal the flattened scalars and `player_powers` beside them.
- **Offline, `tests/test_bridge_observation_shape.py` (9 tests)** compares the bridge's own DTO
  declarations against two things at once: the recorded capture `run_combat_action` in
  `tests/fixtures/canonical-observations.json` (the creature, move, intent and power rows have to
  match it key for key) and the simulator's own projection in
  `PersistentNativeCombatEnvironment.cs` (every converged key spelled the way the simulator spells
  it). That is the convergence the architecture review asked for, checked without the game.
- **Deliberately not in this ticket.** The ordered piles and the per-card fields stay as they were
  (the hand list and the pile counts) for ticket 12, which replaces them; the run block, the flat
  player scalars, relics and potions stay for ticket 13; and `orbs`, which the trace exporter and
  the simulator report, are in neither the bridge nor the parity contract, so no ticket owns them.
  `full_act_bridge_acceptance.py` and `a1_champion_policy.py` — the two Python consumers that read
  the removed enemy rows — were moved onto `creatures` in the same change, so nothing reads the old
  shape; `a1_champion_policy.py`'s incoming-damage estimate now sums the attack intents' damage ×
  repeats instead of guessing 6 per enemy, and its `player_block` read, which had been looking for
  that field inside the combat block where it never lived, reads the observation.
- **Gates.** `python -m pytest tests -q` gives **145 passed, 22 errors**, where all 22 are the
  documented `tmp_path` sandbox refusal in `test_dev_environment.py`/`test_sandbox*.py` — files this
  change does not touch. `ruff check` and `mypy` are clean on everything this change adds (the
  surrounding scripts keep their pre-existing findings), `pwsh scripts/test-public-tree.ps1` passes,
  and the bridge builds in `Release` with 0 warnings and 0 errors under `TreatWarningsAsErrors`.

**2026-09-16 — two-axis review, and what it changed.**

Standards and spec were reviewed in parallel against this working tree. Both reviewers could read
the tree and both built or ran what they could; neither could produce the runtime evidence, because
the review runs under a workspace-write policy and the acceptance hard-links its sandbox onto the
game's volume, so the run recorded above is the implementer's. Summary: **Standards — no documented
standard breached, nine baseline-smell judgement calls; Spec — seven of nine checklist items
confirmed with evidence, the ninth (runtime evidence) marked declaration-only by the reviewer and
since measured, plus two implementation corrections.**

What the review changed:

- **`combat.encounter` is absent rather than `""` when a fight cannot name itself**, which is how the
  simulator and the trace exporter report it (a null member is dropped, and `""` is a value no
  comparison can tell from a name). No live fight is affected; the point is that the missing case now
  reads the same in all three projections.
- **The turn-phase row for `None` is pinned instead of glossed over.** The table mapped `None` onto
  `terminal` while its comment claimed every phase but `Play` maps onto no decision. The comment now
  says what the shipped enum means by `None` (not in progress *and* the enemy's turn, so `terminal`
  is the kind it can stand for), one test asserts that pairing against the recorded terminal capture
  (`phase: "None"`, `decision.kind: "terminal"`), and a second asserts that every `combat.phase` word
  a recorded capture reports is a mapped word.
- **The stage vocabulary gained a caller and a measurement.** `decision_kinds_for_bridge_phase` had
  none; the bridge acceptance now runs every observation on the way to the fight through it, so a
  bridge that grows a stage word nobody mapped fails the acceptance rather than quietly a comparison.
- **Bare ticket numbers left the new C# and package comments.** `ProtocolMessages.cs`,
  `decision_vocabulary.py` and the two new tests now describe the thing rather than naming a number
  that identifies nothing outside `.scratch/act1-combat1-scenarios/`.
- Two smaller repairs: the vocabulary's two lookup functions shared one `KeyError` → `ValueError`
  shape and now share one helper, and the acceptance script's `_check` no longer takes a record it
  used only as error context.

What the review raised and this change deliberately did not do:

- **The stage-word table stays**, though the spec review read it as the projection layer's work. The
  ticket's second checklist item asks for the mapping, and the spec's vocabulary paragraph is about
  exactly these words ("the bridge's phase names and the simulator's decision kinds are different
  words for the same situations, so the comparison needs one explicit mapping rather than a guess");
  the field-by-field projection is its consumer. Its two unobserved rows (`deck_upgrade`,
  `simple_card_select`) stay flagged as read from structure rather than observed — that is what the
  evidence table is for, and each pairing that *is* observed is checked against its capture.
- **The `side == "Enemy"` filter stays duplicated in the two consumer scripts.** It is one line in two
  scripts outside the package, there is no third caller in this change, and a helper in
  `observations.py` would be a module neither script otherwise uses.
- **`combat.energy` and the flat `player_energy` both stay.** The parity contract puts energy inside
  the combat block; the flat scalar is the bridge's older seam; and the acceptance asserting they
  read the same accessor is the check that keeps the duplicate honest until the run block converges
  and removes it.
- **The two tables stay two tables.** Bundling the evidence into the mapping would make every caller
  unwrap a record to reach a `frozenset`; the evidence is provenance with no behaviour, and
  `test_every_mapped_bridge_phase_has_its_evidence_named` is what keeps the keys in step.
- **`SIMULATOR_DECISION_KINDS` stays pinned by literal presence in the simulator's source.** It is a
  guard against a typo or an invented kind, not a reader of the simulator's vocabulary; 15 of the
  kinds it declares are pinned at runtime by the recorded captures, and the three that are not
  (`option_choice`, `custom_reward_choice`, `custom_reward_complete`) are ones the parity run meets
  first.
- **The standards review's stale-consumer finding is a false positive.**
  `expert_combat_retriever.py`, `pure_neural_agent.py`, `train_combat_policy.py` and
  `neural_turn_search.py` do read a `combat.enemies` key with `is_alive`/`enemy_id`, but not the
  bridge's: none of them imports the bridge client, and `enemy_id` is a key of the V10 supervision
  corpus (`compile_native_rollouts.py:98`) that the bridge never emitted. The two live bridge-fed
  readers are the two this change migrated.
- **The bridge's DTO stays a hand-written declaration** while `docs/architecture-review.md` §2 wants
  one typed observation record with a generated schema. That consolidation is its own candidate and a
  much larger change; this ticket's spec forbids the alternative of a second projection on the bridge,
  and what this change does is remove a shape (the enemy row) rather than add one.

**2026-09-16 — the evidence document was corrected too.** `parity-findings.md` still read as though
the bridge's combat observation carried none of this ("it is not today … the encounter id and the
ordered draw pile are known gaps"). Its inventory is now explicitly the pre-change one, the repaired
fields are recorded with the runtime observation above, and the remaining gaps (ordered piles,
per-card fields, run block, inventory) are named as what still keeps the field-by-field comparison
from running.

