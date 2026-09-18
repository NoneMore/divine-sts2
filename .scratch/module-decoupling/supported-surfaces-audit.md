# Supported-surface audit

This audit is the disposition record for issue 01. It describes the tree before the Python
reorganization: nothing listed here has been moved or deleted by this issue.

## Classification and evidence rules

- **Supported command** is a compatibility promise to users. At present this means the installed
  `divine-sts2` CLI, commands and imports shown in `README.md`, and the basic Gymnasium example.
- **Internal tool** is maintained because a repository workflow or later ticket consumes its unique
  capability, but its path and command line are not public compatibility promises.
- **Experiment** may require private corpora or model artifacts and has no compatibility promise.
  A broken experiment is kept only as research history; it must not be advertised as runnable.
- **Deletion candidate** has no uninvestigated consumer and no unique capability. This classification
  authorizes a later cleanup ticket, not deletion here.

Runability is classified as **offline** (help/import or data-only work), **native** (requires the
licensed shipped game and built worker), **full-app** (launches an isolated shipped-game client),
**artifact** (requires an input corpus/checkpoint), or **broken**. Native/full-app/artifact entries
are not failures merely because their external input is absent. Maintenance cost is relative:
**low** is a thin adapter, **medium** owns one workflow, and **high** owns duplicated models,
cross-process orchestration, or a broad end-to-end harness.

The audit used repository-wide inbound-reference searches, module parsing/compilation, `--help` for
the formal CLI and rollout farm, solution/project references, and the deletion commit `d6371e0`.
Static import evidence is decisive for the broken model stack: the repository no longer contains
`deck_transformer`, `combat_v1`, `combat_v5`, `train_v10_combat_policy`, `v9_tokenizer`,
`v9_transformer`, or `v12_combat_model`.

## Public commands and examples

| Entry | Class | Consumer and unique capability | Runability | Cost / disposition |
|---|---|---|---|---|
| `divine-sts2` / `python -m sts2_native_sim.cli` | supported command | README and package metadata; the only formal `doctor` and deterministic `scenario` corpus CLI | offline help; native execution | medium; retain |
| `python/native_rollout_farm.py` (default `random` mode) | supported command | README; persistent multi-worker episode/shard farm | native | high; retain. Its `learned` mode is the broken experiment listed below |
| `python/soak_test_20_workers.py` | supported command | README benchmark claim; sustained multi-worker throughput and crash accounting | native | medium; retain until benchmark consolidation |
| `examples/01_basic_gym_loop.py` | supported command | public example; minimal vector reset/step usage | native after project dependencies are installed | low; retain |
| `python/sts2_native_gym.py` | supported command (compatibility import) | README; legacy import launcher for the packaged `sts2_native_sim.gym` implementation | native after project dependencies are installed | low; keep through the planned deprecation period |
| `examples/02_mcts_search.py` | deletion candidate | no inbound consumer; calls `NativeSearchCoordinator.search` with nonexistent `reset_request`/`max_nodes` parameters, while `search_coordinator_acceptance.py` covers the real API | broken | low; remove rather than maintain a second example API |

The README previously promised `python/neural_turn_search.py`. It now advertises the formal scenario
command instead; the compatibility Gym import and unrelated public documentation are unchanged by
this ticket.

## Acceptance, parity, and diagnostic entries

All entries in this table are internal tools. They require a shipped-game installation unless the
runability column says otherwise. Their command paths may change when acceptance is consolidated.

| Entry | Consumer and unique capability | Runability | Cost / disposition |
|---|---|---|---|
| `python/acceptance.py` | shared scenario fixture for 14 scripts plus the original reset/step/fork milestone | native | medium; retain until its fixture and assertions are split |
| `python/act_variant_acceptance.py` | scenario acceptance and parity research; shipped seed-to-Act-variant oracle | full-app/native | high; retain |
| `python/ancient_choice_acceptance.py` | validates Ancient choices and nested prompts | native | high; retain |
| `python/ancient_room_acceptance.py` | scenario acceptance; shipped Ancient offer/composition oracle | full-app/native | high; retain |
| `python/bridge_card_select_acceptance.py` | parity run and decision vocabulary; full-app card-select contract | full-app | high; retain |
| `python/bridge_combat_observation_acceptance.py` | research record; full-app combat observation identity/order contract | full-app | high; retain |
| `python/choice_acceptance.py` | blocking choice, continuation, fork and replay coverage | native | medium; retain |
| `python/combat_breadth_acceptance.py` | upgraded cards, potions and exact replay breadth | native | medium; retain |
| `python/diagnose_incomplete_turn.py` | focused summon/death regression using the value-matrix scenario helpers | native | low; retain while the regression lacks an automated test |
| `python/diagnose_toadpoles_turn.py` | focused low-HP Toadpoles turn-boundary reproducer | native | low; retain while the regression lacks an automated test |
| `python/differential_harness_acceptance.py` | offline self-test of trace parsing/comparison | offline | low; retain |
| `python/full_act_bridge_acceptance.py` | policy supplier for two trajectory tools plus full-act determinism | native | high; retain |
| `python/full_app_bridge_acceptance.py` | full-app deterministic replay/branch harness | full-app | high; retain |
| `python/full_app_unlock_acceptance.py` | ADR-0001 unlock-policy verification on the full app | full-app | low; retain |
| `python/native_value_matrix_acceptance.py` | guards rejection of unpromoted critics | artifact/native | low; retain with scoring |
| `python/native_value_scorer_acceptance.py` | checkpoint provenance/search integration | artifact/native | low; retain with scoring |
| `python/observation_schema_acceptance.py` | records and validates the canonical observation fixture/schema | native | high; retain |
| `python/option_choice_acceptance.py` | only exercise of the Godot one-shot option-choice mode | native | medium; retain until equivalent coordinator tests exist |
| `python/parity_run_acceptance.py` | only recorded field-by-field generated-scenario comparison with the shipped game | full-app/native | high; protect |
| `python/portable_modes_acceptance.py` | portable branch provenance across every reset mode | native | low; retain |
| `python/run_composed_utility_rooms_acceptance.py` | merchant/rest/treasure composed path; reused by two acceptances | native | medium; retain |
| `python/run_custom_reward_acceptance.py` | custom, multi, linked and blocking rewards | native | low; retain |
| `python/run_event_acceptance.py` | event initialization, choices and replay | native | low; retain |
| `python/run_event_combat_acceptance.py` | map-to-event-to-combat transition | native | low; retain |
| `python/run_item_reward_acceptance.py` | relic and potion reward contract | native | low; retain |
| `python/run_map_acceptance.py` | deterministic map routing | native | low; retain |
| `python/run_option_reward_acceptance.py` | replayable relic-triggered option choice | native | low; retain |
| `python/run_rest_acceptance.py` | rest-site and Smith continuation | native | low; retain |
| `python/run_reward_acceptance.py` | card reward generation and selection | native | low; retain |
| `python/run_room_cycle_acceptance.py` | full map/combat/reward/map room cycle | native | medium; retain |
| `python/run_room_entry_acceptance.py` | composed map-to-combat entry | native | low; retain |
| `python/scenario_record_acceptance.py` | direct consumer of `generate_rows` and `generate_corpus`; recipe, parity-half, resume and byte-reproducibility contract | native | high; protect |
| `python/search_coordinator_acceptance.py` | deterministic branch expansion/ranking/search and scorer integration | native | medium; retain |
| `python/shadow_encounter_composition_audit.py` | compares observed native and shadow encounter signatures | native/artifact | medium; retain as an audit, not a supported simulator path |
| `python/stress_test.py` | branch metadata and sustained-reset memory stress | native | low; retain until benchmark consolidation |

## Generation, trace, corpus, and benchmark tools

| Entry | Class | Consumer and unique capability | Runability | Cost / disposition |
|---|---|---|---|---|
| `benchmark_rl_rollout_engine.py` | internal tool | standalone broad protocol/latency/determinism/reliability report; no inbound code consumer | native | high; retain until its unique report fields are mapped to focused tools |
| `test_scenarios_validation.py` | internal tool | standalone native validation of a legacy eight-scenario catalog; no inbound consumer | native | medium; its duplicated catalog has already drifted, so retain only until consolidation with the benchmark catalog |
| `python/benchmark.py` | deletion candidate | no inbound consumer; its restore-plus-step boundary is already measured by `latency_benchmark.py` and the comprehensive harness | native | low; later delete |
| `python/comprehensive_benchmark.py` | internal tool | combined latency/scaling/soak/stress/rollout JSON report | native | high; retain pending benchmark consolidation |
| `python/differential_campaign.py` | internal tool | parity research workflow; discovers, exact-replays, hashes and aggregates traces | artifact/native | medium; protect with trace path |
| `python/differential_replay.py` | internal tool | campaign, promotion and AutoTrace script; exact trace-to-worker comparator | artifact/native | medium; protect |
| `python/generate_full_act_trajectories.py` | internal tool | consumes full-act policy and exports parallel trajectories | native | high; retain |
| `python/latency_benchmark.py` | internal tool | separated resident/reset/restore/search/protocol timing boundaries | native | medium; retain |
| `python/native_corpus.py` | internal tool | catalog-wide shipped card/encounter exercise with worker replacement | native | medium; retain |
| `python/promote_differential_candidates.py` | internal tool | exact-replay gate and atomic promotion of candidate traces | artifact/native | low; protect with trace path |
| `python/run_event_corpus.py` | internal tool | census of every shipped event model | native | low; retain |
| `python/run_seeded_full_act_corpus.py` | internal tool | seeded autonomous Act 1 traversal corpus | native | medium; retain |
| `python/schedule_autotrace_campaign.py` | internal tool | selects uncovered encounters and drives isolated capture plus exact replay | full-app/native | high; protect with AutoTrace |
| `python/trace_inventory.py` | internal tool | campaign and AutoTrace script; read-only mechanic coverage inventory | artifact/offline | medium; protect with trace path |

## Data preparation, training, and policy experiments

These paths are not public commands. A runnable experiment may still require the `train` extra and
private data/checkpoints. The first table contains maintained internal data/scoring tools; the second
contains research experiments with no compatibility promise.

| Entry | Class | Consumer and unique capability | Runability | Cost / disposition |
|---|---|---|---|---|
| `python/compile_native_rollouts.py` | internal tool | scenario tests and scenario module use `shard_paths`; compiles native rollout shards | artifact/offline | medium; retain and later move shared helpers into the package |
| `python/evaluate_native_value_search.py` | internal tool | fresh-encounter/search-lift promotion gate | artifact/native | medium; protect with scoring |
| `python/train_native_value_corpus.py` | internal tool | builds a shipped-native terminal value corpus | native plus `train` extra | medium; protect with scoring |
| `python/train_native_value_matrix.py` | internal tool | two diagnostics, evaluator and tuner consume its scenario/gating helpers; provenance-gated critic training | native plus `train` extra | high; protect with scoring |
| `python/train_native_value_smoke.py` | internal tool | scorer acceptance; produces a smoke checkpoint | native plus `train` extra | medium; protect with scoring |
| `python/tune_native_value_matrix.py` | internal tool | consumes matrix ranking/gate helpers; cached hyperparameter selection | artifact plus `train` extra | low; retain |
| `python/a1_champion_policy.py` | experiment | no live code consumer; A1 draft/card controller artifact | artifact plus `train` extra | medium; isolate |
| `python/agentic_macro_prior.py` | experiment | only broken learned stack and neural agent consume it; empirical macro prior | artifact | medium; isolate |
| `python/compile_agentic_combat_supervision.py` | experiment | no inbound consumer; converts agentic logs to old V10-shaped transitions | artifact/offline | medium; isolate |
| `python/compile_community_route_prior.py` | experiment | no inbound consumer; route-occupancy compiler | artifact/offline | low; isolate |
| `python/densify_community_runs.py` | experiment | no inbound consumer; replays community seeds with the full-act policy | artifact/native | high; isolate |
| `python/empirical_a10_macro.py` | experiment | only broken learned stack consumes it; A10 macro policy | artifact | medium; isolate |
| `python/expert_combat_retriever.py` | experiment | broken learned stack and its trainer; nonparametric decision retrieval | artifact | medium; isolate |
| `python/extract_agentic_macro_decisions.py` | experiment | community ingestion invokes its extraction output; archive transformer | artifact/offline | medium; isolate |
| `python/full_act_search_benchmark.py` | experiment | no inbound consumer; policy/search-depth benchmark | native | medium; isolate |
| `python/ingest_community_runs.py` | experiment | macro-prior trainer input pipeline | artifact/offline | high; isolate |
| `python/native_fitness_champion.py` | experiment | no inbound consumer; imports the broken learned policy for Act-2 search | broken | high; do not advertise |
| `python/native_outcome_macro_prior.py` | experiment | only broken learned stack consumes it; outcome-weighted macro scorer | artifact | medium; isolate |
| `python/run_a1_champion_benchmark.py` | experiment | no inbound consumer; imports the broken pure-neural singleton | broken | high; do not advertise |
| `python/train_a1_champion.py` | experiment | produces the A1 controller checkpoint | artifact plus `train` extra | medium; isolate |
| `python/train_campfire_policy.py` | experiment | no inbound consumer; campfire policy trainer | artifact plus `train` extra | medium; isolate |
| `python/train_combat_policy.py` | experiment | no inbound consumer; standalone supervised combat trainer | artifact plus `train` extra | high; isolate |
| `python/train_macro_prior.py` | experiment | imports deleted `deck_transformer` | broken | medium; do not advertise |

### Broken learned/neural family

| Entry | Missing dependency / consumer | Unique surviving value | Runability / cost | Disposition |
|---|---|---|---|---|
| `python/neural_turn_search.py` | deleted `deck_transformer`, `v9_tokenizer`, `v9_transformer`; no code consumer | historical turn-search experiment only | broken / high | experiment; removed from README, do not reconstruct here |
| `python/neural_champion_policy.py` | same deleted modules; no code consumer | historical combined policy only | broken / high | experiment; do not advertise |
| `python/pure_neural_agent.py` | deleted `train_v10_combat_policy`; consumed only by two broken experiments | historical agent controller only | broken / high | experiment; do not advertise |
| `python/trace_single_run.py` | imports `pure_neural_agent` and executes at import time | historical single-run trace recipe only | broken / low | experiment; do not advertise |
| `python/native_rollout_policy.py` | deleted `combat_v1`, `combat_v5`, V10 and V12 modules; optional consumer is rollout-farm `--policy learned` | historical composite learned-policy wiring | broken / high | experiment; deterministic farm mode remains supported |
| `python/train_expert_combat_retriever.py` | deleted `train_v10_combat_policy.open_text` | packaging recipe for the retriever | broken / low | experiment; do not advertise |

No supported command imports this family on its default path. This issue deliberately does not
recreate the deleted model stack or claim that `native_rollout_farm.py --policy learned` works.

## Protected research inputs

The following are not cleanup candidates, even where their eventual file location changes:

| Capability | Current owner and consumers | Required disposition |
|---|---|---|
| request-to-rows scenario generation | `sts2_native_sim.scenarios.generate_rows`; direct acceptance consumer in `scenario_record_acceptance.py` | keep as an independently callable supported library interface; preserve recipe and row formats |
| deterministic corpus generation | `sts2_native_sim.scenarios.generate_corpus`; formal CLI and scenario acceptance | keep separate from `generate_rows`; preserve shard layout, resume and compressed-byte reproducibility |
| scenario acceptance/parity | `scenario_record_acceptance.py`, `parity_run_acceptance.py`, `act_variant_acceptance.py`, `ancient_room_acceptance.py` | retain until replacement tests cross the same shipped-game seam |
| worker lifecycle and RPC | exported `NativeWorker` and `NativeWorkerPool`; used throughout tools and acceptance | supported library surface; later modules may depend inward on it, never on scripts |
| forward transition | `NativeWorker.step` and `run_step`, plus `Sts2NativeVectorEnv.step` | preserve action-id semantics; the later Combat episode facade must delegate to this native transition rather than approximate it |
| scoring | exported `encode_scoring_features`, `NativeObservedMaterialScorer`, `NativeTorchValueScorer`; search acceptance and native-value tools | retain provenance gates and native observation inputs; later combat research needs a scorer without the deleted neural stack |
| exact shipped-game traces | AutoTraceDriver, TraceExporter, `differential_replay.py`, promotion and inventory tools | retain end to end; it is the only automated route from a shipped-game playthrough to exact worker replay |

## Edge C# tools

| Entry | Class | Consumer and unique capability | Runability | Cost / required disposition |
|---|---|---|---|---|
| `src/Sts2.NativeSim.AutoTraceDriver` | internal tool | built and packaged explicitly by `scripts/run-isolated-autotrace.ps1`; uniquely drives bounded shipped-game combats so TraceExporter can record them | full-app | high; **retain and protect**. Its absence from the solution is deliberate for now: the owning script builds the game-data-dependent mod directly. Revisit placement, not existence, in the later tools reorganization |
| `tests/Sts2.NativeSim.TraceExporterSmoke` | deletion candidate | the solution only builds it; nothing runs it, it has no assertion/exit contract, and both hosts already implement the real `--trace-exporter-smoke` path | native if manually run | low; delete in the later edge-tool cleanup and keep the host smoke modes |
| `tools/Sts2.NativeSim.ApiProbe` | deletion candidate | no references outside itself; generic type/member reflection is available from sibling decompiled source and ordinary inspection, and it contributes no simulator assertion | offline with game assemblies | low; delete in the later edge-tool cleanup |

## Deletion-candidate check

The complete candidate set is `examples/02_mcts_search.py`, `python/benchmark.py`,
`tests/Sts2.NativeSim.TraceExporterSmoke`, and `tools/Sts2.NativeSim.ApiProbe`. Repository-wide search
found no unlisted consumers. Each capability is already owned by a maintained surface respectively:
`NativeSearchCoordinator` plus `search_coordinator_acceptance.py`, `latency_benchmark.py`, the two host
smoke modes, and sibling-source/general reflection inspection. All other zero-inbound entries remain
internal tools or experiments because they still own a distinct acceptance, diagnostic, report, data
transform, or research recipe.
