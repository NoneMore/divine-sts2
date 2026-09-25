"""Shipped-game check for excluding a first-combat relic without replacing its worker.

Run through the PowerShell environment layer::

    pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe tests/acceptance/scenario_interactive_relic_exclusion_acceptance.py'
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from sts2_native_sim.scenarios import ScenarioRequest, generate_corpus, read_corpus


def main() -> None:
    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("200150",))
    with tempfile.TemporaryDirectory(prefix="sts2-interactive-relic-") as root:
        started = time.perf_counter()
        summary = generate_corpus(request, 1, root)
        seconds = time.perf_counter() - started
        rows = list(read_corpus(root))

    assert [row["record_type"] for row in rows] == ["scenario", "scenario", "failure"], rows
    excluded = rows[2]
    assert excluded["recipe"]["ancient_choice"] == {"option_index": 2, "relic_model_id": "LARGE_CAPSULE"}
    assert excluded["stage"] == "first_combat"
    assert excluded["error"]["kind"] == "unsupported_interactive_first_combat_relic"
    assert "GAMBLING_CHIP" in excluded["error"]["message"]
    assert "combat_initial_state" not in excluded and "state_hash" not in excluded
    assert summary["worker_replacements"] == 0
    assert seconds < 10, f"the one-worker request took {seconds:.3f} s"

    print(json.dumps({
        "seed": "200150",
        "seconds": round(seconds, 3),
        "rows": summary["rows"],
        "worker_replacements": summary["worker_replacements"],
        "excluded_choice": excluded["recipe"]["ancient_choice"],
        "error": excluded["error"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
