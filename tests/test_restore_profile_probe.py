"""Offline tests for the restore profile probe's answer.

The probe itself needs the shipped game, so what is asserted here is the part that turns its raw
records into the answer a decision rests on: how many restores hit the resident prefix and where
the rest of their time went. That arithmetic is the probe's whole claim — a part summed the wrong
way, or a restore counted as free because the worker never reported a profile — would be reported
as a measurement rather than as a mistake.

The probe is a support-area script rather than part of the supported package, so it is imported the
way the repository's other offline tests reach one: by putting `python/` on the path for the test.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def attribute_restores(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[dict[str, Any]]], dict[str, Any]]:
    """The probe's attribution, imported from the support area the way the probe itself is run."""
    monkeypatch.syspath_prepend(str(ROOT / "python"))
    from experiments.scenario_restore_profile import attribute_restores as attribute

    return attribute


def _restore(seconds: float, profile: dict[str, Any] | None, *, hit: bool = False) -> dict[str, Any]:
    """One restore RPC as the probe records it: the wall time it took, and its transition.

    A `None` profile is the worker that was not asked to time itself: the transition carries no
    profile at all, which is what the real worker reports when profiling is off. The hit travels
    beside the profile, as the worker reports it.
    """
    transition: dict[str, Any] = {"kind": "restore", "replayed_actions": 1}
    if hit:
        transition["resident_prefix_hit"] = True
    if profile is not None:
        transition["profile"] = profile
    return {"seconds": seconds, "transition": transition}


def test_attribution_counts_the_resident_prefix_hits_and_totals_each_named_part(
    attribute_restores: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> None:
    restores = [
        _restore(0.002, {"total_ms": 1.5, "unattributed_ms": 1.5}, hit=True),
        _restore(0.215, {
            "resident_check_ms": 0.004,
            "total_ms": 210.0,
            "run_rebuild_ms": 100.0,
            "map_rebuild_ms": 60.0,
            "replay_ms": 30.0,
            "capture_ms": 15.0,
            "unattributed_ms": 5.0,
        }),
        _restore(0.230, {
            "resident_check_ms": 0.006,
            "total_ms": 220.0,
            "run_rebuild_ms": 110.0,
            "map_rebuild_ms": 70.0,
            "replay_ms": 20.0,
            "capture_ms": 15.0,
            "unattributed_ms": 5.0,
        }),
    ]

    answer = attribute_restores(restores)

    assert answer["count"] == 3
    assert answer["resident_prefix_hits"] == 1
    assert answer["parts_ms"] == {
        "resident_check_ms": 0.01,
        "run_rebuild_ms": 210.0,
        "map_rebuild_ms": 130.0,
        "mode_init_ms": 0.0,
        "replay_ms": 50.0,
        "snapshot_ms": 0.0,
        "capture_ms": 30.0,
    }
    assert answer["worker_total_ms"] == 431.5
    assert answer["unattributed_ms"] == 11.5
    assert answer["rpc_seconds"] == pytest.approx(0.447)
    assert answer["outside_worker_ms"] == pytest.approx(447.0 - 431.5)


def test_attribution_refuses_a_restore_the_worker_did_not_time(
    attribute_restores: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> None:
    """A worker that was not profiling is not a restore that took no time."""
    restores = [_restore(0.2, None)]

    with pytest.raises(ValueError, match="STS2_RESTORE_PROFILE"):
        attribute_restores(restores)


def test_attribution_refuses_a_request_that_restored_nothing(
    attribute_restores: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> None:
    """An empty measurement must not read as a request whose restores were all free."""
    with pytest.raises(ValueError, match="no restore"):
        attribute_restores([])


def test_the_probe_measures_the_small_reference_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """The request the probe drives is reference request A, and profiling is asked for by name."""
    monkeypatch.syspath_prepend(str(ROOT / "python"))
    from experiments import scenario_restore_profile as probe

    assert probe.REQUEST.characters == ("IRONCLAD",)
    assert probe.REQUEST.ascensions == (0,)
    assert probe.REQUEST.seeds == ("A1B2C3D4E5", "1", "2", "3")
    assert probe.PROFILE_ENVIRONMENT_VARIABLE == "STS2_RESTORE_PROFILE"
