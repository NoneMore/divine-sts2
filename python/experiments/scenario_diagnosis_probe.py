"""Throwaway research probe: where a scenario generation element's time goes at request scale.

Not a maintained tool. It measures the two things the recorded baselines under ``docs/research/``
do not: how one worker's per-element wall time drifts across a long shard, and what the per-worker
PCK fingerprint costs when it is shared with the worker instead of recomputed by it.

Run it through the PowerShell layer, because ``python/sts2_native_sim/paths.py`` reads
``os.environ`` and only ``scripts/common.ps1`` loads the gitignored ``.env``:

    pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/experiments/scenario_diagnosis_probe.py --elements 64 --out artifacts/scenario-performance/diag-probe.json'
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from sts2_native_sim import paths  # noqa: E402
from sts2_native_sim.client import NativeWorker  # noqa: E402
from sts2_native_sim.pck_fingerprint import PckFingerprint  # noqa: E402
from sts2_native_sim.scenarios import ScenarioRequest, generate_rows  # noqa: E402

#: Two characters and two Ascensions, so a run of elements spans both act-1 variants.
CHARACTERS = ("IRONCLAD", "DEFECT")
ASCENSIONS = (0, 2)


def element_loop(elements: int, seeds_per_chunk: int) -> dict[str, Any]:
    """Drive ``elements`` elements on one worker, timing every Ancient-bearing step through the RPC.

    The request is split into chunks of whole seeds so that the public ``generate_rows`` interface
    is enough to see drift: each chunk is one call, and the chunks share one worker.
    """
    per_seed = len(CHARACTERS) * len(ASCENSIONS)
    seeds = [str(index) for index in range(1, -(-elements // per_seed) + 1)]

    started = time.perf_counter()
    worker = NativeWorker()
    startup_seconds = time.perf_counter() - started

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    original_request = worker.request

    def timed_request(method: str, params: dict[str, Any] | None = None) -> Any:
        tick = time.perf_counter()
        try:
            return original_request(method, params)
        finally:
            elapsed = time.perf_counter() - tick
            totals[method] = totals.get(method, 0.0) + elapsed
            counts[method] = counts.get(method, 0) + 1

    worker.request = timed_request  # type: ignore[method-assign]

    per_chunk: list[dict[str, Any]] = []
    successes = 0
    failures = 0
    rows_total = 0
    generation_started = time.perf_counter()
    for begin in range(0, len(seeds), seeds_per_chunk):
        window = seeds[begin : begin + seeds_per_chunk]
        request = ScenarioRequest(CHARACTERS, ASCENSIONS, tuple(window))
        tick = time.perf_counter()
        rows = generate_rows(request, worker)
        elapsed = time.perf_counter() - tick
        for row in rows:
            rows_total += 1
            if row.get("record_type") == "failure":
                failures += 1
            else:
                successes += 1
        per_chunk.append(
            {
                "seeds": list(window),
                "elements": len(window) * per_seed,
                "rows": len(rows),
                "seconds": round(elapsed, 4),
            }
        )
    generation_seconds = time.perf_counter() - generation_started
    alive = worker.alive()
    worker.close()

    elements_done = sum(entry["elements"] for entry in per_chunk)
    return {
        "worker_startup_seconds": round(startup_seconds, 4),
        "elements": elements_done,
        "rows": rows_total,
        "successes": successes,
        "failures": failures,
        "worker_alive_after": alive,
        "generation_seconds": round(generation_seconds, 4),
        "elements_per_second": round(elements_done / generation_seconds, 4),
        "rows_per_second": round(rows_total / generation_seconds, 4),
        "seconds_per_element": round(generation_seconds / elements_done, 4),
        "rpc_seconds": {key: round(value, 4) for key, value in sorted(totals.items())},
        "rpc_counts": dict(sorted(counts.items())),
        "rpc_share_of_generation": {
            key: round(value / generation_seconds, 4) for key, value in sorted(totals.items())
        },
        "per_chunk": per_chunk,
        "first_chunk_seconds": per_chunk[0]["seconds"] if per_chunk else None,
        "last_chunk_seconds": per_chunk[-1]["seconds"] if per_chunk else None,
    }


def pck_hint_comparison() -> dict[str, Any]:
    """Start one worker whose PCK digest is handed to it, and one that must compute its own."""
    report: dict[str, Any] = {}
    try:
        pck = paths.find_game_assembly().resolve().parent.parent / "SlayTheSpire2.pck"
        tick = time.perf_counter()
        fingerprint = PckFingerprint.measure(pck)
        report["parent_measure_seconds"] = round(time.perf_counter() - tick, 4)
        report["parent_measure_reported_seconds"] = round(fingerprint.seconds, 4)
        report["is_current"] = fingerprint.is_current()

        tick = time.perf_counter()
        hinted = NativeWorker(pck_fingerprint=fingerprint)
        report["hinted_startup_seconds"] = round(time.perf_counter() - tick, 4)
        report["hinted_hello_fingerprint"] = hinted.pck_fingerprint
        hinted.close()

        tick = time.perf_counter()
        plain = NativeWorker()
        report["plain_startup_seconds"] = round(time.perf_counter() - tick, 4)
        report["plain_hello_fingerprint"] = plain.pck_fingerprint
        plain.close()
    except Exception as error:  # a probe must not lose its other measurement
        report["error"] = f"{type(error).__name__}: {error}"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elements", type=int, default=64)
    parser.add_argument("--seeds-per-chunk", type=int, default=2)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--skip-pck", action="store_true")
    arguments = parser.parse_args()

    report = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elements_requested": arguments.elements,
        "characters": list(CHARACTERS),
        "ascensions": list(ASCENSIONS),
        "seeds_per_chunk": arguments.seeds_per_chunk,
        "request_timeout_seconds": None,
        "element_loop": element_loop(arguments.elements, arguments.seeds_per_chunk),
        "pck_hint": None if arguments.skip_pck else pck_hint_comparison(),
    }
    body = json.dumps(report, indent=2, sort_keys=False)
    print(body)
    if arguments.out is not None:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(body + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
