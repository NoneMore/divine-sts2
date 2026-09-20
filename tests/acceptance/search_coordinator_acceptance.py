"""Portable composed-run branch expansion and deterministic ranking acceptance."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
from sts2_native_sim import (
    NativeObservedMaterialScorer,
    NativeSearchCoordinator,
    NativeTorchValueScorer,
    NativeWorkerPool,
)
from tools.run_seeded_full_act_corpus import choose_action, scenario


def main() -> None:
    with NativeWorkerPool(4) as pool:
        worker = pool.workers[0]
        state = worker.run_reset(scenario("NATIVE-FULL-ACT-2"))
        # Walk the run to a combat rather than to a fixed step count: the route out of the
        # act's Ancient room is a decision of its own, so how many steps a fight is deep is
        # the run's business, not the search checkpoint's.
        depth = 0
        while state["observation"]["decision"]["kind"] != "combat_action":
            action_id = choose_action(state)
            if action_id is None:
                raise RuntimeError("route stalled before search checkpoint")
            state = worker.run_step(action_id)
            depth += 1
            if depth > 64:
                raise RuntimeError("route never reached a search checkpoint combat")
        root_hash = state["state_hash"]
        coordinator = NativeSearchCoordinator(pool)
        scorer = NativeObservedMaterialScorer()
        first = coordinator.rank(scorer)
        second = coordinator.rank(scorer)
        compact_first = [(item["action"]["action_id"], item["score"], item["state_hash"]) for item in first]
        compact_second = [(item["action"]["action_id"], item["score"], item["state_hash"]) for item in second]
        assert compact_first == compact_second
        assert len(first) == len(state["legal_actions"])
        assert coordinator.select(scorer)["action"]["action_id"] == first[0]["action"]["action_id"]
        search_first = coordinator.search(scorer, max_depth=2, node_budget=8, beam_width=3)
        search_second = coordinator.search(scorer, max_depth=2, node_budget=8, beam_width=3)
        assert search_first == search_second
        assert worker.observe()["state_hash"] == root_hash
        legacy_rejected = False
        legacy = Path(__file__).resolve().parents[2] / "models" / "set_transformer_ranked.pt"
        if not legacy.exists():
            legacy = Path(__file__).resolve().parents[3] / "models" / "set_transformer_ranked.pt"
        try:
            NativeTorchValueScorer.load(legacy, state["observation"]["game_build"])
        except ValueError:
            legacy_rejected = True
        assert legacy_rejected
        print(json.dumps({
            "success": True,
            "workers": 4,
            "root_depth": depth,
            "root_hash": root_hash,
            "candidate_count": len(first),
            "selected_action": first[0]["action"]["action_id"],
            "selected_score": first[0]["score"],
            "legacy_approximate_checkpoint_rejected": legacy_rejected,
            "multi_ply": search_first,
            "candidate_hashes": [item["state_hash"] for item in first],
        }, indent=2))


if __name__ == "__main__":
    main()
