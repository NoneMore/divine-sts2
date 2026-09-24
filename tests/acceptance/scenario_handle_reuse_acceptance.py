"""Native differential regression for reusing the Ancient offer's state handle.

The reference worker performs the former extra native fork at the Ancient offer.
Both paths use the public scenario generator, and every row is produced by a real
Godot-hosted worker on the same shipped-game build. Run directly on a configured
game host: ``python tests/acceptance/scenario_handle_reuse_acceptance.py``.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from scenario_fork_reference import ForkAfterAncientWorker  # type: ignore[import-not-found]
from sts2_native_sim.client import NativeWorker
from sts2_native_sim.scenarios import ScenarioRequest, encode_row, generate_rows

SAMPLES = (
    ("IRONCLAD", 0, "SCENAR10A01"),
    ("IRONCLAD", 0, "ANCIENT01"),
    ("IRONCLAD", 0, "GYMSCENAR10"),
    ("IRONCLAD", 2, "ANCIENT03"),
    ("DEFECT", 0, "TRACERBULLET"),
    ("DEFECT", 0, "ANCIENT06"),
)


def _generate(worker: NativeWorker, request: ScenarioRequest, *, reference: bool) -> tuple[list[dict[str, Any]], Counter[str]]:
    calls: Counter[str] = Counter()
    original_request = worker.request

    def counted_request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        calls[method] += 1
        return original_request(method, params)

    worker.request = counted_request  # type: ignore[method-assign]
    try:
        driver = ForkAfterAncientWorker(worker) if reference else worker
        return generate_rows(request, driver), calls
    finally:
        worker.request = original_request  # type: ignore[method-assign]


def main() -> None:
    totals: Counter[str] = Counter()
    nested_kinds: set[str] = set()
    with NativeWorker() as worker:
        for character, ascension, seed in SAMPLES:
            request = ScenarioRequest((character,), (ascension,), (seed,))
            reference, old_calls = _generate(worker, request, reference=True)
            current, new_calls = _generate(worker, request, reference=False)
            label = f"{character}@A{ascension}/{seed}"
            if reference != current:
                raise AssertionError(f"{label}: Generated scenario rows differ from the native fork reference")
            if b"".join(encode_row(row).encode("utf-8") for row in reference) != b"".join(
                encode_row(row).encode("utf-8") for row in current
            ):
                raise AssertionError(f"{label}: encoded row bytes differ")
            if not current or any(row["record_type"] != "scenario" for row in current):
                raise AssertionError(f"{label}: expected one successful scenario per offered Ancient choice")
            if old_calls["fork"] != 1 or new_calls["fork"] != 0:
                raise AssertionError(f"{label}: expected exactly one removed native fork RPC")
            for method in ("run_reset", "restore", "run_step"):
                if old_calls[method] != new_calls[method]:
                    raise AssertionError(f"{label}: {method} count differs: {old_calls[method]} != {new_calls[method]}")
            if old_calls["run_reset"] != 1 or old_calls["restore"] != len(current) - 1:
                raise AssertionError(f"{label}: expected one reset and one restore per later Ancient choice")
            nested_kinds.update(
                nested["kind"] for row in current for nested in row["recipe"]["nested_choices"]
            )
            totals.update({"elements": 1, "rows": len(current), "forks_removed": 1})
            totals.update({f"old_{key}": value for key, value in old_calls.items()})
            totals.update({f"new_{key}": value for key, value in new_calls.items()})

        missing = {"card_choice", "custom_reward_choice"} - nested_kinds
        if missing:
            raise AssertionError(f"native sample no longer covers nested decisions {sorted(missing)}")
        print(json.dumps({"success": True, "game_build": worker.build, "counts": totals,
                          "nested_kinds": sorted(nested_kinds)}, default=dict, indent=2))


if __name__ == "__main__":
    main()
