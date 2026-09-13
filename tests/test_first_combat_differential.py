"""Offline tests for the E5 first-combat differential comparator.

These tests need no game installation: they exercise the frozen root schema, the semantic action
keys, the difference finder, and the campaign loop against synthetic workers, so a comparator bug
fails here instead of looking like a simulator divergence.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from sts2_native_sim.first_combat_differential import (  # noqa: E402
    FAST,
    FULL,
    UNSUPPORTED_KINDS,
    ROOT_SCHEMA,
    EntryResult,
    aggregate,
    decision_keys_json,
    first_difference,
    normalize_identity,
    normalize_root,
    run_entry,
    semantic_action,
    semantic_action_keys,
    smallest_key_policy,
)

BUILD = {"version": "0.1.0+test", "assembly_sha256": "AA", "pck_sha256": "BB"}


def _card(model_id: str, *, instance_id: str, index: int, upgrades: int = 0, native_state: dict | None = None) -> dict:
    return {
        "index": index,
        "net_id": index + 1,
        "instance_id": instance_id,
        "model_id": model_id,
        "card_type": "Attack",
        "target_type": "AnyEnemy",
        "energy_cost": 1,
        "costs_x": False,
        "upgrades": upgrades,
        "enchantment": None,
        "native_state": native_state or {},
    }


def _creature(*, side: str, model_id: str, hp: int, alive: bool = True, combat_id: int = 1, index: int = 0) -> dict:
    return {
        "combat_id": combat_id,
        "index": index,
        "side": side,
        "model_id": model_id,
        "hp": hp,
        "max_hp": hp,
        "block": 0,
        "alive": alive,
        "next_move": {"id": "MOVE", "intents": [{"intent_type": "Attack", "implementation": "SingleAttackIntent", "damage": 6, "repeats": 1}]},
        "powers": [{"model_id": "STRENGTH", "amount": 1}],
    }


def fast_root_observation() -> dict:
    hand = [_card("STRIKE_IRONCLAD", instance_id="starter-0-STRIKE_IRONCLAD", index=0)]
    draw = [_card("DEFEND_IRONCLAD", instance_id="starter-1-DEFEND_IRONCLAD", index=0)]
    return {
        "schema_version": 2,
        "game_build": BUILD,
        "run": {"seed": "SEED", "ascension": 0, "gold": 99, "rng_counters": {"Shuffle": 10, "Upfront": 1}},
        "combat": {
            "turn": 1,
            "phase": "Play",
            "energy": 3,
            "max_energy": 3,
            "stars": 0,
            "creatures": [
                _creature(side="Player", model_id="IRONCLAD", hp=80, combat_id=0, index=0),
                _creature(side="Enemy", model_id="NIBBIT", hp=42, combat_id=1, index=1),
            ],
            "piles": [
                {"name": "Hand", "type": "Hand", "cards": hand},
                {"name": "DrawPile", "type": "Draw", "cards": draw},
                {"name": "DiscardPile", "type": "Discard", "cards": []},
                {"name": "ExhaustPile", "type": "Exhaust", "cards": []},
                {"name": "PlayPile", "type": "Play", "cards": []},
            ],
        },
        "inventory": {"relics": [{"model_id": "BURNING_BLOOD", "counter": None, "native_state": {}}], "potions": [None, None]},
        "decision": {"kind": "combat_action"},
    }


def full_root_observation() -> dict:
    observation = fast_root_observation()
    observation["schema_version"] = 3
    observation["combat"] = dict(observation["combat"])
    observation["combat"]["encounter"] = {"model_id": "NIBBITS_WEAK", "room_type": "Monster", "monster_models": ["NIBBIT"], "slots": []}
    # The shipped projection carries explicit environment-local handles and its own run block.
    observation["combat"]["piles"] = [
        {**pile, "cards": [{**card, "net_id": 99} for card in pile["cards"]]} for pile in observation["combat"]["piles"]
    ]
    observation["run"] = {
        "seed": "SEED",
        "character": "IRONCLAD",
        "ascension": 0,
        "gold": 99,
        "current_hp": 80,
        "max_hp": 80,
        "rng_counters": {"Shuffle": 10, "Upfront": 1},
        "relics": [{"index": 0, "model_id": "BURNING_BLOOD", "counter": None, "native_state": {}}],
        "potions": [None, None],
        "potion_capacity": 2,
    }
    return observation


def test_first_difference_reports_type_key_and_length_changes():
    assert first_difference({"a": 1}, {"a": 1}) is None
    assert first_difference({"a": 1}, {"a": 2}).path == "$.a"
    assert first_difference({"a": 1}, {"b": 1}).path == "$"
    assert first_difference([1, 2], [1]).path == "$.length"
    # int/float equality is one numeric class; bool is not a number.
    assert first_difference({"a": 1}, {"a": 1.0}) is None
    assert first_difference({"a": 1}, {"a": True}) is not None


def test_root_projection_is_equal_across_environments_and_detects_mutation():
    expected = normalize_root(FAST, fast_root_observation(), "IRONCLAD")
    actual = normalize_root(FULL, full_root_observation(), "IRONCLAD")
    assert first_difference(expected, actual) is None
    # Environment-local handles never enter the compared projection.
    assert "instance_id" not in actual["combat"]["piles"][0]["cards"][0]
    assert "combat_id" not in actual["combat"]["creatures"][0]

    mutated = full_root_observation()
    mutated["combat"]["creatures"][1]["hp"] = 41
    difference = first_difference(expected, normalize_root(FULL, mutated, "IRONCLAD"))
    assert difference is not None and difference.path == "$.combat.creatures[1].hp"


def test_root_projection_requires_the_native_play_phase():
    observation = full_root_observation()
    observation["combat"]["phase"] = "Start"
    from sts2_native_sim.first_combat_differential import DifferentialError, assert_root_boundary

    try:
        assert_root_boundary(observation, FULL, "test root")
    except DifferentialError as error:
        assert "combat.phase == Play" in str(error)
    else:  # pragma: no cover - the boundary must fail closed
        raise AssertionError("a non-Play phase was accepted as the first-combat root")


def test_shipped_side_asserts_declared_encounter_matches_observed_enemies():
    from sts2_native_sim.first_combat_differential import DifferentialError, assert_root_boundary

    observation = full_root_observation()
    observation["combat"]["encounter"]["monster_models"] = ["LEAF_SLIME_S"]
    try:
        assert_root_boundary(observation, FULL, "test root")
    except DifferentialError as error:
        assert "does not match the observed enemy creatures" in str(error)
    else:  # pragma: no cover - the declaration must fail closed
        raise AssertionError("a mismatched encounter declaration was accepted")


def test_identity_layer_covers_the_run_rng_counters():
    fast = fast_root_observation()
    full = full_root_observation()
    fast_run = dict(fast["run"], rng_counters={"Shuffle": 10})
    full_run = dict(full["run"], rng_counters={"Shuffle": 11})
    difference = first_difference(
        normalize_identity(FAST, {**fast, "run": fast_run}, "IRONCLAD"),
        normalize_identity(FULL, {**full, "run": full_run}, "IRONCLAD"),
    )
    assert difference is not None and difference.path == "$.run.rng_counters.Shuffle"


def test_card_identity_uses_copy_occurrence_not_the_local_handle():
    observation = fast_root_observation()
    hand = observation["combat"]["piles"][0]
    hand["cards"] = [
        _card("STRIKE_IRONCLAD", instance_id="a", index=0),
        _card("STRIKE_IRONCLAD", instance_id="b", index=1),
        _card("STRIKE_IRONCLAD", instance_id="c", index=2, upgrades=1),
    ]
    keys = [
        semantic_action(FAST, observation, {"action_id": f"play:{card['instance_id']}", "kind": "play_card", "parameters": {"instance_id": card["instance_id"], "target_id": 1}}).key
        for card in hand["cards"]
    ]
    assert len(set(keys)) == 3, keys
    assert keys[0][1][0] != keys[1][1][0], "two identical copies must not share one identity"

    shipped = full_root_observation()
    shipped["combat"]["piles"][0]["cards"] = hand["cards"]
    shipped_key = semantic_action(
        FULL,
        shipped,
        {"action_id": "play_card:2:target:1", "action_type": "play_card", "metadata": {"card_index": 2, "target_index": 1}},
    ).key
    assert shipped_key == keys[2]


def test_event_options_are_keyed_by_text_key_and_proceed_is_a_wrapper():
    fast = {
        "run": {"rng_counters": {}},
        "decision": {"kind": "event_choice"},
    }
    option = semantic_action(FAST, fast, {"action_id": "choose_event:0", "kind": "choose_event", "parameters": {"text_key": "NEOW.pages.INITIAL.options.NEW_LEAF"}})
    assert option.key == ("event_option", ("NEOW.pages.INITIAL.options.NEW_LEAF",))
    proceed = semantic_action(FAST, fast, {"action_id": "proceed_neow", "kind": "proceed_neow", "parameters": {}})
    assert proceed.wrapper and "proceed" in proceed.key[0]

    shipped = {"phase": "event", "room": {"room_type": "Event", "details": {"finished": True}}, "run": {"rng_counters": {}}}
    shipped_proceed = semantic_action(
        FULL,
        shipped,
        {"action_id": "choose_event:0", "action_type": "choose_event", "metadata": {"text_key": "PROCEED"}},
    )
    assert shipped_proceed.wrapper and shipped_proceed.key == proceed.key


def test_map_and_reward_keys_are_shared_across_environments():
    fast = {"run": {"rng_counters": {}}, "outstanding_choice": {"options": [{"option_id": "o0", "model_id": "GOLD"}]}}
    shipped = {"run": {"rng_counters": {}}, "room": {"room_type": "Rewards", "details": {}}}
    fast_map = semantic_action(FAST, fast, {"action_id": "choose_map:3:1", "kind": "choose_map", "parameters": {"col": 3, "row": 1, "point_type": "Monster"}})
    shipped_map = semantic_action(FULL, shipped, {"action_id": "choose_map:1:Monster", "action_type": "choose_map", "metadata": {"col": 3, "row": 1, "room_type": "Monster"}})
    assert fast_map.key == shipped_map.key == ("map_node", (3, 1, "Monster"))

    fast_relic = semantic_action(FAST, fast, {"action_id": "choose_reward:0:TUNING_FORK", "kind": "choose_reward", "parameters": {"model_id": "TUNING_FORK", "skip": False}})
    shipped_relic = semantic_action(FULL, shipped, {"action_id": "choose_reward:0:Relic", "action_type": "choose_reward", "metadata": {"model_id": "TUNING_FORK"}})
    assert fast_relic.key == shipped_relic.key == ("reward_claim", ("TUNING_FORK",))

    # A claimable reward whose content is chosen on the next screen is a coordinator wrapper.
    shipped_open = semantic_action(FULL, shipped, {"action_id": "choose_reward:0:Card", "action_type": "choose_reward", "metadata": {"model_id": None}})
    assert shipped_open.wrapper and "reward_open" in shipped_open.key[0]
    shipped_skip = semantic_action(FULL, shipped, {"action_id": "proceed", "action_type": "proceed", "metadata": {}})
    assert shipped_skip.key == ("reward_skip", ()) and not shipped_skip.wrapper


def test_unknown_action_kinds_fail_loudly():
    from sts2_native_sim.first_combat_differential import DifferentialError

    try:
        semantic_action(FAST, {"run": {}, "combat": {}}, {"action_id": "buy_shop:0", "kind": "buy_shop", "parameters": {}})
    except DifferentialError as error:
        assert "no semantic action key" in str(error)
    else:  # pragma: no cover - an unmapped kind must fail closed
        raise AssertionError("an unmapped action kind was accepted")


def test_decision_key_set_drops_wrappers_and_smallest_key_policy_is_deterministic():
    observation = fast_root_observation()
    actions = [
        {"action_id": "play:0:target:1", "kind": "play_card", "parameters": {"instance_id": "starter-0-STRIKE_IRONCLAD", "target_id": 1}},
        {"action_id": "proceed_neow", "kind": "proceed_neow", "parameters": {}},
    ]
    keys = semantic_action_keys(FAST, observation, actions)
    assert len(decision_keys_json(keys)) == 1
    assert smallest_key_policy(keys) is keys[0]


def test_schema_declares_every_compared_field_and_reason():
    assert ROOT_SCHEMA["schema_version"] == 1
    assert "combat.piles" in ROOT_SCHEMA["compared_at_combat_boundaries"]
    assert "run.rng_counters" in ROOT_SCHEMA["compared_at_every_boundary"]
    for field, reason in ROOT_SCHEMA["environment_only"].items():
        assert reason, field
    assert "discard_potion" in UNSUPPORTED_KINDS


class FakeFast:
    """A worker whose states are supplied directly, mirroring NativeWorker's differential surface."""

    def __init__(self, states: list[dict]):
        self.states = states
        self.index = 0
        self.build = dict(BUILD)

    def neow_run_reset(self, run_start: dict) -> dict:
        self.index = 0
        return self.states[0]

    def step(self, action_id: str) -> dict:
        self.index += 1
        return self.states[self.index]


class FakeFull:
    def __init__(self, states: list[dict]):
        self.states = states
        self.index = 0
        self.steps: list[str] = []

    def start_run(self, **_: object) -> dict:
        self.index = 0
        return {"observation": self.states[0]["observation"]}

    def observe(self) -> dict:
        return self.states[self.index]["observation"]

    def legal_actions(self) -> list[dict]:
        return self.states[self.index]["legal_actions"]

    def step(self, action_id: str) -> dict:
        self.steps.append(action_id)
        self.index += 1
        return {"observation": self.states[self.index]["observation"]}

    def close(self) -> None:
        return None


def _combat_states() -> tuple[list[dict], list[dict]]:
    """The same logical corridor from two environments with different local action ids."""
    fast_root = fast_root_observation()
    fast_root["decision"] = {"kind": "combat_action"}
    fast_end = fast_root_observation()
    fast_end["combat"]["creatures"][1]["hp"] = 0
    fast_end["combat"]["creatures"][1]["alive"] = False
    fast_end["decision"] = {"kind": "combat_action"}
    fast_states = [
        {
            "observation": fast_root,
            "state_hash": "F0",
            "legal_actions": [
                {"action_id": "play:starter-0-STRIKE_IRONCLAD:target:1", "kind": "play_card", "parameters": {"instance_id": "starter-0-STRIKE_IRONCLAD", "target_id": 1}},
                {"action_id": "end_turn", "kind": "end_turn", "parameters": {}},
            ],
        },
        {
            "observation": fast_end,
            "state_hash": "F1",
            "legal_actions": [{"action_id": "generate_room_rewards", "kind": "generate_room_rewards", "parameters": {}}],
        },
    ]

    full_root = full_root_observation()
    full_root["phase"] = "combat"
    full_root["decision"] = {"kind": "combat_action"}
    full_end = full_root_observation()
    full_end["combat"]["creatures"][1]["hp"] = 0
    full_end["combat"]["creatures"][1]["alive"] = False
    full_end["phase"] = "combat_complete"
    full_end["decision"] = {"kind": "combat_complete"}
    full_states = [
        {
            "observation": full_root,
            "state_hash": "H0",
            "legal_actions": [
                {"action_id": "play_card:0:target:1", "action_type": "play_card", "metadata": {"card_index": 0, "target_index": 1}},
                {"action_id": "end_turn", "action_type": "end_turn", "metadata": {}},
            ],
        },
        {"observation": full_end, "state_hash": "H1", "legal_actions": []},
    ]
    return fast_states, full_states


def test_run_entry_matches_a_full_first_combat_trajectory():
    fast_states, full_states = _combat_states()
    result = run_entry(FakeFast(fast_states), lambda: FakeFull(full_states), seed="SEED", character="IRONCLAD", ascension=0, trajectory=True)
    assert result.status == "match", result.as_record()
    assert result.endpoint == "encounter_cleared"
    assert result.combat_steps == 1


def test_run_entry_reports_the_step_that_diverges():
    fast_states, full_states = _combat_states()
    full_states[1] = {**full_states[1], "observation": {**full_states[1]["observation"], "combat": {**full_states[1]["observation"]["combat"], "energy": 99}}}
    result = run_entry(FakeFast(fast_states), lambda: FakeFull(full_states), seed="SEED", character="IRONCLAD", ascension=0, trajectory=True)
    assert result.status == "mismatch"
    assert result.difference is not None and result.difference["path"] == "$.combat.energy"


def test_run_entry_reports_a_legal_action_set_divergence():
    fast_states, full_states = _combat_states()
    full_states[0] = {**full_states[0], "legal_actions": full_states[0]["legal_actions"][:1]}
    result = run_entry(FakeFast(fast_states), lambda: FakeFull(full_states), seed="SEED", character="IRONCLAD", ascension=0, trajectory=True)
    assert result.status == "mismatch" and result.stage == "legal_actions"

def test_aggregate_accounts_for_every_status_and_cell():
    results = [
        EntryResult(seed="a", character="IRONCLAD", ascension=0, status="match", boundaries=3, combat_steps=2, endpoint="encounter_cleared"),
        EntryResult(seed="b", character="IRONCLAD", ascension=0, status="mismatch", stage="projection", unsupported=["discard_potion"]),
        EntryResult(seed="c", character="SILENT", ascension=10, status="error", stage="worker"),
    ]
    report = aggregate(results)
    assert report["entries"] == 3
    assert report["status_counts"] == {"error": 1, "match": 1, "mismatch": 1}
    assert report["character_ascension_cells"]["IRONCLAD|A0"] == {"match": 1, "mismatch": 1}
    assert report["compared_combat_steps"] == 2
    assert report["unsupported_kinds"] == ["discard_potion"]
    assert report["global_certification"] is False
    assert "not a simulator certification" in report["scope"]
