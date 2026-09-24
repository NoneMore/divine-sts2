"""Evidence policy and compact trust record for full-app reuse certification."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _clean_initial_history(row: dict[str, Any]) -> bool:
    history = row.get("initial_history")
    initial_hash = row.get("initial_state_hash")
    return bool(initial_hash) and isinstance(history, dict) and history.get("actions") == [] and history.get(
        "state_hashes"
    ) == [initial_hash]


def evaluate(
    fresh: list[dict[str, Any]], reused: list[dict[str, Any]], build: dict[str, Any],
    profile_at_readiness: dict[str, Any], profile_after_sentinel: dict[str, Any],
) -> dict[str, Any]:
    """Compare complete fresh evidence with seventeen entries from one reusable process."""
    failures: list[str] = []
    comparisons: list[dict[str, Any]] = []
    if len(fresh) != 16 or len(reused) != 17:
        failures.append(f"expected 16 fresh and 17 reused entries; got {len(fresh)} and {len(reused)}")
    fresh_pids = [row.get("pid") for row in fresh]
    if len(fresh_pids) != 16 or any(type(pid) is not int for pid in fresh_pids) or len(set(fresh_pids)) != 16:
        failures.append("fresh entries did not use sixteen independent processes")
    reuse_pids = {row.get("pid") for row in reused}
    replacements = [row.get("replacement_count") for row in reused]
    processes_started = max((count for count in replacements if type(count) is int), default=-1) + 1
    if len(reuse_pids) != 1 or not all(type(pid) is int for pid in reuse_pids) or processes_started != 1:
        failures.append("reused entries did not remain in one process without replacement")
    if sum(row.get("pck_fingerprint_count", 0) for row in reused) != 1 or sum(
        row.get("pck_fingerprint_bytes", 0) for row in reused
    ) <= 0:
        failures.append("reused process did not fingerprint the PCK exactly once")
    baseline = profile_at_readiness.get("in_memory")
    if not isinstance(baseline, str) or len(baseline) != 64 or any(
        profile.get(side) != baseline
        for profile in (profile_at_readiness, profile_after_sentinel)
        for side in ("in_memory", "persisted")
    ):
        failures.append("persisted or in-memory progression-complete profile drifted")

    for index, reused_row in enumerate(reused):
        source = fresh[index if index < 16 else 0] if len(fresh) > (index if index < 16 else 0) else {}
        label = reused_row.get("label", f"entry {index + 1}")
        differences: list[str] = []
        if reused_row.get("label") != source.get("label"):
            differences.append("scenario")
        for field in ("matched", "projection", "boundary_trace", "game_build"):
            if reused_row.get(field) != source.get(field):
                differences.append(field)
        if not isinstance(source.get("projection"), dict) or not isinstance(reused_row.get("projection"), dict):
            differences.append("missing full projection")
        if not isinstance(source.get("boundary_trace"), list) or not source["boundary_trace"] or not isinstance(
            reused_row.get("boundary_trace"), list
        ) or not reused_row["boundary_trace"]:
            differences.append("missing legal boundary trace")
        if not source.get("matched") or not reused_row.get("matched"):
            differences.append("entry failure")
        if source.get("game_build") != build or reused_row.get("game_build") != build:
            differences.append("game build")
        if not _clean_initial_history(reused_row):
            differences.append("initial history ownership")
        if not _clean_initial_history(source):
            differences.append("fresh initial history")
        if reused_row.get("process_mode") != "reuse" or reused_row.get("process_entry_ordinal") != index + 1:
            differences.append("lifecycle ordinal or mode")
        if reused_row.get("start_path") != ("menu" if index == 0 else "direct") or reused_row.get(
            "warm"
        ) is not (index > 0):
            differences.append("start path")
        if reused_row.get("replacement_count") != 0:
            differences.append("replacement")
        teardown = reused_row.get("teardown")
        if not isinstance(teardown, dict) or any((
            teardown.get("final_state") != "idle",
            teardown.get("driver_result") not in ("abandoned", "cancelled"),
            teardown.get("parked_wait_released") is not True,
            type(teardown.get("ended_generation")) is not int,
            not isinstance(teardown.get("reset_history_counts"), dict),
            not isinstance(teardown.get("ending_phase"), str),
            type(teardown.get("stale_continuation_refusals")) is not int,
            type(teardown.get("duration_ms")) is not int,
            not isinstance(teardown.get("reset_history_counts"), dict) or not all(
                type(teardown["reset_history_counts"].get(key)) is int
                and teardown["reset_history_counts"][key] >= 0 for key in ("actions", "state_hashes")
            ),
        )):
            differences.append("teardown evidence")
        elif index and teardown["ended_generation"] <= (reused[index - 1].get("teardown") or {}).get("ended_generation", 0):
            differences.append("teardown generation")
        if not all(isinstance(reused_row.get(field), (int, float)) and reused_row[field] >= 0 for field in (
            "startup_seconds", "entry_seconds", "teardown_seconds"
        )):
            differences.append("lifecycle timings")
        comparisons.append({"entry": index + 1, "label": label, "equivalent": not differences,
                            "differences": differences})
        failures.extend(f"{label}: {difference}" for difference in differences)
    for index, row in enumerate(fresh):
        if row.get("process_mode") != "fresh" or row.get("start_path") != "menu":
            failures.append(f"fresh entry {index + 1} lacked menu-start provenance")
    return {"success": not failures, "failures": failures, "comparisons": comparisons,
            "processes_started": processes_started, "fresh_processes_started": len(set(fresh_pids)),
            "profile_at_readiness": profile_at_readiness, "profile_after_sentinel": profile_after_sentinel}


def issue_certificate(report: dict[str, Any], report_path: Path, certificate_path: Path) -> dict[str, Any]:
    """Persist complete evidence first; publish a compact certificate only for a successful gate."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(payload)
    if not report.get("success"):
        raise ValueError("Certification evidence failed; no certificate was written")
    required = ("fresh", "reused", "game_build", "profile_at_readiness", "profile_after_sentinel",
                "profile_baseline", "identity", "comparisons", "failures")
    if any(key not in report for key in required) or not isinstance(report["fresh"], list) or not isinstance(
        report["reused"], list
    ) or not all(isinstance(row, dict) for row in (*report["fresh"], *report["reused"])) or not all(
        isinstance(report[key], dict) for key in ("game_build", "profile_at_readiness", "profile_after_sentinel", "identity")
    ):
        raise ValueError("Certification evidence is incomplete; no certificate was written")
    checked = evaluate(report["fresh"], report["reused"], report["game_build"],
                       report["profile_at_readiness"], report["profile_after_sentinel"])
    identity = report["identity"]
    if (
        not checked["success"] or report["failures"] != [] or report["comparisons"] != checked["comparisons"]
        or report.get("processes_started") != checked["processes_started"]
        or report.get("fresh_processes_started") != checked["fresh_processes_started"]
        or report["profile_baseline"] != report["profile_at_readiness"].get("in_memory")
        or any(identity.get(field) != report["game_build"].get(field) or not isinstance(identity.get(field), str)
               or len(identity[field]) != 64 for field in ("assembly_sha256", "pck_sha256"))
        or any(not isinstance(identity.get(field), str) or not identity[field] for field in (
            "lifecycle_protocol_revision", "profile_policy_revision", "scenario_set_revision"
        ))
    ):
        raise ValueError("Certification evidence is incomplete or inconsistent; no certificate was written")
    certificate = {
        "identity": identity,
        "passed_at_utc": datetime.now(UTC).isoformat(),
        "report_sha256": hashlib.sha256(payload).hexdigest(),
    }
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    certificate_path.write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return certificate
