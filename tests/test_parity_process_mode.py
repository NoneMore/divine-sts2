"""Parity's command boundary selects the certified lifecycle before starting the shipped game."""

from __future__ import annotations

import json

import pytest
from sts2_native_sim.reuse_certification import CertificationError

from tests.acceptance import parity_run_acceptance as parity_cli


class OfflinePool:
    def __init__(self, workers: int) -> None:
        self.workers = [type("Worker", (), {"build": {
            "version": "test", "assembly_sha256": "A" * 64, "pck_sha256": "B" * 64,
        }})()]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_uncertified_default_refuses_reuse_before_launch_but_explicit_fresh_runs(monkeypatch, tmp_path):
    certificate = tmp_path / "missing-certificate.json"
    report_path = tmp_path / "fresh.json"
    launches = []
    monkeypatch.setattr(parity_cli, "CERTIFICATE_PATH", certificate)
    monkeypatch.setattr(parity_cli, "NativeWorkerPool", OfflinePool)
    monkeypatch.setattr(parity_cli, "_records", lambda *_: {})
    monkeypatch.setattr(parity_cli, "ReusableFullAppWorker", lambda *_args, **_kwargs: launches.append("reuse"))
    monkeypatch.setattr(parity_cli, "_sample_result", lambda sample, *_args: {
        "label": sample.label, "character": sample.character, "ascension": sample.ascension,
        "nested_kinds": [], "matched": True,
    })

    with pytest.raises(SystemExit, match="2"):
        parity_cli.main(["--workers", "1"])
    assert launches == []
    assert parity_cli.main(["--workers", "1", "--limit", "1", "--process-mode", "fresh",
                            "--report", str(report_path)]) == 0
    document = json.loads(report_path.read_text(encoding="utf-8"))
    assert document["process_mode"] == "fresh"
    assert document["certification"]["status"] == "not_required"
    assert document["certification"]["identity"]["assembly_sha256"] == "A" * 64
    assert not certificate.exists()


def test_explicit_fresh_still_runs_when_bridge_revision_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(parity_cli, "NativeWorkerPool", OfflinePool)
    monkeypatch.setattr(parity_cli, "_records", lambda *_: {})
    monkeypatch.setattr(parity_cli, "current_certification_identity", lambda *_: (_ for _ in ()).throw(
        CertificationError("built bridge revision unavailable")))
    monkeypatch.setattr(parity_cli, "_sample_result", lambda sample, *_args: {
        "label": sample.label, "character": sample.character, "ascension": sample.ascension,
        "nested_kinds": [], "matched": True,
    })
    path = tmp_path / "fresh.json"
    assert parity_cli.main(["--workers", "1", "--limit", "1", "--process-mode", "fresh",
                            "--report", str(path)]) == 0
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["certification"]["status"] == "not_required"
