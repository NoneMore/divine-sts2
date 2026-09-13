"""Four-worker acceptance for composed native map-to-combat room entry.

The map is generated from the run's `UpFront` stream, so E2's removal of the discarded synthetic
combat must not move a single room; what it must change is that no combat exists before the map
entry. The encounter identity is asserted as a four-worker agreement plus a real enemy check
rather than a hardcoded model id, because the shipped build no longer rolls `NIBBIT` for this
seed (recorded in `docs/persistent-environment.md`).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from acceptance import SCENARIO, assert_run_only_construction
from sts2_native_sim import NativeWorkerPool


def main() -> None:
    scenario = copy.deepcopy(SCENARIO)
    scenario["seed"] = "NATIVE-COMPOSED-ROOM-ENTRY"
    with NativeWorkerPool(4) as pool:
        mapped = pool.map(lambda worker, reset: worker.run_reset(reset), [scenario] * 4)
        assert len({state["state_hash"] for state in mapped}) == 1
        assert len({json.dumps(state["legal_actions"], sort_keys=True) for state in mapped}) == 1
        assert all(state["observation"]["decision"]["kind"] == "map_choice" for state in mapped)
        audits = [assert_run_only_construction(worker) for worker in pool.workers]
        assert len({json.dumps(audit, sort_keys=True) for audit in audits}) == 1, audits
        map_handle = mapped[0]["state_handle"]
        enter = mapped[0]["legal_actions"][0]["action_id"]

        entered = pool.map(lambda worker, action: worker.run_step(action), [enter] * 4)
        assert len({state["state_hash"] for state in entered}) == 1
        assert len({json.dumps(state["legal_actions"], sort_keys=True) for state in entered}) == 1
        assert all(state["observation"]["combat"]["phase"] == "Play" for state in entered)
        assert all(state["observation"]["combat"]["turn"] == 1 for state in entered)
        assert all(any(action["kind"] == "play_card" for action in state["legal_actions"]) for state in entered)
        encounters = [[creature["model_id"] for creature in state["observation"]["combat"]["creatures"] if creature["side"] == "Enemy"] for state in entered]
        assert all(encounter for encounter in encounters), encounters
        assert len({json.dumps(encounter) for encounter in encounters}) == 1, encounters
        assert all(sum(len(pile["cards"]) for pile in state["observation"]["combat"]["piles"]) == len(scenario["deck"]) for state in entered)
        assert all(len({card["instance_id"] for pile in state["observation"]["combat"]["piles"] for card in pile["cards"]}) == len(scenario["deck"]) for state in entered)
        assert all({card["instance_id"] for pile in state["observation"]["combat"]["piles"] for card in pile["cards"]} == {card["instance_id"] for card in scenario["deck"]} for state in entered)
        entered_handle = entered[0]["state_handle"]

        plays = [next(action["action_id"] for action in state["legal_actions"] if action["kind"] == "play_card") for state in entered]
        played = pool.map(lambda worker, action: worker.run_step(action), plays)
        assert len({state["state_hash"] for state in played}) == 1
        turned = pool.map(lambda worker, _: worker.run_step("end_turn"), range(4))
        assert len({state["state_hash"] for state in turned}) == 1
        assert all(state["observation"]["combat"]["turn"] == 2 for state in turned)

        worker = pool.workers[0]
        assert worker.restore(map_handle)["state_hash"] == mapped[0]["state_hash"]
        assert worker.restore(entered_handle)["state_hash"] == entered[0]["state_hash"]

        print(json.dumps({
            "success": True,
            "workers": 4,
            "map_hash": mapped[0]["state_hash"],
            "entered_hash": entered[0]["state_hash"],
            "played_hash": played[0]["state_hash"],
            "full_turn_hash": turned[0]["state_hash"],
            "map_action": enter,
            "encounter": encounters[0],
            "run_construction_audit": audits[0],
            "entry_elapsed_ms": [state["transition"]["elapsed_ms"] for state in entered],
        }, indent=2))


if __name__ == "__main__":
    main()
