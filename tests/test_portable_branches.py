"""Offline tests for portable-branch provenance validation.

These exercise the fail-closed rules the pool applies before any portable branch may touch a
worker: schema version, build identity, reset provenance, and the reset method each provenance
allows. No game process or pinned build is required.
"""
from types import SimpleNamespace

import pytest
from sts2_native_sim import NativeSimError
from sts2_native_sim.client import PORTABLE_BRANCH_SCHEMA_VERSION, _portable_reset_request

BUILD = {"version": "0.1.0+test", "assembly_sha256": "A" * 64, "pck_sha256": "B" * 64}
WORKER = SimpleNamespace(build=BUILD)


def branch(**overrides):
    record = {
        "schema_version": PORTABLE_BRANCH_SCHEMA_VERSION,
        "game_build": dict(BUILD),
        "reset": {"seed": "TEST"},
        "reset_request": {"method": "run_reset", "params": {"seed": "TEST"}},
        "provenance": "run",
        "history": ["choose_map:1:1"],
        "expected_hash": "C" * 64,
    }
    record.update(overrides)
    return record


def error_code(record):
    with pytest.raises(NativeSimError) as raised:
        _portable_reset_request(WORKER, record)
    return raised.value.code


def test_versioned_branch_resolves_its_recorded_mode():
    method, params, provenance = _portable_reset_request(WORKER, branch())
    assert (method, params, provenance) == ("run_reset", {"seed": "TEST"}, "run")


def test_run_start_branch_resolves_to_its_own_provenance():
    record = branch(
        reset={"seed": "TEST", "character": "IRONCLAD", "ascension": 0},
        reset_request={"method": "neow_run_reset", "params": {"seed": "TEST", "character": "IRONCLAD", "ascension": 0}},
        provenance="neow_run",
    )
    method, params, provenance = _portable_reset_request(WORKER, record)
    assert (method, params, provenance) == ("neow_run_reset", {"seed": "TEST", "character": "IRONCLAD", "ascension": 0}, "neow_run")
    # The run-start record is its own reset params, not a wrapped `state` payload.
    assert "state" not in params


def test_run_start_branch_provenance_must_match_its_method():
    assert error_code(branch(reset_request={"method": "neow_run_reset", "params": {}}, provenance="run")) == "reset_provenance_mismatch"


def test_provenance_must_match_the_reset_method():
    assert error_code(branch(provenance="map")) == "reset_provenance_mismatch"
    assert error_code(branch(reset_request={"method": "map_reset", "params": {}})) == "reset_provenance_mismatch"


def test_unknown_reset_method_fails_closed():
    assert error_code(branch(reset_request={"method": "teleport_reset", "params": {}}, provenance="teleport")) == "unknown_reset_mode"
    legacy = branch(reset_request={"method": "teleport_reset", "params": {}})
    del legacy["schema_version"], legacy["provenance"]
    assert error_code(legacy) == "unknown_reset_mode"


def test_versioned_branch_requires_provenance_and_reset_request():
    assert error_code(branch(provenance=None)) == "invalid_portable_branch"
    assert error_code(branch(reset_request=None)) == "invalid_portable_branch"
    assert error_code(branch(reset_request={"method": "run_reset"})) == "invalid_portable_branch"


def test_build_mismatch_fails_closed():
    differing = dict(BUILD, assembly_sha256="0" * 64)
    assert error_code(branch(game_build=differing)) == "build_mismatch"


def test_unknown_schema_version_fails_closed():
    assert error_code(branch(schema_version=PORTABLE_BRANCH_SCHEMA_VERSION + 1)) == "unsupported_portable_branch_schema"


def test_schema_less_record_takes_the_compatibility_path():
    legacy = branch()
    for key in ("schema_version", "provenance", "game_build"):
        del legacy[key]
    method, params, provenance = _portable_reset_request(WORKER, legacy)
    assert (method, params, provenance) == ("run_reset", {"seed": "TEST"}, None)
    bare = {"reset": {"seed": "TEST"}, "history": [], "expected_hash": "D" * 64}
    assert _portable_reset_request(WORKER, bare)[0] == "reset"


def test_incomplete_records_fail_closed():
    assert error_code({"reset_request": {"method": "reset", "params": {}}, "expected_hash": "E" * 64}) == "invalid_portable_branch"
    assert error_code(branch(history=None)) == "invalid_portable_branch"
