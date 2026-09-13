"""Offline tests for the first-combat root enumeration library.

These drive `FirstCombatEnumerator` with a tiny deterministic fake of the three-call worker
surface (`neow_run_reset`, `step`, `export_branch`), so branch scheduling, cap handling, failure
classification, record shape, and canonical byte stability are all testable without the pinned
build or a game process. The real-build gate is `python/first_combat_root_acceptance.py`.
"""
from __future__ import annotations

import copy
import json

import pytest
from sts2_native_sim import (
    DEFAULT_LIMITS,
    EnumerationLimits,
    FirstCombatEnumerator,
    FirstCombatError,
    assert_first_combat_root,
    branch_identity,
    enumerate_first_combat_roots,
    is_first_combat_root,
    run_start_request,
)

BUILD = {"version": "0.1.0+test", "assembly_sha256": "A" * 64, "pck_sha256": "B" * 64}
MAP_ACTIONS = ("choose_map:1:1", "choose_map:2:1")
COMBAT_ACTIONS = ("play:card-0:target:1", "end_turn")
BLESSING_A = "choose_event:0:NEOW.pages.INITIAL.options.LARGE_CAPSULE"
BLESSING_B = "choose_event:1:NEOW.pages.INITIAL.options.NEW_LEAF"
CARD_SKIP = "choose_cards:card-choice-0:skip"
CARD_PICK = "choose_cards:card-choice-0:generated-card-choice-0-0-STRIKE"
PROCEED = "proceed_neow"

# Action id -> kind for the fake tree's legal actions.
ACTION_KINDS = {
    BLESSING_A: "choose_event",
    BLESSING_B: "choose_event",
    CARD_SKIP: "choose_cards",
    CARD_PICK: "choose_cards",
    PROCEED: "proceed_neow",
    MAP_ACTIONS[0]: "choose_map",
    MAP_ACTIONS[1]: "choose_map",
    COMBAT_ACTIONS[0]: "play_card",
    COMBAT_ACTIONS[1]: "end_turn",
}


def decision(observation):
    return observation["decision"]["kind"]


def run_observation(hash_suffix: str, **extra):
    observation = {
        "schema_version": 3,
        "game_build": dict(BUILD),
        "run": {
            "seed": "TESTSEED",
            "ascension": 0,
            "rng_counters": {"Shuffle": 9, "UpFront": 12},
        },
        "decision": {"kind": "combat_action"},
        "hash_suffix": hash_suffix,
    }
    observation.update(extra)
    return observation


def combat_observation(hash_suffix: str, turn: int = 1, phase: str = "Play"):
    return run_observation(
        hash_suffix,
        combat={
            "turn": turn,
            "phase": phase,
            "creatures": [
                {"model_id": "IRONCLAD", "side": "Player", "hp": 80, "max_hp": 80},
                {"model_id": "NIBBIT", "side": "Enemy", "hp": 12, "max_hp": 12},
            ],
        },
    )


def choice_observation(kind: str, hash_suffix: str):
    return run_observation(hash_suffix, decision={"kind": kind}, event={"model_id": "NEOW", "options": []})


def node(observation, actions, state_hash=None):
    legal = []
    for action_id in actions:
        kind = ACTION_KINDS.get(action_id, action_id.split(":", 1)[0])
        parameters = {}
        if kind == "choose_map":
            _, col, row = action_id.split(":")
            parameters = {"col": int(col), "row": int(row), "point_type": "Monster"}
        legal.append({"action_id": action_id, "kind": kind, "parameters": parameters})
    return {
        "observation": observation,
        "legal_actions": legal,
        "state_hash": state_hash or observation["hash_suffix"].upper().ljust(16, "0"),
    }


def standard_nodes():
    """Neow -> two blessings; blessing B opens a two-way card choice. Every map point is a root."""
    nodes = {
        (): node(choice_observation("event_choice", "neow"), [BLESSING_A, BLESSING_B]),
        (BLESSING_A,): node(choice_observation("neow_complete", "a-complete"), [PROCEED]),
        (BLESSING_A, PROCEED): node(
            run_observation("map", decision={"kind": "map_choice"}), list(MAP_ACTIONS)
        ),
        (BLESSING_B,): node(choice_observation("card_choice", "b-choice"), [CARD_SKIP, CARD_PICK]),
        (BLESSING_B, CARD_SKIP): node(choice_observation("neow_complete", "b-skip"), [PROCEED]),
        (BLESSING_B, CARD_PICK): node(choice_observation("neow_complete", "b-pick"), [PROCEED]),
        (BLESSING_B, CARD_SKIP, PROCEED): node(run_observation("map-b", decision={"kind": "map_choice"}), list(MAP_ACTIONS)),
        (BLESSING_B, CARD_PICK, PROCEED): node(run_observation("map-b", decision={"kind": "map_choice"}), list(MAP_ACTIONS)),
    }
    # Both map points of one blessing produce the same combat state, so the six roots hold only two
    # distinct hashes. That is exactly the case where surface-state deduplication would be wrong.
    nodes[(BLESSING_A, PROCEED, MAP_ACTIONS[0])] = node(combat_observation("a-root"), list(COMBAT_ACTIONS))
    nodes[(BLESSING_A, PROCEED, MAP_ACTIONS[1])] = node(combat_observation("a-root"), list(COMBAT_ACTIONS))
    for prefix in ((BLESSING_B, CARD_SKIP, PROCEED), (BLESSING_B, CARD_PICK, PROCEED)):
        for map_action in MAP_ACTIONS:
            nodes[prefix + (map_action,)] = node(combat_observation("b-root"), list(COMBAT_ACTIONS))
    return nodes


class FakeFirstCombatWorker:
    """Deterministic fake of the worker calls the enumerator depends on."""

    def __init__(self, nodes, build=None):
        self.nodes = nodes
        self.build = dict(build or BUILD)
        self.run_start: dict | None = None
        self.trace: tuple[str, ...] = ()
        self.resets = 0
        self.steps = 0

    def _state(self):
        record = self.nodes[self.trace]
        return {
            "state_hash": record["state_hash"],
            "state_handle": "h:" + "|".join(self.trace),
            "observation": copy.deepcopy(record["observation"]),
            "legal_actions": copy.deepcopy(record["legal_actions"]),
        }

    def neow_run_reset(self, run_start):
        assert isinstance(run_start, dict) and set(run_start) == {"game_build", "seed", "character", "ascension"}
        self.run_start = copy.deepcopy(run_start)
        self.trace = ()
        self.resets += 1
        return self._state()

    def step(self, action_id):
        legal = {action["action_id"] for action in self.nodes[self.trace]["legal_actions"]}
        assert action_id in legal, f"{action_id!r} is not legal at {self.trace}"
        self.trace = self.trace + (action_id,)
        self.steps += 1
        return self._state()

    def export_branch(self):
        record = self.nodes[self.trace]
        return {
            "schema_version": 1,
            "game_build": dict(self.build),
            "reset": copy.deepcopy(self.run_start),
            "reset_request": {"method": "neow_run_reset", "params": copy.deepcopy(self.run_start)},
            "provenance": "neow_run",
            "history": list(self.trace),
            "expected_hash": record["state_hash"],
        }


def enumerate_standard(**limits):
    worker = FakeFirstCombatWorker(standard_nodes())
    enumeration = FirstCombatEnumerator(worker, EnumerationLimits(**limits) if limits else None).enumerate(
        "TESTSEED", "IRONCLAD", 0
    )
    return worker, enumeration


def test_enumerates_every_legal_action_once():
    worker, enumeration = enumerate_standard()
    assert enumeration.complete and enumeration.failures == ()
    assert len(enumeration.roots) == 6
    assert {root.route["coord"]["col"] for root in enumeration.roots} == {1, 2}
    # The fake implements no `restore`, so a walk that depended on restoring a sibling's state
    # could not complete at all: every node is re-driven from the run-start recipe. Six run starts
    # is the initial one plus one per sibling after the first.
    assert not hasattr(worker, "restore")
    assert worker.resets == 6 == enumeration.expansions - 8
    assert worker.steps > 0


def test_same_state_roots_stay_separate_branches():
    _, enumeration = enumerate_standard()
    hashes = [root.root_hash for root in enumeration.roots]
    assert len(set(hashes)) == 2 < len(hashes), hashes
    identities = [root.branch_id for root in enumeration.roots]
    assert len(set(identities)) == len(identities)
    for root in enumeration.roots:
        assert root.branch_id == branch_identity("TESTSEED", "IRONCLAD", 0, root.trace)


def test_roots_are_sorted_and_repeatable():
    worker, first = enumerate_standard()
    traces = [root.trace for root in first.roots]
    assert traces == sorted(traces)
    second = FirstCombatEnumerator(worker, None).enumerate("TESTSEED", "IRONCLAD", 0)
    assert second.canonical_bytes() == first.canonical_bytes()
    assert [root.branch_id for root in second.roots] == [root.branch_id for root in first.roots]


def test_record_carries_root_provenance_and_no_process_state():
    _, enumeration = enumerate_standard()
    record = enumeration.as_record()
    assert record["schema_version"] == 1 and record["complete"] is True
    assert record["neow_decision"]["model_id"] == "NEOW"
    assert record["limits"] == DEFAULT_LIMITS.as_record()
    for root in record["roots"]:
        assert root["portable_branch"]["provenance"] == "neow_run"
        assert root["portable_branch"]["history"] == root["trace"]
        assert root["portable_branch"]["reset_request"]["method"] == "neow_run_reset"
        assert set(root["run_start"]) == {"game_build", "seed", "character", "ascension"}
        assert root["run_rng_counters"] and root["game_build"]["assembly_sha256"]
        assert root["action_kinds"][-1] == "choose_map"
        assert "state_handle" not in root
    assert "state_handle" not in json.dumps(record)


def test_action_cap_marks_the_seed_incomplete():
    _, enumeration = enumerate_standard(max_actions_per_branch=1)
    assert enumeration.complete is False
    assert {failure.reason for failure in enumeration.failures} == {"action_cap"}
    with pytest.raises(FirstCombatError):
        enumeration.assert_complete()


def test_root_cap_marks_the_seed_incomplete():
    _, enumeration = enumerate_standard(max_roots=2)
    assert enumeration.complete is False
    assert "root_cap" in {failure.reason for failure in enumeration.failures}
    assert len(enumeration.roots) == 2


def test_expansion_cap_marks_the_seed_incomplete():
    _, enumeration = enumerate_standard(max_expansions=3)
    assert enumeration.complete is False
    assert "expansion_cap" in {failure.reason for failure in enumeration.failures}


def test_no_legal_action_is_recorded():
    nodes = standard_nodes()
    nodes[(BLESSING_A,)] = node(choice_observation("neow_complete", "a-complete"), [])
    enumeration = FirstCombatEnumerator(FakeFirstCombatWorker(nodes)).enumerate("TESTSEED", "IRONCLAD", 0)
    assert "no_legal_action" in {failure.reason for failure in enumeration.failures}
    assert enumeration.complete is False


def test_unsupported_action_is_recorded_rather_than_followed():
    nodes = standard_nodes()
    nodes[(BLESSING_A,)] = node(choice_observation("neow_complete", "a-complete"), ["open_treasure"])
    enumeration = FirstCombatEnumerator(FakeFirstCombatWorker(nodes)).enumerate("TESTSEED", "IRONCLAD", 0)
    failures = {failure.reason: failure for failure in enumeration.failures}
    assert "unsupported_action" in failures
    assert "open_treasure" in failures["unsupported_action"].detail


def test_unsupported_decision_is_recorded():
    nodes = standard_nodes()
    nodes[(BLESSING_A,)] = node(run_observation("shop", decision={"kind": "shop_choice"}), [PROCEED])
    enumeration = FirstCombatEnumerator(FakeFirstCombatWorker(nodes)).enumerate("TESTSEED", "IRONCLAD", 0)
    assert "unsupported_decision" in {failure.reason for failure in enumeration.failures}


def test_terminal_decision_before_root_is_recorded():
    nodes = standard_nodes()
    nodes[(BLESSING_A,)] = node(run_observation("dead", decision={"kind": "run_terminal"}), [])
    enumeration = FirstCombatEnumerator(FakeFirstCombatWorker(nodes)).enumerate("TESTSEED", "IRONCLAD", 0)
    assert "terminal_before_root" in {failure.reason for failure in enumeration.failures}


def test_combat_outside_the_boundary_is_recorded_not_exported():
    nodes = standard_nodes()
    for map_action in MAP_ACTIONS:
        nodes[(BLESSING_A, PROCEED, map_action)] = node(combat_observation("late", turn=2), list(COMBAT_ACTIONS))
    enumeration = FirstCombatEnumerator(FakeFirstCombatWorker(nodes)).enumerate("TESTSEED", "IRONCLAD", 0)
    assert "not_at_root_boundary" in {failure.reason for failure in enumeration.failures}
    assert all("a-root" not in root.root_hash for root in enumeration.roots)


def test_is_first_combat_root_requires_both_halves():
    assert is_first_combat_root(combat_observation("x"))
    assert not is_first_combat_root(combat_observation("x", phase="Start"))
    assert not is_first_combat_root(combat_observation("x", turn=2))
    assert not is_first_combat_root(choice_observation("map_choice", "x"))


def test_assert_first_combat_root_rejects_incomplete_provenance():
    state = {
        "state_hash": "H",
        "observation": combat_observation("x"),
        "legal_actions": [{"action_id": "end_turn", "kind": "end_turn"}],
    }
    with pytest.raises(FirstCombatError):
        assert_first_combat_root(state, "case")
    state["legal_actions"].append({"action_id": "play:x:none", "kind": "play_card"})
    assert_first_combat_root(state, "case")

    missing_counters = copy.deepcopy(state)
    missing_counters["observation"]["run"] = {"seed": "TESTSEED", "ascension": 0}
    with pytest.raises(FirstCombatError):
        assert_first_combat_root(missing_counters, "case")

    missing_build = copy.deepcopy(state)
    missing_build["observation"]["game_build"] = {"version": "0.1.0+test"}
    with pytest.raises(FirstCombatError):
        assert_first_combat_root(missing_build, "case")

    wrong_phase = copy.deepcopy(state)
    wrong_phase["observation"]["combat"]["phase"] = "Start"
    with pytest.raises(FirstCombatError):
        assert_first_combat_root(wrong_phase, "case")


def test_run_start_request_validates_its_inputs():
    assert run_start_request("SEED", "IRONCLAD", 0) == {
        "game_build": {}, "seed": "SEED", "character": "IRONCLAD", "ascension": 0,
    }
    for bad in (("", "IRONCLAD", 0), ("SEED", "", 0), ("SEED", "IRONCLAD", -1), ("SEED", "IRONCLAD", True)):
        with pytest.raises(FirstCombatError):
            run_start_request(*bad)


def test_limits_reject_non_positive_values():
    for bad in ({"max_roots": 0}, {"max_expansions": -1}, {"max_actions_per_branch": 0}):
        with pytest.raises(FirstCombatError):
            EnumerationLimits(**bad)


def test_wrapper_matches_the_enumerator():
    worker = FakeFirstCombatWorker(standard_nodes())
    enumeration = enumerate_first_combat_roots(worker, "TESTSEED", "IRONCLAD", 0, EnumerationLimits(max_roots=6))
    assert len(enumeration.roots) == 6 and enumeration.complete
