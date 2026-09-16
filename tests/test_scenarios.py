"""Offline tests for the generated scenario record, through its public interface.

`sts2_native_sim.scenarios.generate_rows` is the seam: a request goes in, rows come out.
Everything asserted here is a property of the rows, so the generator's internal loop is
free to change. The run it drives is a fake worker built from the captures in
`tests/fixtures/canonical-observations.json` — recorded from the shipped-game-backed native
worker — so the record is built from the shape a real capture has, and the combat block's
schema check is a real one rather than a parse of a hand-written stub.

The fake routes every step by action id: an action the run never offered is a `KeyError`
rather than a silent success, which is what makes "the fixed rule picked *this* node" an
observation about the generator instead of an assumption about the double.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Self

import pytest
from sts2_native_sim.scenarios import (
    ROW_SCHEMA,
    SCENARIO_RECORD,
    ScenarioGenerationError,
    ScenarioRequest,
    generate_rows,
)
from sts2_native_sim.schema import validate_observation

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "canonical-observations.json"
CAPTURES: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

#: `StandardActMap`'s starting point, typed `Ancient` on a fully unlocked run.
ANCIENT_ACTION = "choose_map:3:0"
#: The row-1 monster nodes the act map reports after the Ancient room.
ROW_ONE_ACTIONS = ("choose_map:0:1", "choose_map:3:1", "choose_map:5:1")
#: The first row-1 node, which is the one the documented rule takes.
FIRST_ROW_ONE_ACTION = ROW_ONE_ACTIONS[0]
#: The relic ids the fixture's recorded Ancient room offered, in offer order.
RECORDED_OFFER = ("LAVA_ROCK", "PHIAL_HOLSTER", "SILKEN_TRESS")
#: The canonical seed the sample request uses. `ANCIENT01` is *not* canonical — the shipped
#: transform rewrites its `I` — which makes it the natural non-canonical sample.
SEED = "ANC1ENT01"


def _result(observation: dict[str, Any], state_hash: str) -> dict[str, Any]:
    """One `run_step`/`run_reset` result, in the shape the environment returns."""
    return {
        "observation": observation,
        "state_hash": state_hash,
        "state_handle": f"state-handle-for-{state_hash}",
        "legal_actions": observation["decision"]["legal_actions"],
        "terminal": bool(observation.get("terminal", False)),
        "victory": bool(observation.get("victory", False)),
    }


class FakeRunWorker:
    """The run-mode decision chain one scenario generation walks, keyed by action id."""

    def __init__(
        self,
        *,
        offer: tuple[str, ...] = RECORDED_OFFER,
        nested: tuple[dict[str, Any], ...] = (),
        row_one: str = "combat",
        leave: str = "run_map_after_ancient",
    ) -> None:
        self.offer = list(offer)
        self.nested = [copy.deepcopy(state) for state in nested]
        self.row_one = row_one
        self.leave = leave
        self.reset_request: dict[str, Any] | None = None
        self.steps: list[str] = []
        self.last_hash: str | None = None
        self._routes: dict[str, dict[str, Any]] = {}
        self._ordinal = 0

    # -- the seam the generator uses -----------------------------------------------------

    def run_reset(self, state: dict[str, Any]) -> dict[str, Any]:
        self.reset_request = copy.deepcopy(state)
        observation = copy.deepcopy(CAPTURES["run_map_choice"])
        observation["run"]["seed"] = state["seed"]
        observation["run"]["ascension"] = state["ascension"]
        # The chosen choice opens the nested prompts in order; the last of them hands the
        # event back completed. A choice that opens none completes immediately.
        target = self._patched("run_event_complete")
        for nested in reversed(self.nested):
            self._routes[nested["decision"]["legal_actions"][0]["action_id"]] = target
            target = nested
        self._routes[self._choice_action()] = target
        self._routes["leave_event"] = self._patched(self.leave)
        if self.row_one == "combat":
            # Only the first row-1 node is routed: taking a later one is not the documented
            # rule, and this is where that shows up.
            self._routes[FIRST_ROW_ONE_ACTION] = self._patched("run_combat_action")
        else:
            self._routes[FIRST_ROW_ONE_ACTION] = self._patched("run_event_choice")
        self._routes[ANCIENT_ACTION] = self._event_choice()
        return self._next(observation)

    def run_step(self, action_id: str) -> dict[str, Any]:
        self.steps.append(action_id)
        return self._next(self._routes[action_id])

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    # -- the run's own captures ----------------------------------------------------------

    def _next(self, observation: dict[str, Any]) -> dict[str, Any]:
        self._ordinal += 1
        self.last_hash = f"state-hash-{self._ordinal}"
        return _result(observation, self.last_hash)

    def _patched(self, name: str) -> dict[str, Any]:
        observation = copy.deepcopy(CAPTURES[name])
        if self.reset_request is not None:
            observation["run"]["seed"] = self.reset_request["seed"]
            observation["run"]["ascension"] = self.reset_request["ascension"]
        return observation

    def _choice_action(self) -> str:
        return f"choose_event:0:NEOW.pages.INITIAL.options.{self.offer[0]}"

    def _event_choice(self) -> dict[str, Any]:
        options, actions = [], []
        for index, relic in enumerate(self.offer):
            text_key = f"NEOW.pages.INITIAL.options.{relic}"
            options.append({
                "option_index": index, "text_key": text_key, "locked": False,
                "chosen": False, "is_proceed": False, "relic_model_id": relic,
            })
            actions.append({
                "action_id": f"choose_event:{index}:{text_key}", "kind": "choose_event",
                "parameters": {
                    "option_index": index, "text_key": text_key,
                    "is_proceed": False, "relic_model_id": relic,
                },
            })
        observation = self._patched("run_event_choice")
        observation["event"] = {"model_id": "NEOW", "options": options, "finished": False}
        observation["decision"] = {"kind": "event_choice", "legal_actions": actions}
        return observation


def _card_choice(*action_ids: str) -> dict[str, Any]:
    """A nested card select offering one `choose_cards` action per card."""
    actions = [
        {
            "action_id": action_id, "kind": "choose_cards",
            "parameters": {"choice_id": "card-choice-0", "option_ids": [action_id]},
        }
        for action_id in action_ids
    ]
    return {
        "schema_version": 3, "game_build": {}, "run": {"seed": SEED, "ascension": 0, "act_variant": "OVERGROWTH", "rng_counters": {}},
        "outstanding_choice": {
            "choice_id": "card-choice-0", "kind": "choose_cards", "min_select": 1, "max_select": 1,
            "provenance": "native", "options": [{"option_id": action_id, "model_id": "ANGER"} for action_id in action_ids],
        },
        "decision": {"kind": "card_choice", "legal_actions": actions},
        "terminal": False, "victory": False,
    }


def _bundle_choice(*option_ids: str) -> dict[str, Any]:
    """A nested bundle pick: `choose_option` actions, each naming the option it selects."""
    actions = [
        {
            "action_id": f"choose_option:card-choice-0:{option_id}", "kind": "choose_option",
            "parameters": {"choice_id": "card-choice-0", "option_ids": [option_id]},
        }
        for option_id in option_ids
    ]
    return {
        "schema_version": 3, "game_build": {}, "run": {"seed": SEED, "ascension": 0, "act_variant": "OVERGROWTH", "rng_counters": {}},
        "outstanding_choice": {
            "choice_id": "card-choice-0", "kind": "choose_option", "min_select": 1, "max_select": 1,
            "provenance": "native",
            "options": [{"option_id": option_id, "cards": [{"model_id": "ANGER"}]} for option_id in option_ids],
        },
        "decision": {"kind": "option_choice", "legal_actions": actions},
        "terminal": False, "victory": False,
    }


def _silent_card_choice() -> dict[str, Any]:
    """A card select whose action names no option ids: the environment never does this."""
    state = _card_choice("card-choice-0")
    state["decision"]["legal_actions"][0]["parameters"] = {"choice_id": "card-choice-0"}
    return state


def _reward_choice() -> dict[str, Any]:
    """A nested reward set: two rewards to take, and a skip the run also allows."""
    actions = [
        {
            "action_id": f"choose_custom_reward:{index}:-1:0:gold:none", "kind": "choose_custom_reward",
            "parameters": {"reward_index": index, "child_index": -1, "option_index": 0, "reward_kind": "gold", "model_id": None},
        }
        for index in range(2)
    ]
    actions.append({"action_id": "skip_custom_rewards", "kind": "skip_custom_rewards", "parameters": {}})
    return {
        "schema_version": 3, "game_build": {}, "run": {"seed": SEED, "ascension": 0, "act_variant": "OVERGROWTH", "rng_counters": {}},
        "custom_rewards": {
            "rewards": [
                {"reward_index": index, "reward": {"kind": "gold", "implementation": "GoldReward", "selected": False}, "children": []}
                for index in range(2)
            ],
            "can_skip": True, "depth": 1,
        },
        "decision": {"kind": "custom_reward_choice", "legal_actions": actions},
        "terminal": False, "victory": False,
    }


def _request(seed: str = SEED, ascension: int = 0, character: str = "IRONCLAD") -> ScenarioRequest:
    return ScenarioRequest(character=character, ascension=ascension, seed=seed)


def _one_row(**kwargs: Any) -> dict[str, Any]:
    rows = generate_rows(_request(), kwargs.pop("worker", None) or FakeRunWorker(**kwargs))
    assert len(rows) == 1, "one request records exactly one scenario for now"
    return rows[0]


# -- the row envelope and the recipe -----------------------------------------------------


def test_a_request_records_one_scenario_row_with_the_declared_envelope() -> None:
    row = _one_row()

    assert row["schema"] == ROW_SCHEMA
    assert row["record_type"] == SCENARIO_RECORD
    assert set(row["game_build"]) == {"version", "assembly_sha256", "pck_sha256"}
    assert row["recipe"]["character"] == "IRONCLAD"
    assert row["recipe"]["ascension"] == 0
    assert row["recipe"]["encounter"] == CAPTURES["run_combat_action"]["combat"]["encounter"]


def test_the_recorded_character_is_the_model_id_the_run_was_started_as() -> None:
    """The environment looks a character up case-insensitively, so the record names the resolved id."""
    worker = FakeRunWorker()
    row = generate_rows(_request(character="ironclad"), worker)[0]

    assert row["recipe"]["character"] == "IRONCLAD"
    assert worker.reset_request is not None and worker.reset_request["character"] == "IRONCLAD"


def test_the_recorded_seed_is_canonical_and_the_raw_seed_is_kept_only_when_it_differed() -> None:
    canonical = _one_row()
    assert canonical["recipe"]["seed"] == SEED
    assert "raw_seed" not in canonical["recipe"], "an already-canonical seed records no diagnostic"

    # `SeedHelper.CanonicalizeSeed` in one sample: upper-case, `O` → `0`, `I` → `1`, then trim.
    for raw in ("ANCIENT01", "  ancient0i "):
        row = generate_rows(_request(raw), FakeRunWorker())[0]
        assert row["recipe"]["seed"] == SEED
        assert row["recipe"]["raw_seed"] == raw
        # The canonical form is what the run was started with, so the record and the run agree.
        assert row["combat_initial_state"]["run"]["seed"] == SEED


def test_the_offered_ancient_options_keep_offer_order_and_the_first_one_is_taken() -> None:
    offer = ("HEFTY_TABLET", "FISHING_ROD", "SILKEN_TRESS")
    worker = FakeRunWorker(offer=offer, nested=(_card_choice("card-choice-0", "card-choice-1"),))
    row = _one_row(worker=worker)

    assert row["recipe"]["ancient_options"] == [
        {"option_index": index, "relic_model_id": relic} for index, relic in enumerate(offer)
    ]
    assert row["recipe"]["ancient_choice"] == {"option_index": 0, "relic_model_id": "HEFTY_TABLET"}
    assert worker.steps == [
        ANCIENT_ACTION,
        "choose_event:0:NEOW.pages.INITIAL.options.HEFTY_TABLET",
        "card-choice-0",
        "leave_event",
        FIRST_ROW_ONE_ACTION,
    ]


def test_the_row_one_node_is_the_first_reported_map_action_and_its_coordinate_is_recorded() -> None:
    worker = FakeRunWorker()
    row = _one_row(worker=worker)

    assert worker.steps[-1] == FIRST_ROW_ONE_ACTION
    assert row["recipe"]["node"] == {"col": 0, "row": 1, "point_type": "Monster"}


def test_the_act_variant_is_the_one_the_run_played() -> None:
    row = _one_row()

    assert row["recipe"]["act_variant"] == CAPTURES["run_combat_action"]["run"]["act_variant"]


# -- the nested-choice rule --------------------------------------------------------------


def test_a_nested_prompt_is_resolved_by_the_first_legal_action_and_recorded() -> None:
    worker = FakeRunWorker(offer=("HEFTY_TABLET", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_card_choice("card-choice-0", "card-choice-1"),))
    row = _one_row(worker=worker)

    assert row["recipe"]["nested_choices"] == [{
        "kind": "card_choice",
        "selected_index": 0,
        "selected_option_ids": ["card-choice-0"],
    }]


def test_a_nested_reward_pick_is_recorded_by_the_index_it_selected() -> None:
    worker = FakeRunWorker(offer=("NEW_LEAF", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_reward_choice(),))
    row = _one_row(worker=worker)

    # A reward pick names a reward index rather than option ids, so the index is the selection.
    assert row["recipe"]["nested_choices"] == [{
        "kind": "custom_reward_choice",
        "selected_index": 0,
        "selected_option_ids": [],
    }]


def test_a_nested_bundle_pick_records_the_options_it_selected() -> None:
    worker = FakeRunWorker(offer=("SCROLL_BOXES", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_bundle_choice("bundle-0", "bundle-1"),))
    row = _one_row(worker=worker)

    assert row["recipe"]["nested_choices"] == [{
        "kind": "option_choice",
        "selected_index": 0,
        "selected_option_ids": ["bundle-0"],
    }]


def test_a_nested_selection_that_names_no_option_ids_fails_rather_than_recording_nothing() -> None:
    worker = FakeRunWorker(offer=("HEFTY_TABLET", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_silent_card_choice(),))

    with pytest.raises(ScenarioGenerationError) as raised:
        generate_rows(_request(), worker)

    assert raised.value.stage == "ancient_choice"
    assert "option ids" in str(raised.value)


def test_a_choice_that_opens_no_prompt_records_no_nested_choice() -> None:
    row = _one_row(worker=FakeRunWorker(offer=("SILKEN_TRESS", "FISHING_ROD", "LAVA_ROCK")))

    assert row["recipe"]["nested_choices"] == []


# -- the combat initial state ------------------------------------------------------------


def test_the_row_carries_the_full_combat_initial_state() -> None:
    worker = FakeRunWorker()
    row = _one_row(worker=worker)
    state = row["combat_initial_state"]
    capture = CAPTURES["run_combat_action"]

    # The enemies with their generated HP, and nothing invented.
    enemies = [c for c in state["combat"]["creatures"] if c["side"] == "Enemy"]
    assert enemies == [c for c in capture["combat"]["creatures"] if c["side"] == "Enemy"]
    assert enemies and all(isinstance(enemy["hp"], int) for enemy in enemies)

    # The player's row carries the player's HP, which a combat capture does not repeat in `run`.
    player = [c for c in state["combat"]["creatures"] if c["side"] == "Player"]
    assert len(player) == 1 and player[0]["hp"] > 0
    assert player[0] == next(c for c in capture["combat"]["creatures"] if c["side"] == "Player")

    # Every ordered pile, the hand and the draw pile included, in the order the fight reports.
    assert [pile["name"] for pile in state["combat"]["piles"]] == [
        "Hand", "DrawPile", "DiscardPile", "ExhaustPile", "PlayPile",
    ]
    assert state["combat"]["piles"] == capture["combat"]["piles"]

    # The relics and the potions by slot, and the run's gold and named counters.
    assert state["inventory"] == capture["inventory"]
    assert state["run"]["gold"] == capture["run"]["gold"]
    assert state["combat"]["turn"] == capture["combat"]["turn"]
    assert state["run"]["rng_counters"]
    assert state["run"]["rng_counters"] == capture["run"]["rng_counters"]

    assert row["state_hash"] == worker.last_hash, "the recorded hash is not the fight's own"


def test_the_combat_initial_state_is_a_capture_the_published_schema_describes() -> None:
    row = _one_row()

    validate_observation(row["combat_initial_state"])


# -- a record, not a snapshot ------------------------------------------------------------


def test_the_same_request_run_twice_produces_the_same_record() -> None:
    first = generate_rows(_request("ancient01"), FakeRunWorker())
    second = generate_rows(_request("ancient01"), FakeRunWorker())

    assert first == second


def test_the_record_stores_no_state_handle_and_no_portable_branch() -> None:
    row = _one_row()

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in {"state_handle", "reset", "reset_request", "history", "expected_hash"}, (
                    f"{path}.{key} is a simulator handle or a portable branch"
                )
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(row, "$")
    assert "state-hash" in json.dumps(row), "the state hash is recorded, as the ticket asks"


# -- failing closed ----------------------------------------------------------------------


def test_a_run_that_does_not_reach_a_fight_fails_at_the_stage_it_stopped_at() -> None:
    with pytest.raises(ScenarioGenerationError) as raised:
        generate_rows(_request(), FakeRunWorker(row_one="event"))

    assert raised.value.stage == "first_combat"
    assert "event_choice" in str(raised.value)


def test_a_room_that_does_not_hand_back_the_map_fails_at_the_leaving_stage() -> None:
    with pytest.raises(ScenarioGenerationError) as raised:
        generate_rows(_request(), FakeRunWorker(leave="run_event_choice"))

    assert raised.value.stage == "leave_ancient"
    assert "event_choice" in str(raised.value)


# -- the console entry point -------------------------------------------------------------


def test_the_console_entry_point_writes_the_record_it_generates(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sts2_native_sim import cli

    monkeypatch.setattr(cli, "NativeWorker", lambda **_: FakeRunWorker())
    with pytest.raises(SystemExit) as raised:
        cli.main(["scenario", "--character", "IRONCLAD", "--ascension", "0", "--seed", "ancient01"])
    assert raised.value.code == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert [json.loads(line) for line in lines] == generate_rows(_request("ancient01"), FakeRunWorker())
