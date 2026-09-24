"""RESEARCH PROTOTYPE: compare one-seed native batches with the Python scenario driver.

Run after building the Debug Godot host through scripts/build-persistent-server.ps1.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from sts2_native_sim._scenario_driver import _first_mismatch
from sts2_native_sim.client import NativeWorker
from sts2_native_sim.scenarios import ScenarioRequest, generate_rows

SEEDS = ("A1B2C3D4E5", "1", "2", "3")


def compare_row(mode: str, seed: str, index: int, actual: dict, expected: dict) -> None:
    assert expected["record_type"] == "scenario", (mode, seed, index, expected)
    mismatch = _first_mismatch(expected["combat_initial_state"], actual["observation"])
    if mismatch or expected["state_hash"] != actual["state_hash"]:
        raise AssertionError((mode, seed, index, mismatch, expected["state_hash"], actual["state_hash"]))
    choice = actual["choice"]["parameters"]
    if {key: choice.get(key) for key in ("option_index", "relic_model_id")} != expected["recipe"]["ancient_choice"]:
        raise AssertionError((mode, seed, index, "ancient_choice"))
    node = actual["node"]["parameters"]
    if {key: node[key] for key in ("col", "row", "point_type")} != expected["recipe"]["node"]:
        raise AssertionError((mode, seed, index, "node"))


def reset_state(seed: str) -> dict:
    return {
        "game_build": {}, "seed": seed, "rng_counters": {}, "character": "IRONCLAD",
        "ascension": 0, "encounter": "first", "current_hp": 80, "max_hp": 80,
        "deck": [], "gold": 99, "use_character_starting_loadout": True, "reset_mode": "run",
    }


def fresh_main() -> None:
    reference: dict[str, list[dict]] = {}
    for mode in ("python", "native_full", "native_light"):
        started = time.perf_counter()
        worker = NativeWorker()
        startup = time.perf_counter() - started
        tick = time.perf_counter()
        phases: dict[str, float] = {}
        try:
            for seed in SEEDS:
                if mode == "python":
                    reference[seed] = generate_rows(ScenarioRequest(("IRONCLAD",), (0,), (seed,)), worker)
                else:
                    result = worker.request("generate_first_combat_scenarios_probe", {
                        "state": reset_state(seed), "light": mode == "native_light"})
                    assert len(result["rows"]) == len(reference[seed]) == 3
                    for index, (actual, expected) in enumerate(zip(result["rows"], reference[seed])):
                        compare_row(mode, seed, index, actual, expected)
                    for phase, milliseconds in result["phase_ms"].items():
                        phases[phase] = phases.get(phase, 0.0) + milliseconds
            seconds = time.perf_counter() - tick
        finally:
            worker.close()
        print(json.dumps({"mode": mode, "startup_s": startup, "generation_s": seconds,
                          "rows": 12, "phase_ms": phases}), flush=True)


def main() -> None:
    worker = NativeWorker()
    measurements: dict[str, list[float]] = {key: [] for key in ("python", "native_full", "native_light")}
    results = []
    try:
        for round_number in range(3):
            order = ("python", "native_full", "native_light") if round_number % 2 == 0 else (
                "native_light", "native_full", "python")
            reference: dict[str, list[dict]] = {}
            for mode in order:
                tick = time.perf_counter()
                for seed in SEEDS:
                    if mode == "python":
                        rows = generate_rows(ScenarioRequest(("IRONCLAD",), (0,), (seed,)), worker)
                        reference[seed] = rows
                    else:
                        result = worker.request("generate_first_combat_scenarios_probe", {
                            "state": reset_state(seed), "light": mode == "native_light"})
                        rows = result["rows"]
                        if seed in reference:
                            for index, (actual, expected) in enumerate(zip(rows, reference[seed])):
                                compare_row(mode, seed, index, actual, expected)
                        results.append({"round": round_number + 1, "mode": mode, "seed": seed,
                                        "rows": len(rows), "native_elapsed_ms": result["elapsed_ms"],
                                        "phase_ms": result["phase_ms"]})
                elapsed = time.perf_counter() - tick
                measurements[mode].append(elapsed)
                print(json.dumps({"round": round_number + 1, "mode": mode,
                                  "seconds": elapsed}), flush=True)
            # The alternate order can put native first; run a fresh reference comparison then.
            if round_number % 2:
                for seed in SEEDS:
                    expected = reference[seed]
                    for mode in ("native_full", "native_light"):
                        result = worker.request("generate_first_combat_scenarios_probe", {
                            "state": reset_state(seed), "light": mode == "native_light"})
                        for index, (actual, row) in enumerate(zip(result["rows"], expected)):
                            compare_row(mode, seed, index, actual, row)
    finally:
        worker.close()
    summary = {mode: {"median": statistics.median(times), "range": [min(times), max(times)]}
               for mode, times in measurements.items()}
    for mode in ("native_full", "native_light"):
        phase_rounds = []
        for round_number in range(1, 4):
            phases: dict[str, float] = {}
            for row in results:
                if row["round"] == round_number and row["mode"] == mode:
                    for phase, milliseconds in row["phase_ms"].items():
                        phases[phase] = phases.get(phase, 0.0) + milliseconds
            phase_rounds.append(phases)
        summary[mode]["phase_ms_median"] = {
            phase: statistics.median(round_phases.get(phase, 0.0) for round_phases in phase_rounds)
            for phase in phase_rounds[0]
        }
    print(json.dumps({"summary": summary, "details": results}, indent=2), flush=True)


if __name__ == "__main__":
    fresh_main() if sys.argv[1:] == ["--fresh"] else main()
