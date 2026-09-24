"""The certification report is the public evidence checked before a trust record is written."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from sts2_native_sim.parity_projection import project_record
from sts2_native_sim.reuse_certification import evaluate, issue_certificate

from tests.acceptance.parity_run_acceptance import SAMPLE

BUILD = {"version": "test", "assembly_sha256": "A" * 64, "pck_sha256": "B" * 64}
PROFILE = {"in_memory": "C" * 64, "persisted": "C" * 64}
CAPTURE = json.loads((Path(__file__).parent / "fixtures" / "canonical-observations.json").read_text(
    encoding="utf-8"
))["run_combat_action"]
PROJECTION = project_record(CAPTURE)


def evidence():
    fresh = []
    reused = []
    for index, sample in enumerate(SAMPLE):
        base = {
            "label": sample.label, "matched": True, "game_build": BUILD,
            "projection": PROJECTION,
            "boundary_trace": [{"phase": "event", "legal": ["choose_event:0"], "chosen": "choose_event:0"}],
            "initial_history": {"actions": [], "state_hashes": [f"own-{index}"]},
            "initial_state_hash": f"own-{index}",
        }
        fresh.append(dict(base, pid=1000 + index, process_mode="fresh", start_path="menu"))
        reused.append(dict(base, pid=123, process_mode="reuse", process_entry_ordinal=index + 1,
                           start_path="menu" if index == 0 else "direct", warm=index > 0,
                           replacement_count=0, pck_fingerprint_count=1 if index == 0 else 0,
                           pck_fingerprint_bytes=100 if index == 0 else 0,
                           teardown={"final_state": "idle", "ended_generation": index + 1,
                                     "driver_result": "abandoned", "ending_phase": "combat",
                                     "parked_wait_released": True, "stale_continuation_refusals": 1,
                                     "reset_history_counts": {"actions": 2, "state_hashes": 3},
                                     "duration_ms": 1},
                           startup_seconds=1, entry_seconds=2, teardown_seconds=0.1))
    reused.append(dict(reused[0], process_entry_ordinal=17, start_path="direct", warm=True,
                       pck_fingerprint_count=0, pck_fingerprint_bytes=0,
                       teardown=dict(reused[0]["teardown"], ended_generation=17)))
    return fresh, reused


def test_complete_equivalence_passes_and_sentinel_is_entry_seventeen():
    fresh, reused = evidence()
    result = evaluate(fresh, reused, BUILD, PROFILE, PROFILE)
    assert result["success"] is True, result["failures"]
    assert result["processes_started"] == 1
    assert len(result["comparisons"]) == 17


def test_projection_boundary_history_and_lifecycle_drift_block_certification():
    fresh, reused = evidence()
    for change in (
        lambda rows: rows[4]["projection"]["run"].update(gold=-1),
        lambda rows: rows[4]["boundary_trace"][0].update(chosen="choose_event:1"),
        lambda rows: rows[4]["initial_history"]["actions"].append("stale"),
        lambda rows: rows[4].update(pid=456),
        lambda rows: rows[4].update(teardown=None),
    ):
        altered = copy.deepcopy(reused)
        change(altered)
        assert evaluate(fresh, altered, BUILD, PROFILE, PROFILE)["success"] is False


def test_profile_drift_and_fresh_failure_block_certification():
    fresh, reused = evidence()
    assert evaluate(fresh, reused, BUILD, PROFILE, {"in_memory": "D" * 64,
                                                    "persisted": "C" * 64})["success"] is False
    fresh[2]["matched"] = False
    assert evaluate(fresh, reused, BUILD, PROFILE, PROFILE)["success"] is False


def test_only_complete_report_issues_a_path_free_certificate(tmp_path):
    report_path = tmp_path / "artifacts" / "report.json"
    certificate_path = tmp_path / "certifications" / "reuse.json"
    identity = {"assembly_sha256": BUILD["assembly_sha256"], "pck_sha256": BUILD["pck_sha256"],
                "lifecycle_protocol_revision": "reuse-v1", "profile_policy_revision": "profile-v1",
                "scenario_set_revision": "scenarios-v1"}
    with pytest.raises(ValueError, match="failed"):
        issue_certificate({"success": False, "identity": identity}, report_path, certificate_path)
    assert report_path.is_file() and not certificate_path.exists()

    with pytest.raises(ValueError, match="incomplete"):
        issue_certificate({"success": True, "identity": identity}, report_path, certificate_path)
    assert not certificate_path.exists()

    fresh, reused = evidence()
    complete_report = {**evaluate(fresh, reused, BUILD, PROFILE, PROFILE),
                       "identity": identity, "game_build": BUILD, "fresh": fresh, "reused": reused,
                       "profile_baseline": PROFILE["in_memory"]}
    certificate = issue_certificate(complete_report, report_path, certificate_path)
    assert certificate["identity"] == identity
    assert certificate["report_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()
    assert json.loads(certificate_path.read_text()) == certificate
    assert str(tmp_path) not in certificate_path.read_text()
