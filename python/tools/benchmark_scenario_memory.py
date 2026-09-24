"""Measure live native scenario workers on this host.

Usage: python python/tools/benchmark_scenario_memory.py
The report is written to artifacts/scenario-performance/memory-<timestamp>.json.
"""

from __future__ import annotations

import json
import argparse
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from sts2_native_sim.client import NativeWorker
from sts2_native_sim.scenarios import ScenarioRequest, generate_rows

MIB = 1024 * 1024
COUNTS = (1, 4, 8)
SEEDS_PER_WORKER = 4


def memory(pid: int) -> dict[str, float]:
    info = psutil.Process(pid).memory_info()
    return {"private_mib": round(info.private / MIB, 2), "working_set_mib": round(info.rss / MIB, 2)}


def tree_memory(pid: int) -> dict[str, float]:
    process = psutil.Process(pid)
    processes = [process, *process.children(recursive=True)]
    values = [memory(child.pid) for child in processes if child.is_running()]
    return {key: round(sum(value[key] for value in values), 2)
            for key in ("private_mib", "working_set_mib")}


def summarize(values: list[float]) -> dict[str, float]:
    return {"min": min(values), "median": statistics.median(values), "max": max(values)}


def run(count: int) -> dict[str, object]:
    workers: list[NativeWorker] = []
    lock = threading.Lock()
    stop = threading.Event()
    peak = {"worker_private_mib": 0.0, "worker_working_set_mib": 0.0,
            "total_private_mib": 0.0}
    parent = psutil.Process()

    def sample() -> None:
        while not stop.is_set():
            try:
                children = [p for p in parent.children(recursive=True) if p.is_running()]
                infos = [memory(p.pid) for p in children]
                private = sum(m["private_mib"] for m in infos)
                working_set = sum(m["working_set_mib"] for m in infos)
                peak["worker_private_mib"] = max(peak["worker_private_mib"], private)
                peak["worker_working_set_mib"] = max(peak["worker_working_set_mib"], working_set)
                peak["total_private_mib"] = max(
                    peak["total_private_mib"], private + memory(parent.pid)["private_mib"]
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            stop.wait(0.05)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        startup = time.perf_counter()

        def start(_: int) -> NativeWorker:
            worker = NativeWorker()
            with lock:
                workers.append(worker)
            return worker

        with ThreadPoolExecutor(max_workers=count) as pool:
            ready_workers = list(pool.map(start, range(count)))
        startup_seconds = time.perf_counter() - startup
        ready = [tree_memory(worker.process.pid) for worker in ready_workers]

        def generate(item: tuple[int, NativeWorker]) -> int:
            index, worker = item
            rows = 0
            for offset in range(SEEDS_PER_WORKER):
                seed = str(100000 + index * SEEDS_PER_WORKER + offset)
                result = generate_rows(ScenarioRequest(("IRONCLAD",), (0,), (seed,)), worker)
                if any(row["record_type"] != "scenario" for row in result):
                    raise RuntimeError(f"worker {index}, seed {seed}: {result}")
                rows += len(result)
            return rows

        generation = time.perf_counter()
        with ThreadPoolExecutor(max_workers=count) as pool:
            row_counts = list(pool.map(generate, enumerate(ready_workers)))
        generation_seconds = time.perf_counter() - generation
        after = [tree_memory(worker.process.pid) for worker in ready_workers]
        return {
            "workers": count,
            "seeds_per_worker": SEEDS_PER_WORKER,
            "rows": sum(row_counts),
            "startup_seconds": round(startup_seconds, 3),
            "generation_seconds": round(generation_seconds, 3),
            "ready_private_mib": summarize([m["private_mib"] for m in ready]),
            "ready_working_set_mib": summarize([m["working_set_mib"] for m in ready]),
            "after_private_mib": summarize([m["private_mib"] for m in after]),
            "after_working_set_mib": summarize([m["working_set_mib"] for m in after]),
            "after_worker_private_mib": round(sum(m["private_mib"] for m in after), 2),
            "after_worker_working_set_mib": round(sum(m["working_set_mib"] for m in after), 2),
            "python_private_mib_after": memory(parent.pid)["private_mib"],
            "python_working_set_mib_after": memory(parent.pid)["working_set_mib"],
            "peak_sampled_mib": peak,
        }
    finally:
        stop.set()
        sampler.join(timeout=1)
        for worker in workers:
            worker.close()


def run_long(elements: int) -> dict[str, object]:
    checkpoints: list[dict[str, object]] = []
    outcome: dict[str, object] = {"checkpoints": checkpoints}
    worker = NativeWorker()
    try:
        for index in range(elements + 1):
            if index:
                rows = generate_rows(
                    ScenarioRequest(("IRONCLAD",), (0,), (str(200000 + index),)), worker
                )
                failures = [row for row in rows if row["record_type"] != "scenario"]
                if failures:
                    outcome["failure"] = {"element": index, "seed": str(200000 + index),
                                          "rows": [{"record_type": row["record_type"],
                                                    "stage": row.get("stage"), "error": row.get("error")}
                                                   for row in rows],
                                          "worker": tree_memory(worker.process.pid)
                                          if worker.alive() else None}
                    break
            if index in (0, 1, 4, 16, 64, 128, 256, 512, elements):
                checkpoints.append({"elements": index, "worker": tree_memory(worker.process.pid),
                                    "python": memory(psutil.Process().pid),
                                    "python_handle_count": len(worker._handle_histories),
                                    "native_diagnostics": worker.diagnostics()})
    finally:
        try:
            worker.close()
        except Exception as error:
            outcome["close_error"] = str(error)
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long", action="store_true", help="sample one worker through --long-elements")
    parser.add_argument("--long-elements", type=int, default=128)
    parser.add_argument("--probe-seed", help="print concise result for one seed")
    parser.add_argument("--counts", type=int, nargs="+", default=COUNTS,
                        help="worker counts for the concurrent run")
    args = parser.parse_args()
    report = {
        "measured_utc": datetime.now(timezone.utc).isoformat(),
        "logical_cores": psutil.cpu_count(),
        "physical_cores": psutil.cpu_count(logical=False),
        "system_memory_gib": round(psutil.virtual_memory().total / (1024 ** 3), 2),
        "python_private_mib_before": memory(psutil.Process().pid)["private_mib"],
        "python_working_set_mib_before": memory(psutil.Process().pid)["working_set_mib"],
        "runs": [],
    }
    if args.probe_seed:
        worker = NativeWorker()
        try:
            rows = generate_rows(ScenarioRequest(("IRONCLAD",), (0,), (args.probe_seed,)), worker)
            print(json.dumps({"seed": args.probe_seed, "rows": [
                {"record_type": row["record_type"], "stage": row.get("stage"),
                 "error": row.get("error")} for row in rows], "alive": worker.alive()}), flush=True)
        finally:
            try:
                worker.close()
            except Exception as error:
                print(json.dumps({"close_error": str(error)}), flush=True)
        return
    if args.long:
        report["long_run"] = run_long(args.long_elements)
        print(json.dumps(report["long_run"]), flush=True)
    else:
        for count in args.counts:
            result = run(count)
            report["runs"].append(result)
            print(json.dumps(result), flush=True)
    output = ROOT / "artifacts" / "scenario-performance" / (
        f"memory-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output)}), flush=True)


if __name__ == "__main__":
    main()
