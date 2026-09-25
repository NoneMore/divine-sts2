"""A run checkpoint restores the Ancient offer through the native worker interface."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from sts2_native_sim.ancient import ancient_action, choice_actions  # noqa: E402
from sts2_native_sim.client import NativeWorker  # noqa: E402


def main() -> None:
    with NativeWorker() as worker:
        reset = worker.run_reset({
            "game_build": {}, "seed": "ANCIENT01", "rng_counters": {},
            "character": "IRONCLAD", "ascension": 0, "encounter": "first",
            "current_hp": 80, "max_hp": 80, "deck": [], "gold": 99,
            "use_character_starting_loadout": True,
        })
        entrance = ancient_action(reset)
        assert entrance is not None
        entered = worker.run_step(entrance["action_id"])
        choices = choice_actions(entered)
        assert len(choices) > 1
        worker.run_step(choices[0]["action_id"])

        restored = worker.restore(entered["state_handle"])
        assert restored["state_hash"] == entered["state_hash"]
        assert restored["observation"] == entered["observation"]
        assert restored["transition"]["kind"] == "snapshot_restore", worker.request("diagnostics")
        assert restored["transition"]["replayed_actions"] == 0
        assert choice_actions(restored) == choices


if __name__ == "__main__":
    main()
