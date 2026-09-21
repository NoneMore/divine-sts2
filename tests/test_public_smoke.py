from __future__ import annotations

import json
from pathlib import Path

import pytest

from sts2_native_sim import cli


ROOT = Path(__file__).resolve().parents[1]


def test_public_schemas_are_valid_json() -> None:
    state = json.loads((ROOT / "schemas" / "canonical-state.schema.json").read_text(encoding="utf-8"))
    action = json.loads((ROOT / "schemas" / "legal-action.schema.json").read_text(encoding="utf-8"))
    # The canonical schema's version is pinned to the environment's constant, and validated against
    # recorded captures, by tests/test_observation_schema.py; this only checks the files parse.
    assert state["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "play_card" in action["properties"]["kind"]["enum"]


def test_cli_help_is_side_effect_free(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])
    assert raised.value.code == 0
    assert "doctor" in capsys.readouterr().out


def test_current_architecture_docs_link_implemented_modules_and_tool_replacements() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    tooling = (ROOT / "docs" / "tooling.md").read_text(encoding="utf-8")

    for required in (
        "Sts2.NativeSim.Core/RunSession",
        "Sts2.NativeSim.Protocol",
        "sts2_native_sim.scenarios",
        "ADR-0005",
        "ADR-0006",
    ):
        assert required in architecture
    for required in (
        "AutoTraceDriver",
        "run-isolated-autotrace.ps1",
        "TraceExporterSmoke",
        "ApiProbe",
        "latency_benchmark.py",
        "NativeSearchCoordinator",
    ):
        assert required in tooling
