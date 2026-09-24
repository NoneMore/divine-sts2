"""Evidence policy and compact trust record for full-app reuse certification."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .full_app_client import protocol_package_dir
from .paths import REPOSITORY_ROOT

IDENTITY_FIELDS = ("assembly_sha256", "pck_sha256", "lifecycle_protocol_revision",
                   "profile_policy_revision", "scenario_set_revision")


class CertificationError(ValueError):
    """The requested reuse identity has no valid certification."""


def current_certification_identity(build: dict[str, Any], scenario_set_revision: str) -> dict[str, str]:
    """Read the contract revisions declared by the bridge and bind them to the current game."""
    declarations = (
        ("lifecycle_protocol_revision", "Sts2.NativeSim.Protocol/FullAppBridgeHandshake.cs",
         "LifecycleProtocolRevision"),
        ("profile_policy_revision", "Sts2.NativeSim.Protocol/ProgressionCompletePolicy.cs", "Revision"),
    )
    assembly, pck = build.get("assembly_sha256"), build.get("pck_sha256")
    if not isinstance(assembly, str) or not isinstance(pck, str):
        raise CertificationError("Current game build identity is incomplete; reuse cannot be authorized.")
    identity = {"assembly_sha256": assembly, "pck_sha256": pck,
                "scenario_set_revision": scenario_set_revision}
    for field, source, name in declarations:
        try:
            contents = (REPOSITORY_ROOT / "src" / source).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise CertificationError(f"Cannot read current {field}; reuse cannot be authorized.") from error
        matches = re.findall(rf'\bconst\s+string\s+{name}\s*=\s*"([^"]+)"\s*;', contents)
        if len(matches) != 1:
            raise CertificationError(f"Cannot determine current {field}; reuse cannot be authorized.")
        identity[field] = matches[0]
    script = (
        '$ErrorActionPreference = "Stop"; '
        '$assembly = [Reflection.Assembly]::LoadFrom($args[0]); '
        '$lifecycle = $assembly.GetType("Sts2.NativeSim.Protocol.FullAppBridgeHandshake")'
        '.GetField("LifecycleProtocolRevision").GetRawConstantValue(); '
        '$profile = $assembly.GetType("Sts2.NativeSim.Protocol.ProgressionCompletePolicy")'
        '.GetField("Revision").GetRawConstantValue(); '
        '@{ lifecycle_protocol_revision = $lifecycle; profile_policy_revision = $profile } '
        '| ConvertTo-Json -Compress'
    )
    try:
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-CommandWithArgs", script,
             str(protocol_package_dir() / "Sts2.NativeSim.Protocol.dll")],
            check=True, capture_output=True, text=True,
        )
        built = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise CertificationError("Cannot read built bridge revisions; reuse cannot be authorized.") from error
    if not isinstance(built, dict) or any(built.get(key) != identity[key] for key in (
        "lifecycle_protocol_revision", "profile_policy_revision"
    )):
        raise CertificationError("Built bridge revisions differ from source; reuse cannot be authorized.")
    if any(not isinstance(value, str) or not value for value in identity.values()):
        raise CertificationError("Current game or bridge identity is incomplete; reuse cannot be authorized.")
    return identity


def require_certificate(identity: dict[str, str], certificate_path: Path,
                        report_path: Path) -> dict[str, Any]:
    """Authorize reuse from the committed record, checking local full evidence when available."""
    remedy = "Run the dedicated certify_full_app_reuse gate and commit its certificate, or select --process-mode fresh."
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CertificationError(f"Reuse certification is missing. {remedy}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CertificationError(f"Reuse certification cannot be read. {remedy}") from error

    fields = certificate.get("identity") if isinstance(certificate, dict) else None
    timestamp = certificate.get("passed_at_utc") if isinstance(certificate, dict) else None
    digest = certificate.get("report_sha256") if isinstance(certificate, dict) else None
    try:
        if not isinstance(timestamp, str):
            raise TypeError("missing pass time")
        passed_at = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError) as error:
        raise CertificationError(f"Reuse certification is malformed. {remedy}") from error
    if (set(certificate) != {"identity", "passed_at_utc", "report_sha256"}
            or not isinstance(fields, dict) or set(fields) != set(IDENTITY_FIELDS)
            or any(not isinstance(fields[key], str) or not fields[key] for key in IDENTITY_FIELDS)
            or any(len(fields[key]) != 64 or any(char not in "0123456789abcdefABCDEF" for char in fields[key])
                   for key in ("assembly_sha256", "pck_sha256"))
            or passed_at.utcoffset() is None
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in digest)):
        raise CertificationError(f"Reuse certification is malformed. {remedy}")
    if fields != identity:
        changed = ", ".join(key for key in IDENTITY_FIELDS if fields[key] != identity.get(key))
        raise CertificationError(f"Reuse certification is stale ({changed}). {remedy}")
    try:
        evidence = report_path.read_bytes()
    except FileNotFoundError:
        evidence = None  # The full report is an untracked artifact, not part of the portable trust record.
    except OSError as error:
        raise CertificationError(f"Reuse certification evidence cannot be read. {remedy}") from error
    if evidence is not None and hashlib.sha256(evidence).hexdigest().lower() != digest.lower():
        raise CertificationError(f"Reuse certification evidence digest differs. {remedy}")
    return certificate


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
