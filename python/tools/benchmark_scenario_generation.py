"""Compare the native fork reference and handle reuse for scenario generation.

Usage: python python/tools/benchmark_scenario_generation.py <unique-run-id> [--rounds 3]
Every corpus measurement writes a fresh directory. Reusing an ID is refused so resume
cannot masquerade as full-generation throughput.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "tests" / "acceptance"))

from scenario_fork_reference import ForkAfterAncientWorker  # type: ignore[import-not-found]
from sts2_native_sim.client import NativeWorker
from sts2_native_sim.scenarios import ScenarioRequest, generate_corpus, generate_rows

SEEDS = ("A1B2C3D4E5", "1", "2", "3")
OUT = ROOT / "artifacts" / "scenario-performance"
MODES = ("fork_reference", "reuse_handle")
RPC_METHODS = ("run_reset", "restore", "run_step", "fork")


def _driver(worker: NativeWorker, mode: str) -> NativeWorker | ForkAfterAncientWorker:
    return ForkAfterAncientWorker(worker) if mode == "fork_reference" else worker


def timed_rows(mode: str, round_number: int) -> dict[str, Any]:
    started = time.perf_counter()
    worker = NativeWorker()
    startup = time.perf_counter() - started
    original_request = worker.request
    calls: dict[str, list[float]] = defaultdict(list)

    def timed_request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        tick = time.perf_counter()
        try:
            return original_request(method, params)
        finally:
            calls[method].append(time.perf_counter() - tick)

    worker.request = timed_request  # type: ignore[method-assign]
    samples: list[dict[str, Any]] = []
    try:
        driver = _driver(worker, mode)
        for seed in SEEDS:
            request = ScenarioRequest(("IRONCLAD",), (0,), (seed,))
            tick = time.perf_counter()
            rows = generate_rows(request, driver)
            samples.append({
                "seed": seed,
                "seconds": time.perf_counter() - tick,
                "rows": len(rows),
                "succeeded": sum(row["record_type"] == "scenario" for row in rows),
            })
    finally:
        worker.request = original_request  # type: ignore[method-assign]
        tick = time.perf_counter()
        worker.close()
        shutdown = time.perf_counter() - tick

    seconds = sum(sample["seconds"] for sample in samples)
    rows = sum(sample["rows"] for sample in samples)
    return {
        "mode": mode,
        "round": round_number,
        "game_build": worker.build,
        "startup_seconds": startup,
        "shutdown_seconds": shutdown,
        "generation_seconds": seconds,
        "rows": rows,
        "succeeded": sum(sample["succeeded"] for sample in samples),
        "rows_per_second": rows / seconds,
        "samples": samples,
        "rpc": {method: {"count": len(calls[method]), "seconds": sum(calls[method])} for method in RPC_METHODS},
    }


def timed_corpus(mode: str, workers: int, run_id: str, round_number: int) -> dict[str, Any]:
    root = OUT / f"corpus-{workers}-{mode}-{run_id}-r{round_number}"
    if root.exists():
        raise FileExistsError(f"{root} exists; use a fresh run ID so resume cannot affect the benchmark")
    request = ScenarioRequest(("IRONCLAD",), (0,), SEEDS)
    factory = lambda _shard: _driver(NativeWorker(), mode)
    tick = time.perf_counter()
    summary = generate_corpus(request, workers, root, worker_factory=factory)
    elapsed = time.perf_counter() - tick
    rows = summary["succeeded"] + summary["failed"]
    return {
        "mode": mode,
        "round": round_number,
        "workers": workers,
        "wall_seconds": elapsed,
        "rows": rows,
        "succeeded": summary["succeeded"],
        "failed": summary["failed"],
        "rows_per_second": rows / elapsed,
        "worker_replacements": summary["worker_replacements"],
        "shard_bytes": sum(path.stat().st_size for path in root.glob("worker-*.jsonl.gz")),
    }


def _assert_corpus_bytes_equal(workers: int, run_id: str, round_number: int) -> None:
    roots = [OUT / f"corpus-{workers}-{mode}-{run_id}-r{round_number}" for mode in MODES]
    old_files = {path.name: path.read_bytes() for path in roots[0].iterdir() if path.is_file()}
    new_files = {path.name: path.read_bytes() for path in roots[1].iterdir() if path.is_file()}
    if old_files != new_files:
        raise AssertionError(f"round {round_number}, {workers} workers: native corpus bytes differ")


def _median(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def _summarize(report: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"rows": {}, "corpora": {}}
    for mode in MODES:
        measurements = [item for item in report["rows"] if item["mode"] == mode]
        summary["rows"][mode] = {
            "generation_seconds": _median([item["generation_seconds"] for item in measurements]),
            "rows_per_second": _median([item["rows_per_second"] for item in measurements]),
            "rpc": {
                method: {
                    "count": measurements[0]["rpc"][method]["count"],
                    "seconds": _median([item["rpc"][method]["seconds"] for item in measurements]),
                }
                for method in RPC_METHODS
            },
        }
        summary["corpora"][mode] = {}
        for workers in (1, 2, 4):
            measured = [item for item in report["corpora"] if item["mode"] == mode and item["workers"] == workers]
            summary["corpora"][mode][str(workers)] = {
                "wall_seconds": _median([item["wall_seconds"] for item in measured]),
                "rows_per_second": _median([item["rows_per_second"] for item in measured]),
            }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="unique alphanumeric label for fresh corpus directories")
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum() or args.rounds < 1:
        parser.error("run_id must be alphanumeric and rounds must be positive")
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / f"results-{args.run_id}.json"
    if output.exists():
        raise FileExistsError(f"{output} exists; use a fresh run ID")

    report: dict[str, Any] = {"request": {"character": "IRONCLAD", "ascension": 0, "seeds": SEEDS},
                              "rounds": args.rounds, "rows": [], "corpora": []}
    for round_number in range(1, args.rounds + 1):
        order = MODES if round_number % 2 else tuple(reversed(MODES))
        for mode in order:
            result = timed_rows(mode, round_number)
            report["rows"].append(result)
            print(json.dumps({"kind": "rows", **result}), flush=True)
        for workers in (1, 2, 4):
            for mode in order:
                result = timed_corpus(mode, workers, args.run_id, round_number)
                report["corpora"].append(result)
                print(json.dumps({"kind": "corpus", **result}), flush=True)
            _assert_corpus_bytes_equal(workers, args.run_id, round_number)
            print(json.dumps({"kind": "corpus_differential", "round": round_number,
                              "workers": workers, "byte_identical": True}), flush=True)
    report["summary"] = _summarize(report)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"result_file": str(output), "summary": report["summary"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
