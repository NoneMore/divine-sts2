#!/usr/bin/env python3
"""Certify sixteen fresh menu starts against seventeen entries in one reusable shipped game."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path
from typing import Any

from sts2_native_sim import NativeWorkerPool
from sts2_native_sim.full_app_client import FullAppClientConfig
from sts2_native_sim.reusable_full_app_worker import ReusableFullAppWorker
from sts2_native_sim.reuse_certification import evaluate, issue_certificate

from tests.acceptance.parity_run_acceptance import (
    SAMPLE,
    SCENARIO_SET_REVISION,
    _records,
    _reuse_candidate_result,
    _sample_result,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--worker-id", type=int,
                        help="first sandbox ID; by default the gate allocates new isolated sandboxes")
    parser.add_argument("--report", type=Path, default=Path("artifacts/reuse-certification/report.json"))
    parser.add_argument("--certificate", type=Path, default=Path("certifications/full-app-reuse.json"))
    parser.add_argument("--dump", type=Path)
    args = parser.parse_args(argv)
    first_worker_id = args.worker_id if args.worker_id is not None else 1_000_000_000_000 + secrets.randbelow(1_000_000_000_000)

    fresh: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    build: dict[str, Any] = {}
    at_readiness: dict[str, Any] = {}
    after_sentinel: dict[str, Any] = {}
    lifecycle_revision: str | None = None
    profile_revision: str | None = None
    baseline_fingerprint: str | None = None
    error: str | None = None
    try:
        with NativeWorkerPool(args.workers) as pool:
            runs = _records(pool, SAMPLE)
            build = pool.workers[0].build
            for index, sample in enumerate(SAMPLE):
                print(f"fresh {index + 1}/16 {sample.label}", flush=True)
                fresh.append(_sample_result(sample, runs, first_worker_id + index, args.dump, certify=True))
            config = FullAppClientConfig(worker_id=first_worker_id + 16, process_mode="reuse")
            with ReusableFullAppWorker(config, max_entries=17, capture_profile=True) as worker:
                for index, sample in enumerate((*SAMPLE, SAMPLE[0])):
                    print(f"reuse {index + 1}/17 {sample.label}", flush=True)
                    final_snapshot = (lambda client: after_sentinel.update(client.call("profile_snapshot"))) \
                        if index == 16 else None
                    reused.append(_reuse_candidate_result(
                        sample, runs, worker, args.dump, certify=True, after_teardown=final_snapshot,
                    ))
                at_readiness = worker.profile_at_readiness or {}
                lifecycle_revision = worker.lifecycle_protocol_revision
                profile_revision = worker.progression_policy_revision
                baseline_fingerprint = worker.profile_baseline
                if worker.game_build != build:
                    error = "reused worker game build differs from the fresh oracle"
    except Exception as exc:  # noqa: BLE001 - preserve partial evidence, never certify an interrupted gate
        error = f"{type(exc).__name__}: {exc}"

    outcome = evaluate(fresh, reused, build, at_readiness, after_sentinel)
    if error:
        outcome["failures"].append(error)
    if not lifecycle_revision or not profile_revision:
        outcome["failures"].append("missing lifecycle or profile-policy revision")
    if at_readiness.get("in_memory") != baseline_fingerprint:
        outcome["failures"].append("readiness profile differs from the progression-complete baseline")
    outcome["success"] = not outcome["failures"]
    identity = {
        "assembly_sha256": build.get("assembly_sha256"),
        "pck_sha256": build.get("pck_sha256"),
        "lifecycle_protocol_revision": lifecycle_revision,
        "profile_policy_revision": profile_revision,
        "scenario_set_revision": SCENARIO_SET_REVISION,
    }
    if any(not isinstance(value, str) or not value for value in identity.values()):
        outcome["failures"].append("incomplete certification identity")
        outcome["success"] = False
    complete_report = {**outcome, "identity": identity, "game_build": build,
                       "fresh": fresh, "reused": reused, "profile_baseline": baseline_fingerprint}
    try:
        certificate = issue_certificate(complete_report, args.report, args.certificate)
    except ValueError:
        print(json.dumps({"success": False, "failure_count": len(outcome["failures"]),
                          "failures": outcome["failures"][:20],
                          "report": str(args.report)}, indent=2), flush=True)
        return 1
    print(json.dumps({"success": True, "certificate": certificate,
                      "report": str(args.report)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
