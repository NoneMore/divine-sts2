"""Research probe: where does the Ancient-entry restore spend time, and what does snapshot capture cost?

The original measurement showed that the Ancient-entry checkpoint rebuilt a run and its map.
The same fixed request now measures the snapshot restore. Pass ``--capture-steps`` to ask the
worker for the capture cost after every step; this adds diagnostic RPCs, so use a run without that
flag when comparing generation time. All timings live outside the corpus.

So the probe drives reference request A — the small request the diagnosis fixes — on one worker with
profiling on, and reports for every restore the wall time it took from the outside and where the
worker that ran it spent that time. The worker only times itself when it is started with
``STS2_RESTORE_PROFILE=1``; a restore that reports no profile is refused rather than counted as free.

Run it through the PowerShell layer, because ``python/sts2_native_sim/paths.py`` reads
``os.environ`` and only ``scripts/common.ps1`` loads the gitignored ``.env``:

    pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/experiments/scenario_restore_profile.py --out artifacts/scenario-performance/restore-profile.json'

The worker has to be rebuilt in the configuration the Godot host runs (Debug) before a change to the
restore path is visible to it, and the timing it reports is a wall-clock measurement of one call, so
it is written to a sidecar outside every corpus and never into a shard or a summary (ADR-0008).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from sts2_native_sim.client import NativeWorker  # noqa: E402
from sts2_native_sim.scenarios import ScenarioRequest, generate_rows  # noqa: E402

#: The switch the worker reads to time each restore. It is set in this process before a worker is
#: started, because the worker inherits its environment at spawn and reads the switch once.
PROFILE_ENVIRONMENT_VARIABLE = "STS2_RESTORE_PROFILE"

#: Reference request A: the small request whose restores the diagnosis counts, fixed here so this
#: probe and the recorded baseline measure the same workload.
REQUEST = ScenarioRequest(
    characters=("IRONCLAD",),
    ascensions=(0,),
    seeds=("A1B2C3D4E5", "1", "2", "3"),
)

#: The parts a restore's profile names, and the ones this probe attributes its time to. A part the
#: restore did not take is absent from the profile (the wire omits nulls), and the probe reads it as
#: zero, so one restore's shape is comparable with the next one's. `mode_init_ms` is the room a
#: non-run recipe rebuilds; the Ancient checkpoint is a run-mode checkpoint, so its own part is
#: `map_rebuild_ms`.
PARTS = (
    "resident_check_ms",
    "run_rebuild_ms",
    "map_rebuild_ms",
    "mode_init_ms",
    "replay_ms",
    "snapshot_ms",
    "capture_ms",
)


def attribute_restores(restores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Where a request's restores spent their time, and how many of them hit the resident prefix.

    Each entry is one restore RPC as the probe recorded it: the seconds the call took from the
    outside, and the transition the worker answered with. The answer counts the restores and their
    fast-path hits, totals each named part, and keeps apart two things a reader would otherwise
    blend: the time the worker spent restoring (its own profile) and the time the call took around
    it (transport, and the coordinator's own projection and hashing).

    A restore whose transition carries no profile is refused rather than attributed zero: a worker
    that was never asked to time itself has not measured a cheap restore, it has measured nothing.
    """
    if not restores:
        raise ValueError("no restore was recorded, so there is nothing to attribute")
    hits = 0
    parts = dict.fromkeys(PARTS, 0.0)
    unattributed_ms = 0.0
    worker_total_ms = 0.0
    rpc_seconds = 0.0
    per_restore: list[dict[str, Any]] = []
    for index, restore in enumerate(restores):
        transition = restore.get("transition") or {}
        profile = transition.get("profile")
        if not isinstance(profile, Mapping):
            raise ValueError(
                f"restore {index} reported no profile: the worker has to be started with "
                f"{PROFILE_ENVIRONMENT_VARIABLE}=1 for this measurement"
            )
        # The worker reports the hit beside the timing rather than inside it: on a hit there is no
        # part to name, because the check that found the state is the whole restore.
        hit = bool(transition.get("resident_prefix_hit"))
        hits += hit
        for part in PARTS:
            parts[part] += float(profile.get(part) or 0.0)
        unattributed_ms += float(profile.get("unattributed_ms") or 0.0)
        worker_total_ms += float(profile.get("total_ms") or 0.0)
        rpc_seconds += float(restore["seconds"])
        per_restore.append(
            {
                "seconds": round(float(restore["seconds"]), 6),
                "resident_prefix_hit": hit,
                **{part: profile.get(part) for part in PARTS},
                "total_ms": profile.get("total_ms"),
                "unattributed_ms": profile.get("unattributed_ms"),
                "replayed_actions": transition.get("replayed_actions"),
            }
        )
    return {
        "count": len(restores),
        "resident_prefix_hits": hits,
        "parts_ms": parts,
        "worker_total_ms": worker_total_ms,
        "unattributed_ms": unattributed_ms,
        "rpc_seconds": rpc_seconds,
        "outside_worker_ms": rpc_seconds * 1000.0 - worker_total_ms,
        "per_restore": per_restore,
    }


def measure_round(round_number: int, *, capture_steps: bool = False) -> dict[str, Any]:
    """Drive the request on one worker, timing every restore the generation performs from outside."""
    started = time.perf_counter()
    worker = NativeWorker()
    startup_seconds = time.perf_counter() - started
    restores: list[dict[str, Any]] = []
    step_capture_ms: list[float] = []
    original_request = worker.request

    def timed_request(method: str, params: dict[str, Any] | None = None) -> Any:
        tick = time.perf_counter()
        result = original_request(method, params)
        if method == "restore":
            restores.append(
                {
                    "seconds": time.perf_counter() - tick,
                    "transition": result.get("transition") or {},
                }
            )
        elif method == "run_step" and capture_steps:
            # The coordinator owns the step transition, so read the native environment's
            # measured capture cost through its diagnostic endpoint after the step.
            diagnostics = original_request("diagnostics")
            step_capture_ms.append(float(diagnostics.get("snapshot_capture_ms") or 0.0))
        return result

    worker.request = timed_request  # type: ignore[method-assign]
    try:
        tick = time.perf_counter()
        rows = generate_rows(REQUEST, worker)
        generation_seconds = time.perf_counter() - tick
    finally:
        worker.request = original_request  # type: ignore[method-assign]
        worker.close()

    return {
        "round": round_number,
        "startup_seconds": round(startup_seconds, 4),
        "generation_seconds": round(generation_seconds, 4),
        "rows": len(rows),
        "scenario_rows": sum(1 for row in rows if row.get("record_type") == "scenario"),
        "failure_rows": sum(1 for row in rows if row.get("record_type") == "failure"),
        "restores": restores,
        "step_snapshot_capture_ms": step_capture_ms,
        "snapshot_capture_total_ms": sum(step_capture_ms),
        "attribution": attribute_restores(restores),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--capture-steps", action="store_true",
                        help="read native snapshot capture timings after every step (adds diagnostic RPCs)")
    parser.add_argument("--out", type=Path, default=None)
    arguments = parser.parse_args()
    if arguments.rounds < 1:
        parser.error("rounds must be positive")

    # The worker is a child process that copies this environment at spawn, so profiling is asked for
    # before the first worker starts and every round of the probe measures the same thing.
    os.environ[PROFILE_ENVIRONMENT_VARIABLE] = "1"
    rounds = [measure_round(number, capture_steps=arguments.capture_steps)
              for number in range(1, arguments.rounds + 1)]
    report = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "request": {
            "characters": list(REQUEST.characters),
            "ascensions": list(REQUEST.ascensions),
            "seeds": list(REQUEST.seeds),
        },
        "rounds": rounds,
        "snapshot_capture_total_ms": sum(one_round["snapshot_capture_total_ms"] for one_round in rounds),
        "all_restores": attribute_restores(
            [restore for one_round in rounds for restore in one_round["restores"]]
        ),
    }
    body = json.dumps(report, indent=2, sort_keys=False)
    if arguments.out is None:
        print(body)
    else:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(body + "\n", encoding="utf-8")
        print(json.dumps({"result_file": str(arguments.out), "answer": report["all_restores"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
