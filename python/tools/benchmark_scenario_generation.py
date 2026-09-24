"""Measure first-combat scenario generation and fresh corpus creation.

Usage: python python/tools/benchmark_scenario_generation.py <unique-run-id>
Each run ID creates fresh corpus directories. Reusing an ID resumes those corpora
and therefore does not measure full generation.
"""

import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from sts2_native_sim.client import NativeWorker  # noqa: E402
from sts2_native_sim.scenarios import ScenarioRequest, generate_corpus, generate_rows  # noqa: E402


SEEDS = ("A1B2C3D4E5", "1", "2", "3")
OUT = ROOT / "artifacts" / "scenario-performance"


def timed_rows():
    started = time.perf_counter()
    worker = NativeWorker()
    startup = time.perf_counter() - started
    original_request = worker.request
    calls = defaultdict(list)

    def timed_request(method, params=None):
        tick = time.perf_counter()
        try:
            return original_request(method, params)
        finally:
            calls[method].append(time.perf_counter() - tick)

    worker.request = timed_request
    samples = []
    try:
        for seed in SEEDS:
            request = ScenarioRequest(("IRONCLAD",), (0,), (seed,))
            before = {name: len(values) for name, values in calls.items()}
            tick = time.perf_counter()
            rows = generate_rows(request, worker)
            duration = time.perf_counter() - tick
            per_method = {
                name: {"count": len(values[before.get(name, 0):]),
                       "seconds": sum(values[before.get(name, 0):])}
                for name, values in calls.items()
                if len(values) > before.get(name, 0)
            }
            samples.append({"seed": seed, "seconds": duration,
                            "rows": len(rows),
                            "succeeded": sum(row["record_type"] == "scenario" for row in rows),
                            "methods": per_method})
    finally:
        tick = time.perf_counter()
        worker.close()
        shutdown = time.perf_counter() - tick
    return {"startup_seconds": startup, "shutdown_seconds": shutdown,
            "samples": samples,
            "mean_seconds_per_element": statistics.mean(sample["seconds"] for sample in samples),
            "total_seconds": sum(sample["seconds"] for sample in samples),
            "total_scenarios": sum(sample["succeeded"] for sample in samples)}


def timed_corpus(workers, label):
    root = OUT / label
    request = ScenarioRequest(("IRONCLAD",), (0,), SEEDS)
    tick = time.perf_counter()
    summary = generate_corpus(request, workers, root)
    elapsed = time.perf_counter() - tick
    return {"workers": workers, "wall_seconds": elapsed,
            "succeeded": summary["succeeded"], "failed": summary["failed"],
            "worker_replacements": summary["worker_replacements"],
            "shard_bytes": sum(path.stat().st_size for path in root.glob("worker-*.jsonl.gz"))}


def main():
    if len(sys.argv) != 2 or not sys.argv[1].replace("-", "").replace("_", "").isalnum():
        raise SystemExit("usage: benchmark_scenario_generation.py <unique-run-id>")
    OUT.mkdir(parents=True, exist_ok=True)
    run_id = sys.argv[1]
    report = {"rows": timed_rows(), "corpora": []}
    print(json.dumps(report, indent=2), flush=True)
    for workers, label in ((1, "corpus-1"), (2, "corpus-2"), (4, "corpus-4")):
        result = timed_corpus(workers, f"{label}-{run_id}")
        report["corpora"].append(result)
        print(json.dumps(result), flush=True)
    (OUT / f"results-{run_id}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
