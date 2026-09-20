import ast
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from sts2_native_sim import (
    NativeObservedMaterialScorer,
    NativeTorchValueScorer,
    NativeWorker,
    NativeWorkerPool,
    encode_scoring_features,
)
from sts2_native_sim.scenarios import CombatEpisode, materialize_scenario

ROOT = Path(__file__).resolve().parents[1]


def test_python_support_areas_exist() -> None:
    expected = [
        ROOT / "python" / "tools",
        ROOT / "python" / "experiments",
        ROOT / "tests" / "acceptance",
    ]

    assert all(path.is_dir() for path in expected)


@pytest.mark.parametrize(
    ("area", "entries"),
    [
        (
            ROOT / "python" / "tools",
            {
                "benchmark_rl_rollout_engine.py",
                "compile_native_rollouts.py",
                "comprehensive_benchmark.py",
                "diagnose_incomplete_turn.py",
                "diagnose_toadpoles_turn.py",
                "differential_campaign.py",
                "differential_replay.py",
                "evaluate_native_value_search.py",
                "generate_full_act_trajectories.py",
                "latency_benchmark.py",
                "native_corpus.py",
                "native_rollout_farm.py",
                "promote_differential_candidates.py",
                "run_event_corpus.py",
                "run_seeded_full_act_corpus.py",
                "schedule_autotrace_campaign.py",
                "shadow_encounter_composition_audit.py",
                "soak_test_20_workers.py",
                "stress_test.py",
                "test_scenarios_validation.py",
                "trace_inventory.py",
                "train_native_value_corpus.py",
                "train_native_value_matrix.py",
                "train_native_value_smoke.py",
                "tune_native_value_matrix.py",
            },
        ),
        (
            ROOT / "python" / "experiments",
            {
                "a1_champion_policy.py",
                "agentic_macro_prior.py",
                "compile_agentic_combat_supervision.py",
                "compile_community_route_prior.py",
                "densify_community_runs.py",
                "empirical_a10_macro.py",
                "expert_combat_retriever.py",
                "extract_agentic_macro_decisions.py",
                "full_act_search_benchmark.py",
                "ingest_community_runs.py",
                "native_fitness_champion.py",
                "native_outcome_macro_prior.py",
                "native_rollout_policy.py",
                "neural_champion_policy.py",
                "neural_turn_search.py",
                "pure_neural_agent.py",
                "run_a1_champion_benchmark.py",
                "trace_single_run.py",
                "train_a1_champion.py",
                "train_campfire_policy.py",
                "train_combat_policy.py",
                "train_expert_combat_retriever.py",
                "train_macro_prior.py",
            },
        ),
        (
            ROOT / "tests" / "acceptance",
            {
                "acceptance.py",
                "act_variant_acceptance.py",
                "ancient_choice_acceptance.py",
                "ancient_room_acceptance.py",
                "bridge_card_select_acceptance.py",
                "bridge_combat_observation_acceptance.py",
                "choice_acceptance.py",
                "combat_breadth_acceptance.py",
                "differential_harness_acceptance.py",
                "full_act_bridge_acceptance.py",
                "full_app_bridge_acceptance.py",
                "full_app_unlock_acceptance.py",
                "native_value_matrix_acceptance.py",
                "native_value_scorer_acceptance.py",
                "observation_schema_acceptance.py",
                "option_choice_acceptance.py",
                "parity_run_acceptance.py",
                "portable_modes_acceptance.py",
                "run_composed_utility_rooms_acceptance.py",
                "run_custom_reward_acceptance.py",
                "run_event_acceptance.py",
                "run_event_combat_acceptance.py",
                "run_item_reward_acceptance.py",
                "run_map_acceptance.py",
                "run_option_reward_acceptance.py",
                "run_rest_acceptance.py",
                "run_reward_acceptance.py",
                "run_room_cycle_acceptance.py",
                "run_room_entry_acceptance.py",
                "scenario_record_acceptance.py",
                "search_coordinator_acceptance.py",
            },
        ),
    ],
)
def test_maintained_python_entry_points_live_in_their_support_area(
    area: Path, entries: set[str]
) -> None:
    missing = sorted(name for name in entries if not (area / name).is_file())

    assert missing == []


@pytest.mark.parametrize(
    ("published_name", "implementation_module"),
    [
        ("native_rollout_farm.py", "tools.native_rollout_farm"),
        ("soak_test_20_workers.py", "tools.soak_test_20_workers"),
    ],
)
def test_published_command_launcher_preserves_arguments_and_exit_behavior(
    monkeypatch: pytest.MonkeyPatch,
    published_name: str,
    implementation_module: str,
) -> None:
    arguments = [published_name, "--sentinel", "value"]
    observed: list[tuple[str, str, list[str]]] = []

    def run_module(module_name: str, *, run_name: str) -> None:
        observed.append((module_name, run_name, sys.argv.copy()))
        raise SystemExit(23)

    monkeypatch.setattr(runpy, "run_module", run_module)
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(SystemExit, match="23"):
        runpy.run_path(str(ROOT / "python" / published_name), run_name="__main__")

    launcher = str(ROOT / "python" / published_name)
    assert observed == [(implementation_module, "__main__", [launcher, *arguments[1:]])]


def test_supported_package_does_not_import_lower_support_areas() -> None:
    forbidden_roots = {"tools", "experiments", "tests"}
    violations: list[str] = []

    for path in (ROOT / "python" / "sts2_native_sim").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if module.split(".", 1)[0] in forbidden_roots:
                    violations.append(f"{path.name}:{node.lineno}: {module}")

    assert violations == []


def test_combat_research_primitives_remain_importable() -> None:
    primitives = [
        materialize_scenario,
        CombatEpisode,
        NativeWorker,
        NativeWorkerPool,
        encode_scoring_features,
        NativeObservedMaterialScorer,
        NativeTorchValueScorer,
    ]

    assert all(callable(primitive) for primitive in primitives)


@pytest.mark.parametrize(
    "relative_path",
    [
        "python/tools/run_seeded_full_act_corpus.py",
        "python/tools/generate_full_act_trajectories.py",
        "tests/acceptance/observation_schema_acceptance.py",
        "python/experiments/full_act_search_benchmark.py",
    ],
)
def test_moved_commands_resolve_their_cross_area_imports(relative_path: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / relative_path), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_autotrace_pipeline_uses_the_relocated_trace_tools() -> None:
    script = (ROOT / "scripts" / "run-isolated-autotrace.ps1").read_text(encoding="utf-8")

    assert "python\\tools\\differential_replay.py" in script
    assert "python\\tools\\trace_inventory.py" in script
    assert "python\\differential_replay.py" not in script
    assert "python\\trace_inventory.py" not in script


def test_rollout_farm_reaches_the_learned_policy_as_an_experiment() -> None:
    path = ROOT / "python" / "tools" / "native_rollout_farm.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "experiments.native_rollout_policy" in imported_modules
