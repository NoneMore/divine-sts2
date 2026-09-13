"""Cross-worker portable branch provenance for every environment reset mode.

E2 evidence in three parts:

1. Every reset RPC reconstructs through one first-class provenance, and a composed run reset
   owns no combat phase at all.
2. Map, event/nested-choice, and combat branches round-trip through both local restore and
   cross-worker portable restore with identical hashes, observations, and legal actions.
3. Tampering with the recorded mode, history, hash, build, or schema version fails closed, and
   a schema-less record still replays through the explicit version-0 compatibility path.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from acceptance import COMBAT_RNG_STREAMS, SCENARIO, assert_run_only_construction, audit_construction_boundary
from sts2_native_sim import NativeSimError, NativeWorkerPool

EVENT_SCENARIO = copy.deepcopy(SCENARIO)
EVENT_SCENARIO.update({
    "seed": "NATIVE-PORTABLE-EVENT",
    "current_hp": 70,
    "max_hp": 80,
    "gold": 50,
})

# Reset mode -> the construction audit its reset must produce. Composed runs own the run and its
# map; every other mode still constructs combat after the run-only phase.
EXPECTED_MODE_AUDIT = {
    "combat": ("combat", audit_construction_boundary),
    "run": ("run", assert_run_only_construction),
    "map": ("map", audit_construction_boundary),
    "card_reward": ("card_reward", audit_construction_boundary),
    "item_reward": ("item_reward", audit_construction_boundary),
    "custom_reward": ("custom_reward", audit_construction_boundary),
    "rest": ("rest", audit_construction_boundary),
    "event": ("event", audit_construction_boundary),
}


def expect_error(code: str, action) -> NativeSimError:
    try:
        action()
    except NativeSimError as error:
        assert error.code == code, f"expected {code}, obtained {error.code}"
        return error
    raise AssertionError(f"expected {code} but the operation succeeded")


def assert_no_synthetic_combat(worker) -> dict:
    """A local restore of a composed-run branch must rebuild the run without a combat phase."""
    audit = worker.diagnostics()["last_restore"]
    assert audit is not None, "diagnostics did not report a restore audit"
    assert audit["mode"] == "run", audit
    assert audit["path"] == "replay", audit
    assert audit["synthetic_combat_installed"] is False, audit
    assert audit["player_has_combat_state"] is False, audit
    consumed = {s: audit["rng_counters"].get(s, 0) for s in COMBAT_RNG_STREAMS if audit["rng_counters"].get(s, 0) != 0}
    assert not consumed, f"composed run restore consumed combat RNG: {consumed}"
    return audit


def assert_portable_roundtrip(pool: NativeWorkerPool, worker_index: int, branch: dict, expected: dict, label: str) -> dict:
    assert branch["schema_version"] == 1, branch
    assert branch["provenance"] is not None, branch
    assert branch["game_build"]["assembly_sha256"], branch
    restored = pool.restore_portable(worker_index, branch)
    assert restored["state_hash"] == expected["state_hash"], label
    assert restored["observation"] == expected["observation"], label
    assert json.dumps(restored["legal_actions"], sort_keys=True) == json.dumps(expected["legal_actions"], sort_keys=True), label
    assert pool.workers[worker_index].reset_mode == branch["provenance"], label
    return restored


def main() -> None:
    with NativeWorkerPool(2) as pool:
        source = pool.workers[0]
        cases = [
            ("combat", "combat", lambda: source.reset(SCENARIO)),
            ("run", "run", lambda: source.run_reset(SCENARIO)),
            ("map", "map", lambda: source.map_reset(SCENARIO)),
            ("card_reward", "card_reward", lambda: source.reward_reset(SCENARIO)),
            ("item_reward", "item_reward", lambda: source.item_reward_reset(SCENARIO, "potion")),
            ("custom_reward", "custom_reward", lambda: source.custom_reward_reset(SCENARIO, ["gold"])),
            ("rest", "rest", lambda: source.rest_reset(SCENARIO)),
            ("event", "event", lambda: source.event_reset(EVENT_SCENARIO, "THIS_OR_THAT")),
        ]
        results = {}
        combat_branch: dict = {}
        for name, provenance, reset in cases:
            state = reset()
            mode, audit = EXPECTED_MODE_AUDIT[name]
            reported = audit(source)
            assert reported["mode"] == mode, (name, reported)
            assert source.diagnostics()["reset_mode"] == provenance, (name, source.diagnostics())
            action_id = state["legal_actions"][0]["action_id"]
            stepped = source.step(action_id)
            branch = source.export_branch()
            assert branch["provenance"] == provenance, (name, branch["provenance"])
            restored = assert_portable_roundtrip(pool, 1, branch, stepped, name)
            if name == "combat":
                combat_branch = copy.deepcopy(branch)
            results[name] = {"provenance": provenance, "action_id": action_id, "hash": restored["state_hash"]}

        # Stage coverage: map, event with a nested native choice, and combat each round-trip
        # through local restore and cross-worker portable restore.
        run_scenario = copy.deepcopy(SCENARIO)
        run_scenario["seed"] = "NATIVE-PORTABLE-STAGES"
        map_state = source.run_reset(run_scenario)
        assert assert_run_only_construction(source)["mode"] == "run"
        assert map_state["observation"]["decision"]["kind"] == "map_choice", map_state["observation"]["decision"]
        map_branch = source.export_branch()
        assert_portable_roundtrip(pool, 1, map_branch, map_state, "map stage")

        enter = source.step(map_state["legal_actions"][0]["action_id"])
        assert enter["observation"]["decision"]["kind"] == "combat_action", enter["observation"]["decision"]
        assert enter["observation"]["combat"]["turn"] == 1 and enter["observation"]["combat"]["phase"] == "Play", enter["observation"]["combat"]
        assert any(action["kind"] == "play_card" for action in enter["legal_actions"]), enter["legal_actions"]
        combat_stage = source.export_branch()
        assert_portable_roundtrip(pool, 1, combat_stage, enter, "run combat stage")

        # Local restore while the worker is resident in a later state must really reconstruct, and
        # that reconstruction must not build and discard a synthetic combat.
        advanced = source.run_step("end_turn")
        assert advanced["state_hash"] != map_state["state_hash"]
        local_map = source.restore(map_state["state_handle"])
        assert local_map["state_hash"] == map_state["state_hash"]
        assert local_map["transition"].get("resident_prefix_hit") is None, local_map["transition"]
        assert_no_synthetic_combat(source)
        replay = source.run_step(map_state["legal_actions"][0]["action_id"])
        assert replay["state_hash"] == enter["state_hash"]
        source.run_step("end_turn")
        local_combat = source.restore(enter["state_handle"])
        assert local_combat["state_hash"] == enter["state_hash"]
        assert local_combat["transition"].get("replayed_actions") == 1, local_combat["transition"]
        assert_no_synthetic_combat(source)

        nested = source.event_reset(EVENT_SCENARIO, "BRAIN_LEECH")
        share = next(action["action_id"] for action in nested["legal_actions"] if action["parameters"]["text_key"].endswith("SHARE_KNOWLEDGE"))
        choice = source.event_step(share)
        assert choice["observation"]["decision"]["kind"] == "card_choice", choice["observation"]["decision"]
        assert all(action["kind"] == "choose_cards" for action in choice["legal_actions"]), choice["legal_actions"]
        nested_branch = source.export_branch()
        assert_portable_roundtrip(pool, 1, nested_branch, choice, "event nested choice")
        picked = source.event_step(choice["legal_actions"][0]["action_id"])
        assert picked["observation"]["decision"]["kind"] == "event_complete", picked["observation"]["decision"]
        local_nested = source.restore(choice["state_handle"])
        assert local_nested["state_hash"] == choice["state_hash"]
        assert local_nested["transition"].get("replayed_actions") == 1, local_nested["transition"]

        # Negative evidence: tampered provenance, mode, history, hash, build, and schema fail
        # closed, and a schema-less record still takes the explicit version-0 compatibility path.
        tampered = copy.deepcopy(combat_branch)
        tampered["provenance"] = "map"
        expect_error("reset_provenance_mismatch", lambda: pool.restore_portable(1, tampered))
        tampered = copy.deepcopy(combat_branch)
        tampered["reset_request"]["method"] = "map_reset"
        expect_error("reset_provenance_mismatch", lambda: pool.restore_portable(1, tampered))
        tampered = copy.deepcopy(combat_branch)
        tampered["reset_request"]["method"] = "teleport_reset"
        expect_error("unknown_reset_mode", lambda: pool.restore_portable(1, tampered))
        tampered = copy.deepcopy(combat_branch)
        tampered["game_build"]["assembly_sha256"] = "0" * 64
        expect_error("build_mismatch", lambda: pool.restore_portable(1, tampered))
        tampered = copy.deepcopy(combat_branch)
        tampered["schema_version"] = 99
        expect_error("unsupported_portable_branch_schema", lambda: pool.restore_portable(1, tampered))
        tampered = copy.deepcopy(combat_branch)
        tampered["history"] = ["end_turn"]
        expect_error("replay_divergence", lambda: pool.restore_portable(1, tampered))
        tampered = copy.deepcopy(combat_branch)
        tampered["expected_hash"] = "0" * 64
        expect_error("replay_divergence", lambda: pool.restore_portable(1, tampered))
        legacy = copy.deepcopy(combat_branch)
        del legacy["schema_version"], legacy["provenance"], legacy["game_build"]
        legacy_restored = pool.restore_portable(1, legacy)
        assert legacy_restored["state_hash"] == results["combat"]["hash"], legacy_restored["state_hash"]
        legacy_run = copy.deepcopy(map_branch)
        del legacy_run["schema_version"], legacy_run["provenance"], legacy_run["game_build"]
        legacy_run_restored = pool.restore_portable(1, legacy_run)
        assert legacy_run_restored["state_hash"] == map_state["state_hash"], legacy_run_restored["state_hash"]

        print(json.dumps({
            "success": True,
            "workers": 2,
            "modes": results,
            "stages": {
                "map_hash": map_state["state_hash"],
                "run_combat_hash": enter["state_hash"],
                "run_combat_turn": enter["observation"]["combat"]["turn"],
                "run_combat_phase": enter["observation"]["combat"]["phase"],
                "event_nested_choice_hash": choice["state_hash"],
                "event_nested_options": len(choice["legal_actions"]),
                "legacy_schema_hash": legacy_restored["state_hash"],
                "legacy_run_schema_hash": legacy_run_restored["state_hash"],
            },
        }, indent=2))


if __name__ == "__main__":
    main()
