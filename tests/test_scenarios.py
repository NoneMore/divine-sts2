"""Offline tests for the generated scenario record, through its public interface.

`sts2_native_sim.scenarios.generate_rows` is the seam: a request goes in, rows come out.
Everything asserted here is a property of the rows — including the batch behaviour, which is
asserted through the same seam rather than by calling an expansion helper — so the
generator's internal loop is free to change. The run it drives is a fake worker built from
the captures in `tests/fixtures/canonical-observations.json` — recorded from the
shipped-game-backed native worker — so the record is built from the shape a real capture has,
and the combat block's schema check is a real one rather than a parse of a hand-written stub.

A request is the product of the characters, Ascensions and run seeds it declares, plus one
dimension the run itself supplies: the Ancient choices the seed's run offers. The fake routes
every step by action id, every offered choice included, so an action the run never offered is
a `KeyError` rather than a silent success — which is what makes "a seed records exactly the
choices its run offers" and "the fixed rule picked *this* node" observations about the
generator instead of assumptions about the double.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Self

import pytest
from sts2_native_sim.scenarios import (
    ROW_SCHEMA,
    SCENARIO_RECORD,
    RunWorker,
    ScenarioGenerationError,
    ScenarioRequest,
    ScenarioRequestError,
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
        takeable: tuple[str, ...] | None = None,
        nested: tuple[dict[str, Any], ...] = (),
        nested_choice: int = 0,
        row_one: str = "combat",
        leave: str = "run_map_after_ancient",
    ) -> None:
        self.offer = list(offer)
        #: The offered relics that also have a legal action. The event reports every one of
        #: `offer`; a `takeable` that disagrees with it is the environment contradicting itself,
        #: which is what the generator is expected to refuse rather than paper over.
        self.takeable = list(offer if takeable is None else takeable)
        self.nested = [copy.deepcopy(state) for state in nested]
        #: Which offered choice opens the nested prompts: a prompt belongs to one choice, not to
        #: all of them.
        self.nested_choice = nested_choice
        self.row_one = row_one
        self.leave = leave
        self.reset_request: dict[str, Any] | None = None
        self.steps: list[str] = []
        self.last_hash: str | None = None
        self._routes: dict[str, dict[str, Any]] = {}

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
        # Every takeable choice is routeable: the generator takes each of them in turn.
        for index, relic in self._choice_indices().items():
            if relic in self.takeable:
                self._routes[self._choice_action(index, relic)] = (
                    target if index == self.nested_choice else self._patched("run_event_complete")
                )
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
        # A hash is a function of the state, so the same capture hashes alike across drives —
        # which is what makes "the recorded hash is the fight's own" observable.
        digest = hashlib.sha256(json.dumps(observation, sort_keys=True).encode("utf-8")).hexdigest()[:16].upper()
        self.last_hash = f"state-hash-{digest}"
        return _result(observation, self.last_hash)

    def _patched(self, name: str) -> dict[str, Any]:
        observation = copy.deepcopy(CAPTURES[name])
        if self.reset_request is not None:
            observation["run"]["seed"] = self.reset_request["seed"]
            observation["run"]["ascension"] = self.reset_request["ascension"]
        return observation

    def _choice_indices(self) -> dict[int, str]:
        """Every choice this double can mention, by the option index each reports."""
        return dict(enumerate(list(self.offer) + [relic for relic in self.takeable if relic not in self.offer]))

    def _choice_action(self, index: int, relic: str) -> str:
        return f"choose_event:{index}:NEOW.pages.INITIAL.options.{relic}"

    def _event_choice(self) -> dict[str, Any]:
        options, actions = [], []
        for index, relic in self._choice_indices().items():
            text_key = f"NEOW.pages.INITIAL.options.{relic}"
            if relic in self.offer:
                options.append({
                    "option_index": index, "text_key": text_key, "locked": False,
                    "chosen": False, "is_proceed": False, "relic_model_id": relic,
                })
            if relic in self.takeable:
                actions.append({
                    "action_id": self._choice_action(index, relic), "kind": "choose_event",
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
    """One element per dimension: the batch machinery is asserted by its own tests."""
    return ScenarioRequest(characters=(character,), ascensions=(ascension,), seeds=(seed,))


def _rows(worker: RunWorker | None = None, **worker_options: Any) -> list[dict[str, Any]]:
    """Every row the default one-element request produces: one per Ancient choice offered."""
    return generate_rows(_request(), worker or FakeRunWorker(**worker_options))


def _row(worker: RunWorker | None = None, **worker_options: Any) -> dict[str, Any]:
    """The row the default request records for the first Ancient choice it offers."""
    return _rows(worker, **worker_options)[0]


def _element(row: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """What one row is an element of the request: character, Ascension, seed, Ancient choice."""
    recipe = row["recipe"]
    return (recipe["character"], recipe["ascension"], recipe["seed"], recipe["ancient_choice"]["option_index"])


# -- the row envelope and the recipe -----------------------------------------------------


def test_a_request_records_one_scenario_row_with_the_declared_envelope() -> None:
    row = _row()

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
    canonical = _row()
    assert canonical["recipe"]["seed"] == SEED
    assert "raw_seed" not in canonical["recipe"], "an already-canonical seed records no diagnostic"

    # `SeedHelper.CanonicalizeSeed` in one sample: upper-case, `O` → `0`, `I` → `1`, then trim.
    for raw in ("ANCIENT01", "  ancient0i "):
        row = generate_rows(_request(raw), FakeRunWorker())[0]
        assert row["recipe"]["seed"] == SEED
        assert row["recipe"]["raw_seed"] == raw
        # The canonical form is what the run was started with, so the record and the run agree.
        assert row["combat_initial_state"]["run"]["seed"] == SEED


def test_every_offered_ancient_choice_is_taken_in_turn_and_recorded_in_offer_order() -> None:
    offer = ("HEFTY_TABLET", "FISHING_ROD", "SILKEN_TRESS")
    worker = FakeRunWorker(offer=offer, nested=(_card_choice("card-choice-0", "card-choice-1"),))

    rows = _rows(worker=worker)

    offered = [{"option_index": index, "relic_model_id": relic} for index, relic in enumerate(offer)]
    assert [row["recipe"]["ancient_options"] for row in rows] == [offered] * len(offer)
    assert [row["recipe"]["ancient_choice"] for row in rows] == offered
    # Each choice is taken from its own drive of the run, in the order the run offered them.
    assert [step for step in worker.steps if step.startswith("choose_event")] == [
        f"choose_event:{index}:NEOW.pages.INITIAL.options.{relic}" for index, relic in enumerate(offer)
    ]
    assert worker.steps[:5] == [
        ANCIENT_ACTION,
        "choose_event:0:NEOW.pages.INITIAL.options.HEFTY_TABLET",
        "card-choice-0",
        "leave_event",
        FIRST_ROW_ONE_ACTION,
    ]


def test_the_row_one_node_is_the_first_reported_map_action_and_its_coordinate_is_recorded() -> None:
    worker = FakeRunWorker()
    row = _row(worker=worker)

    assert worker.steps[-1] == FIRST_ROW_ONE_ACTION
    assert row["recipe"]["node"] == {"col": 0, "row": 1, "point_type": "Monster"}


def test_the_act_variant_is_the_one_the_run_played() -> None:
    row = _row()

    assert row["recipe"]["act_variant"] == CAPTURES["run_combat_action"]["run"]["act_variant"]


# -- the batch: expansion, canonicalisation and collision --------------------------------


def test_a_batch_request_records_one_row_per_element_in_the_declared_order() -> None:
    request = ScenarioRequest(
        characters=("DEFECT", "IRONCLAD"),
        ascensions=(2, 0),
        seeds=("SEED2", "SEED1"),
    )

    rows = generate_rows(request, FakeRunWorker())

    assert len(rows) == 2 * 2 * 2 * len(RECORDED_OFFER)
    assert [_element(row) for row in rows] == [
        (character, ascension, seed, choice_index)
        for character in ("DEFECT", "IRONCLAD")
        for ascension in (2, 0)
        for seed in ("SEED2", "SEED1")
        for choice_index in range(len(RECORDED_OFFER))
    ]


def test_a_request_may_be_declared_with_lists_and_reads_back_in_the_declared_order() -> None:
    request = ScenarioRequest(characters=["ironclad"], ascensions=[2, 0], seeds=["SEED1"])

    assert (request.characters, request.ascensions, request.seeds) == (("ironclad",), (2, 0), ("SEED1",))


def test_a_seed_records_exactly_the_ancient_choices_its_run_offers() -> None:
    """The double reports the offer twice — as the event's options and as legal actions — and the
    two disagreement tests below show the generator refuses the request when they disagree, so a
    row per reported option here is not the generator grading itself."""
    for offer in (("LAVA_ROCK",), ("LAVA_ROCK", "PHIAL_HOLSTER"), RECORDED_OFFER):
        rows = _rows(offer=offer)
        offered = [{"option_index": index, "relic_model_id": relic} for index, relic in enumerate(offer)]

        assert len(rows) == len(offer)
        assert [row["recipe"]["ancient_choice"] for row in rows] == offered
        assert [row["recipe"]["ancient_options"] for row in rows] == [offered] * len(offer)


def test_a_reported_choice_no_action_can_take_fails_rather_than_being_skipped() -> None:
    worker = FakeRunWorker(takeable=("LAVA_ROCK", "PHIAL_HOLSTER"))

    with pytest.raises(ScenarioGenerationError) as raised:
        generate_rows(_request(), worker)

    assert raised.value.stage == "ancient_choice"
    assert "option 2" in str(raised.value) and "no legal action" in str(raised.value)


def test_a_choice_the_event_does_not_report_fails_rather_than_being_taken() -> None:
    worker = FakeRunWorker(
        offer=("LAVA_ROCK", "PHIAL_HOLSTER"), takeable=("LAVA_ROCK", "PHIAL_HOLSTER", "SILKEN_TRESS")
    )

    with pytest.raises(ScenarioGenerationError) as raised:
        generate_rows(_request(), worker)

    assert raised.value.stage == "ancient_choice"
    assert "does not report" in str(raised.value)


def test_two_records_for_one_seed_share_the_run_and_differ_in_the_ancient_choice() -> None:
    """The choice is the dimension the rows differ by; what it resolved belongs to its own row.

    A nested choice is that choice's consequence rather than a second dimension, so the rows share
    everything that identifies the run — character, Ascension, seed, Act variant, the offer, the
    node and the encounter — and differ in the choice and in the prompts it opened.
    """
    worker = FakeRunWorker(nested=(_card_choice("card-choice-0", "card-choice-1"),), nested_choice=1)

    rows = _rows(worker=worker)

    assert [row["recipe"]["ancient_choice"] for row in rows] == rows[0]["recipe"]["ancient_options"]
    assert [row["recipe"]["nested_choices"] for row in rows] == [
        [],
        [{"kind": "card_choice", "selected_index": 0, "selected_option_ids": ["card-choice-0"]}],
        [],
    ]
    shared = ("character", "ascension", "seed", "act_variant", "ancient_options", "node", "encounter")
    for row in rows[1:]:
        assert {key: row["recipe"][key] for key in shared} == {key: rows[0]["recipe"][key] for key in shared}


def test_a_batch_canonicalises_every_seed_and_keeps_each_raw_form_beside_it() -> None:
    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("ANCIENT01", "SCENAR10A01"))

    rows = generate_rows(request, FakeRunWorker())

    rewritten = [row for row in rows if row["recipe"]["seed"] == SEED]
    untouched = [row for row in rows if row["recipe"]["seed"] != SEED]
    assert len(rewritten) == len(RECORDED_OFFER) and len(untouched) == len(RECORDED_OFFER)
    assert {row["recipe"]["raw_seed"] for row in rewritten} == {"ANCIENT01"}
    assert all("raw_seed" not in row["recipe"] for row in untouched)
    assert all(row["combat_initial_state"]["run"]["seed"] == row["recipe"]["seed"] for row in rows)


def test_two_seeds_that_canonicalise_alike_fail_the_request_and_drive_nothing() -> None:
    worker = FakeRunWorker()
    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("ANCIENT01", "anc1ent01"))

    with pytest.raises(ScenarioRequestError) as raised:
        generate_rows(request, worker)

    message = str(raised.value)
    assert "ANCIENT01" in message and "anc1ent01" in message and SEED in message
    assert worker.reset_request is None, "a rejected request started a run"
    assert worker.steps == [], "a rejected request drove a run"


def test_a_seed_declared_twice_is_rejected_rather_than_recorded_twice() -> None:
    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("GYMSCENAR10", "GYMSCENAR10"))

    with pytest.raises(ScenarioRequestError):
        generate_rows(request, FakeRunWorker())


def test_a_character_declared_in_two_cases_is_rejected_rather_than_recorded_twice() -> None:
    request = ScenarioRequest(characters=("ironclad", "IRONCLAD"), ascensions=(0,), seeds=(SEED,))

    with pytest.raises(ScenarioRequestError) as raised:
        generate_rows(request, FakeRunWorker())

    assert "ironclad" in str(raised.value) and "IRONCLAD" in str(raised.value)


def test_a_request_that_declares_no_seed_is_refused_rather_than_quietly_empty() -> None:
    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=())

    with pytest.raises(ScenarioRequestError):
        generate_rows(request, FakeRunWorker())


def test_every_row_a_batch_emits_carries_a_capture_the_published_schema_describes() -> None:
    request = ScenarioRequest(characters=("IRONCLAD", "DEFECT"), ascensions=(0,), seeds=("SEED1", "SEED2"))

    rows = generate_rows(request, FakeRunWorker())

    assert len(rows) == 2 * 2 * len(RECORDED_OFFER)
    for row in rows:
        assert row["schema"] == ROW_SCHEMA and row["record_type"] == SCENARIO_RECORD
        validate_observation(row["combat_initial_state"])


# -- the nested-choice rule --------------------------------------------------------------


def test_a_nested_prompt_is_resolved_by_the_first_legal_action_and_recorded() -> None:
    worker = FakeRunWorker(offer=("HEFTY_TABLET", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_card_choice("card-choice-0", "card-choice-1"),))
    row = _row(worker=worker)

    assert row["recipe"]["nested_choices"] == [{
        "kind": "card_choice",
        "selected_index": 0,
        "selected_option_ids": ["card-choice-0"],
    }]


def test_a_nested_reward_pick_is_recorded_by_the_index_it_selected() -> None:
    worker = FakeRunWorker(offer=("NEW_LEAF", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_reward_choice(),))
    row = _row(worker=worker)

    # A reward pick names a reward index rather than option ids, so the index is the selection.
    assert row["recipe"]["nested_choices"] == [{
        "kind": "custom_reward_choice",
        "selected_index": 0,
        "selected_option_ids": [],
    }]


def test_a_nested_bundle_pick_records_the_options_it_selected() -> None:
    worker = FakeRunWorker(offer=("SCROLL_BOXES", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_bundle_choice("bundle-0", "bundle-1"),))
    row = _row(worker=worker)

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
    row = _row(worker=FakeRunWorker(offer=("SILKEN_TRESS", "FISHING_ROD", "LAVA_ROCK")))

    assert row["recipe"]["nested_choices"] == []


# -- the combat initial state ------------------------------------------------------------


def test_the_row_carries_the_full_combat_initial_state() -> None:
    worker = FakeRunWorker()
    row = _row(worker=worker)
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
    row = _row()

    validate_observation(row["combat_initial_state"])


# -- a record, not a snapshot ------------------------------------------------------------


def test_the_same_request_run_twice_produces_the_same_record() -> None:
    first = generate_rows(_request("ancient01"), FakeRunWorker())
    second = generate_rows(_request("ancient01"), FakeRunWorker())

    assert first == second


def test_the_record_stores_no_state_handle_and_no_portable_branch() -> None:
    row = _row()

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


def test_the_console_entry_point_writes_every_row_of_the_batch_it_generates(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sts2_native_sim import cli

    monkeypatch.setattr(cli, "NativeWorker", lambda **_: FakeRunWorker())
    with pytest.raises(SystemExit) as raised:
        cli.main([
            "scenario",
            "--character", "IRONCLAD",
            "--character", "DEFECT",
            "--ascension", "0",
            "--seed", "ancient01",
        ])
    assert raised.value.code == 0

    request = ScenarioRequest(characters=("IRONCLAD", "DEFECT"), ascensions=(0,), seeds=("ancient01",))
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert [json.loads(line) for line in lines] == generate_rows(request, FakeRunWorker())


def test_the_console_entry_point_refuses_a_colliding_request_without_writing_anything(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sts2_native_sim import cli

    written: list[Any] = []
    monkeypatch.setattr(cli, "NativeWorker", lambda **_: FakeRunWorker())
    monkeypatch.setattr(cli, "_write_rows", lambda rows, output: written.append(rows))

    with pytest.raises(SystemExit) as raised:
        cli.main(["scenario", "--character", "IRONCLAD", "--seed", "ANCIENT01", "--seed", "anc1ent01"])

    assert raised.value.code == 2
    assert written == [], "a rejected request wrote output"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ANCIENT01" in captured.err and "anc1ent01" in captured.err
