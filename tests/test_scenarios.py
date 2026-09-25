"""Offline tests for the generated scenario record, through its public interfaces.

Two seams, and every test is written at one of them. `sts2_native_sim.scenarios.generate_rows`
turns a request into rows; `sts2_native_sim.scenarios.generate_corpus` turns a request and a
worker count into a corpus in an artifact root. Everything asserted here is a property of what
comes out of one of those two — including the batch behaviour, which is asserted through the same
seams rather than by calling an expansion helper — so the generator's internal loop is free to
change. The run it drives is a fake worker built from the captures in
`tests/fixtures/canonical-observations.json` — recorded from the shipped-game-backed native worker
— so the record is built from the shape a real capture has, and the combat block's schema check is
a real one rather than a parse of a hand-written stub.

A request is the product of the characters, Ascensions and run seeds it declares, plus one
dimension the run itself supplies: the Ancient choices the seed's run offers. The fake routes
every step by action id, every offered choice included, so an action the run never offered is
a `KeyError` rather than a silent success — which is what makes "a seed records exactly the
choices its run offers" and "the fixed rule picked *this* node" observations about the
generator instead of assumptions about the double. It can be told to fail one step — which is
how an element that cannot produce a scenario is forced, a failure being a row of the corpus
rather than an exception escaping the batch — or to die on one step, which is how a crashed
worker is forced; it can also be told to be slow, which is how a deliberately late worker is,
or to serve a fight with a floating-point quantity in it, which is how a state the record
cannot hold is forced.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import shutil
import tempfile
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Self

import pytest
from sts2_native_sim import _scenario_corpus, scenarios
from sts2_native_sim.client import NativeSimError
from sts2_native_sim.pck_fingerprint import PckFingerprint
from sts2_native_sim.scenarios import (
    CORPUS_SCHEMA,
    ERROR_RUN,
    FAILURE_RECORD,
    ROW_SCHEMA,
    SCENARIO_RECORD,
    SUMMARY_FILE,
    RunWorker,
    ScenarioMaterializationError,
    ScenarioRequest,
    ScenarioRequestError,
    encode_row,
    generate_corpus,
    generate_rows,
    materialize_scenario,
    read_corpus,
    read_scenario_corpus,
    summarize_rows,
)
from sts2_native_sim.schema import ObservationSchemaViolation, validate_observation

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
#: A worker failure, as the real worker reports one: a stable code, a message, and details that
#: must not reach a row.
WORKER_CRASH = NativeSimError("worker_crashed", "worker exited 1", {"logs": ["boom"]})


def _choice_action(index: int, relic: str) -> str:
    """The action id that takes an offered Ancient choice, as the environment names it."""
    return f"choose_event:{index}:NEOW.pages.INITIAL.options.{relic}"


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
        crash_on: dict[str, BaseException] | None = None,
        crash_on_resets: dict[int, BaseException] | None = None,
        crash_on_restores: dict[int, BaseException] | None = None,
        die_on: dict[str, BaseException] | None = None,
        delay_seconds: float = 0.0,
        float_quantity: bool = False,
        relics_after_choice: dict[int, tuple[str, ...]] | None = None,
        proceed: bool = False,
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
        #: The action ids this worker fails on, and — by 1-based ordinal — the runs it fails
        #: starting, so a failure can be forced at one step, or on one drive, of a batch. A
        #: failure is recorded as a row and this worker stays usable.
        self.crash_on = dict(crash_on or {})
        self.crash_on_resets = dict(crash_on_resets or {})
        self.crash_on_restores = dict(crash_on_restores or {})
        #: The action ids this worker *dies* on: it fails the same way, and then reports itself
        #: dead, which is what a batch replaces a worker for. And the seconds it takes before
        #: every run it starts, which is how a deliberately late worker is built.
        self.die_on = dict(die_on or {})
        self.delay_seconds = delay_seconds
        #: Whether the fight this worker serves has a floating-point quantity in it. A record's
        #: quantities are integers and strings, so this is how an element the generator cannot
        #: record is forced rather than assumed impossible — and it is a state a schema check
        #: accepts, because `1.0` is an integer to JSON Schema.
        self.float_quantity = float_quantity
        self.relics_after_choice = relics_after_choice or {}
        #: Whether the event also reports its own way out — an option that takes no blessing. The
        #: shipped act-1 Ancient builds no such option, but the environment reports the flag, and a
        #: caller that took one would record a choice granting nothing.
        self.proceed = proceed
        self.selected_choice: int | None = None
        self.dead = False
        self.closed = False
        self.resets = 0
        self.restores = 0
        #: The build every run this worker plays is on, as `NativeWorker.hello` reports it.
        self.build: dict[str, Any] = copy.deepcopy(CAPTURES["run_combat_action"]["game_build"])
        self.reset_request: dict[str, Any] | None = None
        self.steps: list[str] = []
        self.last_hash: str | None = None
        self._routes: dict[str, dict[str, Any]] = {}
        self._checkpoints: dict[str, dict[str, Any]] = {}

    # -- the seam the generator uses -----------------------------------------------------

    def run_reset(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        self.resets += 1
        if self.resets in self.crash_on_resets:
            raise self.crash_on_resets[self.resets]
        self.reset_request = copy.deepcopy(state)
        self._checkpoints.clear()
        observation = copy.deepcopy(CAPTURES["run_map_choice"])
        observation["run"]["seed"] = state["seed"]
        observation["run"]["ascension"] = state["ascension"]
        # The chosen choice opens the nested prompts in order; the last of them hands the
        # event back completed. A choice that opens none completes immediately.
        target = self._patched("run_event_complete")
        for nested in reversed(self.nested):
            for action in nested["decision"]["legal_actions"]:
                self._routes[action["action_id"]] = target
            target = nested
        # Every takeable choice is routeable: the generator takes each of them in turn.
        for index, relic in self._choice_indices().items():
            if relic in self.takeable:
                self._routes[self._choice_action(index, relic)] = (
                    target if index == self.nested_choice else self._patched("run_event_complete")
                )
        self._routes["leave_event"] = self._patched(self.leave)
        if self.row_one == "combat":
            for action_id in ROW_ONE_ACTIONS:
                self._routes[action_id] = self._patched("run_combat_action")
        else:
            self._routes[FIRST_ROW_ONE_ACTION] = self._patched("run_event_choice")
        self._routes[ANCIENT_ACTION] = self._event_choice()
        return self._next(observation)

    def run_step(self, action_id: str) -> dict[str, Any]:
        self.steps.append(action_id)
        if action_id in self.die_on:
            self.dead = True
            raise self.die_on[action_id]
        if action_id in self.crash_on:
            raise self.crash_on[action_id]
        if action_id.startswith("choose_event:"):
            self.selected_choice = int(action_id.split(":", 2)[1])
        if action_id == "leave_event":
            result = self._next(self._routes[action_id])
            relics = self.relics_after_choice.get(
                self.selected_choice,
                (self.offer[self.selected_choice],) if self.selected_choice is not None else (),
            )
            result["scoring_features"] = {"relics": list(relics)}
            return result
        return self._next(self._routes[action_id])

    def restore(self, state_handle: str) -> dict[str, Any]:
        assert state_handle in self._checkpoints
        self.restores += 1
        if self.restores in self.crash_on_restores:
            raise self.crash_on_restores[self.restores]
        return self._next(copy.deepcopy(self._checkpoints[state_handle]))

    def alive(self) -> bool:
        """Whether this worker is still usable, as a batch asks before replacing one."""
        return not self.dead

    def close(self) -> None:
        """Shut the worker down, which a batch does once per shard it wrote."""
        self.closed = True

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
        result = _result(observation, self.last_hash)
        self._checkpoints[result["state_handle"]] = copy.deepcopy(observation)
        return result

    def _patched(self, name: str) -> dict[str, Any]:
        observation = copy.deepcopy(CAPTURES[name])
        if self.reset_request is not None:
            observation["run"]["seed"] = self.reset_request["seed"]
            observation["run"]["ascension"] = self.reset_request["ascension"]
        if self.float_quantity and name == "run_combat_action":
            observation["combat"]["energy"] = 3.0
        return observation

    def _choice_indices(self) -> dict[int, str]:
        """Every choice this double can mention, by the option index each reports."""
        return dict(enumerate(list(self.offer) + [relic for relic in self.takeable if relic not in self.offer]))

    def _choice_action(self, index: int, relic: str) -> str:
        return _choice_action(index, relic)

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
        if self.proceed:
            # The event's own way out, as the environment reports one: an option and an action that
            # take no blessing, which is what a run takes when it has nothing left to choose.
            index = max(self._choice_indices(), default=-1) + 1
            action_id = f"choose_event:{index}:PROCEED"
            options.append({
                "option_index": index, "text_key": "PROCEED", "locked": False,
                "chosen": False, "is_proceed": True, "relic_model_id": None,
            })
            actions.append({
                "action_id": action_id, "kind": "choose_event",
                "parameters": {"option_index": index, "text_key": "PROCEED", "is_proceed": True, "relic_model_id": None},
            })
            self._routes[action_id] = self._patched("run_event_complete")
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


def _bundle_choice(*option_ids: str, skippable: bool = False) -> dict[str, Any]:
    """A nested bundle pick: `choose_option` actions, each naming the option it selects.

    A pick the run also allows to be declined carries the empty selection the environment emits for
    a prompt whose minimum selection is zero — first, as `EnumerateSelections` emits it — which is
    how a relic pick's offered relics sit behind a skip.
    """
    actions = [
        {
            "action_id": f"choose_option:card-choice-0:{option_id}", "kind": "choose_option",
            "parameters": {"choice_id": "card-choice-0", "option_ids": [option_id]},
        }
        for option_id in option_ids
    ]
    if skippable:
        actions.insert(0, {
            "action_id": "choose_option:card-choice-0:skip", "kind": "choose_option",
            "parameters": {"choice_id": "card-choice-0", "option_ids": []},
        })
    return {
        "schema_version": 3, "game_build": {}, "run": {"seed": SEED, "ascension": 0, "act_variant": "OVERGROWTH", "rng_counters": {}},
        "outstanding_choice": {
            "choice_id": "card-choice-0", "kind": "choose_option", "min_select": 0 if skippable else 1, "max_select": 1,
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


def _reward_action(index: int) -> str:
    """The action `_reward_choice` names for one of the rewards it offers, by reward index."""
    return f"choose_custom_reward:{index}:-1:0:gold:none"


def _reward_choice(rewards: int = 2) -> dict[str, Any]:
    """A nested reward set: `rewards` rewards to take, and a skip the run also allows."""
    actions = [
        {
            "action_id": _reward_action(index), "kind": "choose_custom_reward",
            "parameters": {"reward_index": index, "child_index": -1, "option_index": 0, "reward_kind": "gold", "model_id": None},
        }
        for index in range(rewards)
    ]
    actions.append({"action_id": "skip_custom_rewards", "kind": "skip_custom_rewards", "parameters": {}})
    return {
        "schema_version": 3, "game_build": {}, "run": {"seed": SEED, "ascension": 0, "act_variant": "OVERGROWTH", "rng_counters": {}},
        "custom_rewards": {
            "rewards": [
                {"reward_index": index, "reward": {"kind": "gold", "implementation": "GoldReward", "selected": False}, "children": []}
                for index in range(rewards)
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


# -- materializing a recorded scenario -------------------------------------------------


def test_materialization_replays_the_recorded_ancient_nested_choice_and_map_coordinate() -> None:
    nested = (_card_choice("choose_cards:first", "choose_cards:second"),)
    row = _rows(FakeRunWorker(nested=nested, nested_choice=1))[1]
    row["recipe"]["nested_choices"][0].update({
        "selected_index": 1,
        "selected_option_ids": ["choose_cards:second"],
    })
    row["recipe"]["node"].update({"col": 3, "row": 1})
    worker = FakeRunWorker(nested=nested, nested_choice=1)

    episode = materialize_scenario(row, worker)

    assert worker.steps == [
        ANCIENT_ACTION,
        _choice_action(1, RECORDED_OFFER[1]),
        "choose_cards:second",
        "leave_event",
        "choose_map:3:1",
    ]
    assert episode.observation == row["combat_initial_state"]


def test_materialization_names_the_first_observation_mismatch_before_the_changed_hash() -> None:
    row = _row()

    class ChangedCombatWorker(FakeRunWorker):
        def _next(self, observation: dict[str, Any]) -> dict[str, Any]:
            observation = copy.deepcopy(observation)
            if observation["decision"]["kind"] == "combat_action":
                observation["combat"]["energy"] += 1
            return super()._next(observation)

    with pytest.raises(
        ScenarioMaterializationError,
        match=r"combat_initial_state mismatch at \$\.combat\.energy",
    ):
        materialize_scenario(row, ChangedCombatWorker())


def test_a_combat_episode_steps_forward_to_victory_and_reports_hp_loss() -> None:
    row = _row()
    first_action = row["combat_initial_state"]["decision"]["legal_actions"][0]["action_id"]
    final_action = row["combat_initial_state"]["decision"]["legal_actions"][1]["action_id"]

    class FinishingCombatWorker(FakeRunWorker):
        def run_reset(self, state: dict[str, Any]) -> dict[str, Any]:
            result = super().run_reset(state)
            damaged = self._patched("run_combat_action")
            damaged["combat"]["creatures"][0]["hp"] -= 7
            self._routes[first_action] = damaged
            self._routes[final_action] = self._patched("run_room_reward_choice")
            return result

        def run_step(self, action_id: str) -> dict[str, Any]:
            result = super().run_step(action_id)
            if action_id == final_action:
                result["scoring_features"] = {"current_hp": 9990}
            return result

    episode = materialize_scenario(row, FinishingCombatWorker())

    assert episode.legal_actions == row["combat_initial_state"]["decision"]["legal_actions"]
    assert episode.complete is False
    assert episode.outcome is None
    assert episode.hp_loss == 0

    damaged = episode.step(first_action)
    assert damaged["combat"]["creatures"][0]["hp"] == 9992
    assert episode.complete is False
    assert episode.hp_loss == 7

    episode.step(final_action)
    assert episode.complete is True
    assert episode.outcome == "victory"
    assert episode.hp_loss == 9


def test_a_combat_episode_rejects_a_step_outside_the_canonical_contract() -> None:
    row = _row()
    action_id = row["combat_initial_state"]["decision"]["legal_actions"][0]["action_id"]

    class InvalidObservationWorker(FakeRunWorker):
        def run_reset(self, state: dict[str, Any]) -> dict[str, Any]:
            result = super().run_reset(state)
            broken = self._patched("run_combat_action")
            broken["runtime_only"] = {}
            self._routes[action_id] = broken
            return result

    episode = materialize_scenario(row, InvalidObservationWorker())

    with pytest.raises(ObservationSchemaViolation, match=r"runtime_only"):
        episode.step(action_id)


def test_materialization_reports_encounter_identity_before_other_combat_drift() -> None:
    row = _row()

    class ChangedEncounterWorker(FakeRunWorker):
        def _next(self, observation: dict[str, Any]) -> dict[str, Any]:
            observation = copy.deepcopy(observation)
            if observation["decision"]["kind"] == "combat_action":
                observation["combat"]["encounter"] = "WRONG_ENCOUNTER"
            return super()._next(observation)

    with pytest.raises(ScenarioMaterializationError, match="encounter mismatch"):
        materialize_scenario(row, ChangedEncounterWorker())


def test_materialization_reports_a_state_hash_mismatch_after_the_observation_matches() -> None:
    row = _row()

    class ChangedHashWorker(FakeRunWorker):
        def _next(self, observation: dict[str, Any]) -> dict[str, Any]:
            result = super()._next(observation)
            if observation["decision"]["kind"] == "combat_action":
                result["state_hash"] = "changed-state-hash"
            return result

    with pytest.raises(ScenarioMaterializationError, match="state_hash mismatch"):
        materialize_scenario(row, ChangedHashWorker())


def test_materialization_replays_the_reward_branch_a_row_recorded() -> None:
    """An enumerated branch is a recipe like any other: it replays to the fight it recorded.

    The branch is the reward the discovery drive did not take, so a replay that took the prompt's
    first option instead would be a different branch and this is where that would show.
    """
    branch = _rows(worker=_branched_worker())[1]
    worker = _branched_worker()

    episode = materialize_scenario(branch, worker)

    assert _reward_action(1) in worker.steps
    assert episode.observation == branch["combat_initial_state"]


def test_materialization_refuses_a_recorded_reward_the_prompt_no_longer_offers_at_that_index() -> None:
    """The recorded identity is what makes the index a reward rather than a position.

    A build that offers another reward at the recorded index would otherwise replay a branch the
    row does not describe, so the identity the row carries is checked against the action taken.
    """
    branch = _rows(worker=_branched_worker())[1]
    branch["recipe"]["nested_choices"][0]["selected_reward"]["reward_kind"] = "relic"

    with pytest.raises(ScenarioMaterializationError, match="not the recorded"):
        materialize_scenario(branch, _branched_worker())


def test_materialization_refuses_a_reward_identity_that_is_not_the_shape_the_prompt_reports() -> None:
    """A recorded identity that is not a reward's identity is refused before a run is started."""
    branch = _rows(worker=_branched_worker())[1]
    del branch["recipe"]["nested_choices"][0]["selected_reward"]["reward_index"]
    worker = _branched_worker()

    with pytest.raises(
        ScenarioMaterializationError,
        match=r"invalid scenario row: \$\.recipe\.nested_choices\[0\]\.selected_reward\.reward_index is required",
    ):
        materialize_scenario(branch, worker)

    assert worker.resets == 0


def test_materialization_refuses_a_failure_row_before_starting_a_run() -> None:
    failure = _row(row_one="event")
    worker = FakeRunWorker()

    with pytest.raises(ScenarioMaterializationError, match="requires a scenario row"):
        materialize_scenario(failure, worker)

    assert worker.resets == 0


def test_materialization_validates_the_whole_recipe_before_starting_a_run() -> None:
    row = _row()
    del row["recipe"]["node"]
    worker = FakeRunWorker()

    with pytest.raises(ScenarioMaterializationError, match=r"invalid scenario row: \$\.recipe\.node is required"):
        materialize_scenario(row, worker)

    assert worker.resets == 0


def test_a_combat_episode_reports_defeat_and_the_last_observed_hp_loss() -> None:
    row = _row()
    action_id = row["combat_initial_state"]["decision"]["legal_actions"][0]["action_id"]

    class LosingCombatWorker(FakeRunWorker):
        def run_reset(self, state: dict[str, Any]) -> dict[str, Any]:
            result = super().run_reset(state)
            defeated = self._patched("run_combat_terminal")
            defeated["combat"]["creatures"][0]["hp"] = 9987
            self._routes[action_id] = defeated
            return result

    episode = materialize_scenario(row, LosingCombatWorker())
    episode.step(action_id)

    assert episode.complete is True
    assert episode.outcome == "defeat"
    assert episode.hp_loss == 12
    assert episode.legal_actions == []
    with pytest.raises(RuntimeError, match="episode is complete"):
        episode.step(action_id)


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


def test_a_run_start_request_declares_the_run_reset_it_is() -> None:
    """The generator asks for a run reset on the request, not by which members it happens to set.

    A run reset builds no combat — the run stands on its map and the fight it will really play is
    built when it enters a monster room — and the environment reads that off the request, because a
    stored branch replays from the same request, where no method name is left to say which reset it
    was. The generator states which of the two resets it is asking for rather than leaving it to be
    inferred from the members it fills in. The value is written out rather than taken from the
    client's constant because it is the wire word the environment's own `ResetModes.Run` reads, so a
    rename on either side is a change to both.
    """
    worker = FakeRunWorker()
    generate_rows(_request(), worker)

    assert worker.reset_request is not None and worker.reset_request["reset_mode"] == "run"


def test_each_scenario_generation_element_resets_once_for_all_ancient_choices() -> None:
    worker = FakeRunWorker()

    rows = generate_rows(ScenarioRequest(("IRONCLAD",), (0,), ("1", "2")), worker)

    assert len(rows) == 6
    assert worker.resets == 2


def test_ancient_choices_reuse_the_offered_state_handle() -> None:
    worker = FakeRunWorker()

    rows = _rows(worker=worker)

    assert [row["record_type"] for row in rows] == [SCENARIO_RECORD] * 3
    assert worker.restores == 2


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


def test_a_reported_choice_no_action_can_take_is_recorded_as_a_failure_row() -> None:
    row = _row(takeable=("LAVA_ROCK", "PHIAL_HOLSTER"))

    assert row["record_type"] == FAILURE_RECORD
    assert row["stage"] == "ancient_choice"
    assert "option 2" in row["error"]["message"] and "no legal action" in row["error"]["message"]
    # A choice no action can take was never taken, so the recipe does not name one.
    assert "ancient_choice" not in row["recipe"]
    assert row["recipe"]["act_variant"] == CAPTURES["run_combat_action"]["run"]["act_variant"]


def test_a_choice_the_event_does_not_report_is_recorded_as_a_failure_row() -> None:
    row = _row(offer=("LAVA_ROCK", "PHIAL_HOLSTER"), takeable=("LAVA_ROCK", "PHIAL_HOLSTER", "SILKEN_TRESS"))

    assert row["record_type"] == FAILURE_RECORD
    assert row["stage"] == "ancient_choice"
    assert "does not report" in row["error"]["message"]
    assert "ancient_choice" not in row["recipe"]


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


def test_a_nested_reward_pick_names_a_reward_instead_of_option_ids() -> None:
    """A reward pick is not an action that failed to name what it selected.

    A reward set offers rewards rather than option ids, so the pick's selection is the reward's own
    identity, recorded beside an empty `selected_option_ids`: the branch reaches a scenario row
    rather than the failure row a selection that names nothing gets.
    """
    worker = FakeRunWorker(offer=("NEW_LEAF", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_reward_choice(),))
    row = _row(worker=worker)

    picked = row["recipe"]["nested_choices"][0]
    assert row["record_type"] == SCENARIO_RECORD
    assert picked["selected_index"] == 0 and picked["selected_option_ids"] == []
    assert picked["selected_reward"]["reward_index"] == 0


def test_a_nested_bundle_pick_records_the_options_it_selected() -> None:
    worker = FakeRunWorker(offer=("SCROLL_BOXES", "FISHING_ROD", "SILKEN_TRESS"),
                           nested=(_bundle_choice("bundle-0", "bundle-1"),))
    row = _row(worker=worker)

    assert row["recipe"]["nested_choices"] == [{
        "kind": "option_choice",
        "selected_index": 0,
        "selected_option_ids": ["bundle-0"],
    }]


def test_a_nested_selection_that_names_no_option_ids_is_recorded_as_a_failure_row() -> None:
    rows = _rows(offer=("HEFTY_TABLET", "FISHING_ROD", "SILKEN_TRESS"), nested=(_silent_card_choice(),))
    row = rows[0]

    assert row["record_type"] == FAILURE_RECORD
    # The run reached the fight, but the choice that opened this prompt is what could not be
    # recorded, so the stage is the choice's own rather than the phase the drive finished in.
    assert row["stage"] == "ancient_choice"
    assert "option ids" in row["error"]["message"]
    assert row["recipe"]["ancient_choice"] == {"option_index": 0, "relic_model_id": "HEFTY_TABLET"}
    # The offer was already known, so the choices that could be recorded still were.
    assert [other["record_type"] for other in rows] == [FAILURE_RECORD, SCENARIO_RECORD, SCENARIO_RECORD]


def test_a_proceed_option_the_ancient_reports_is_not_a_choice_and_records_no_row() -> None:
    """The Ancient's own way out ends the room instead of taking a blessing, so it is no branch.

    The environment reports such an option with ``is_proceed``. A run that takes it holds no new
    relic and reaches no new situation, and a row for it would claim a choice the offer does not
    make: the batch records the choices that take something, the offer it records is those choices,
    and the proceed option is not driven at all.
    """
    worker = FakeRunWorker(proceed=True)

    rows = _rows(worker=worker)

    assert [row["recipe"]["ancient_choice"]["relic_model_id"] for row in rows] == list(RECORDED_OFFER)
    assert [row["recipe"]["ancient_options"] for row in rows] == [
        [{"option_index": index, "relic_model_id": relic} for index, relic in enumerate(RECORDED_OFFER)],
    ] * len(RECORDED_OFFER)
    assert "choose_event:3:PROCEED" not in worker.steps


def test_a_choice_that_opens_no_prompt_records_no_nested_choice() -> None:
    row = _row(worker=FakeRunWorker(offer=("SILKEN_TRESS", "FISHING_ROD", "LAVA_ROCK")))

    assert row["recipe"]["nested_choices"] == []


# -- the enumerated opening branches -----------------------------------------------------


#: The offer whose first choice opens one reward prompt — a reward set of two rewards and a skip —
#: and the double that serves it. The offer's other two choices open no prompt, so a test's row set
#: is that choice's branches followed by one row per remaining choice.
_BRANCHED_OFFER = ("SMALL_CAPSULE", "FISHING_ROD", "SILKEN_TRESS")


def _branched_worker(**options: Any) -> FakeRunWorker:
    """A double whose first offered choice opens one reward prompt."""
    return FakeRunWorker(offer=_BRANCHED_OFFER, nested=(_reward_choice(),), **options)


def test_a_choice_that_opens_one_option_pick_records_a_row_per_option_and_none_for_the_skip() -> None:
    """An option pick offers whole bundles, and declining it is not a branch of its own.

    The empty selection is the environment's own spelling of "skip this prompt": it is emitted first
    for a prompt whose minimum selection is zero, which is what a relic pick's offered relics sit
    behind. Every bundle the prompt offers is a branch of its own — the drive that found the prompt
    took the skip, so each bundle is driven from the state the offered state was left in — and the
    skip records nothing.
    """
    worker = FakeRunWorker(
        offer=("SCROLL_BOXES", "FISHING_ROD", "SILKEN_TRESS"),
        nested=(_bundle_choice("bundle-0", "bundle-1", skippable=True),),
    )

    rows = _rows(worker=worker)

    assert [
        (
            row["recipe"]["ancient_choice"]["option_index"],
            [nested["selected_option_ids"] for nested in row["recipe"]["nested_choices"]],
        )
        for row in rows
    ] == [(0, [["bundle-0"]]), (0, [["bundle-1"]]), (1, []), (2, [])]
    assert all("selected_reward" not in nested for row in rows for nested in row["recipe"]["nested_choices"])
    # Each bundle is driven once: the skip the finding drive took is not a row, so neither bundle
    # is the drive that found the prompt.
    assert worker.steps.count("choose_option:card-choice-0:bundle-0") == 1
    assert worker.steps.count("choose_option:card-choice-0:bundle-1") == 1


def test_a_failed_option_is_its_own_failure_row_and_leaves_its_sibling_recorded() -> None:
    """One option failing is that option's failure, not the choice's.

    The failure row carries the recipe resolved so far — the Ancient choice and the reward the
    branch took — which is what tells it from its sibling's failure, and the sibling is still driven
    from the offered state the run was left in.
    """
    worker = _branched_worker(crash_on={_reward_action(1): WORKER_CRASH})

    rows = _rows(worker=worker)

    assert [row["record_type"] for row in rows] == [
        SCENARIO_RECORD, FAILURE_RECORD, SCENARIO_RECORD, SCENARIO_RECORD,
    ]
    failed = rows[1]
    assert failed["stage"] == "ancient_choice"
    assert failed["error"] == {"kind": "worker_crashed", "message": "worker exited 1"}
    assert failed["recipe"]["ancient_choice"] == {"option_index": 0, "relic_model_id": "SMALL_CAPSULE"}
    assert failed["recipe"]["nested_choices"] == [{
        "kind": "custom_reward_choice",
        "selected_index": 1,
        "selected_option_ids": [],
        "selected_reward": {
            "reward_index": 1, "child_index": -1, "option_index": 0, "reward_kind": "gold", "model_id": None,
        },
    }]
    assert "combat_initial_state" not in failed and "state_hash" not in failed


def test_an_option_that_fails_before_it_is_taken_still_leaves_its_siblings_recorded() -> None:
    """The drive that finds the prompt is the drive of the option it took, failure included.

    When that option is the one that fails, the failure is its row rather than the choice's, and
    every other reward the prompt offers is still driven — which is what "a failed option does not
    suppress its siblings" means for the option that happened to be found first.
    """
    worker = _branched_worker(crash_on={_reward_action(0): WORKER_CRASH})

    rows = _rows(worker=worker)

    assert [row["record_type"] for row in rows] == [
        FAILURE_RECORD, SCENARIO_RECORD, SCENARIO_RECORD, SCENARIO_RECORD,
    ]
    assert rows[0]["recipe"]["nested_choices"][0]["selected_reward"]["reward_index"] == 0
    assert rows[1]["recipe"]["nested_choices"][0]["selected_reward"]["reward_index"] == 1
    assert worker.steps.count(_reward_action(0)) == 1 and worker.steps.count(_reward_action(1)) == 1


def test_a_prompt_with_no_option_to_take_leaves_the_choice_the_row_it_drove() -> None:
    """An offered Ancient choice still contributes a row when its prompt offers nothing to take.

    A prompt whose only legal action is a skip has no non-skip option to branch on, so branching on
    it would leave the offered choice contributing no row at all. The choice keeps the row its own
    drive produced instead; the skip it took is that row's own record, not a branch of its own.
    """
    worker = FakeRunWorker(
        offer=("SMALL_CAPSULE", "FISHING_ROD", "SILKEN_TRESS"),
        nested=(_reward_choice(0),),
    )

    rows = _rows(worker=worker)

    assert [
        (
            row["recipe"]["ancient_choice"]["option_index"],
            [nested["kind"] for nested in row["recipe"]["nested_choices"]],
        )
        for row in rows
    ] == [(0, ["custom_reward_choice"]), (1, []), (2, [])]
    assert rows[0]["recipe"]["nested_choices"] == [{
        "kind": "custom_reward_choice",
        "selected_index": 0,
        "selected_option_ids": [],
    }]


def test_a_choice_that_opens_a_card_select_is_not_branched_on() -> None:
    """A card select is the next cardinality, not this one: which copy is taken is pruned there.

    The prompt offers two cards and the choice records the one the fixed rule takes, so a card
    select contributes one row rather than one row per card.
    """
    worker = FakeRunWorker(
        offer=("HEFTY_TABLET", "FISHING_ROD", "SILKEN_TRESS"),
        nested=(_card_choice("card-choice-0", "card-choice-1"),),
    )

    rows = _rows(worker=worker)

    assert [row["recipe"]["ancient_choice"]["option_index"] for row in rows] == [0, 1, 2]
    assert rows[0]["recipe"]["nested_choices"] == [{
        "kind": "card_choice",
        "selected_index": 0,
        "selected_option_ids": ["card-choice-0"],
    }]


def test_a_choice_that_opens_a_prompt_and_then_another_keeps_the_single_row_it_drove() -> None:
    """One prompt is this ticket's cardinality; a chain of prompts is the chained-choice ticket's.

    The choice's own drive resolves each prompt it meets by the fixed rule, so its row records the
    chain it walked — the reward it took and the card select that followed — and the rewards it did
    not take stay unrecorded until the recursive policy owns them.
    """
    worker = FakeRunWorker(
        offer=("NEOWS_BONES", "FISHING_ROD", "SILKEN_TRESS"),
        nested=(_reward_choice(), _card_choice("card-choice-0", "card-choice-1")),
    )

    rows = _rows(worker=worker)

    assert [
        (
            row["recipe"]["ancient_choice"]["option_index"],
            [nested["kind"] for nested in row["recipe"]["nested_choices"]],
        )
        for row in rows
    ] == [(0, ["custom_reward_choice", "card_choice"]), (1, []), (2, [])]
    assert worker.steps.count(_reward_action(1)) == 0


def test_a_choice_that_opens_one_reward_prompt_records_a_row_per_reward_and_none_for_the_skip() -> None:
    """A reward set offers whole rewards, so each reward it offers is a branch of its own.

    The drive that finds the prompt takes the first legal action, and the branch it took is the row
    it produced rather than a second run of the same branch; each reward it did not take is driven
    from the state the Ancient offer was left in. The skip the set also allows is no branch at all:
    it declines the prompt rather than taking a reward from it, so it records nothing.
    """
    worker = _branched_worker()

    rows = _rows(worker=worker)

    assert [
        (
            row["recipe"]["ancient_choice"]["option_index"],
            [nested["selected_index"] for nested in row["recipe"]["nested_choices"]],
        )
        for row in rows
    ] == [(0, [0]), (0, [1]), (1, []), (2, [])]
    assert all(row["record_type"] == SCENARIO_RECORD for row in rows)
    validate_observation(rows[1]["combat_initial_state"])
    # Each reward is driven once: the row for the branch the discovery drive took is that drive's,
    # and the sibling's is its own drive of the same offered state.
    assert worker.steps.count(_reward_action(0)) == 1
    assert worker.steps.count(_reward_action(1)) == 1


def test_a_branch_records_the_reward_it_took_by_the_identity_the_pick_names() -> None:
    """A reward pick names no option ids, so what it took is recorded as the reward it is.

    The row's index is the pick's position among the prompt's legal actions, which is what a replay
    takes from it; the identity beside it — the reward's indices, its kind and its model — is what
    says the replay took the same reward rather than whatever holds that position on another build.
    A reward model is the reward's subject, so `model_id` is null for a reward that has none.
    """
    worker = FakeRunWorker(offer=("SMALL_CAPSULE", "FISHING_ROD", "SILKEN_TRESS"), nested=(_reward_choice(),))

    rows = _rows(worker=worker)

    assert [row["recipe"]["nested_choices"] for row in rows[:2]] == [
        [{
            "kind": "custom_reward_choice",
            "selected_index": 0,
            "selected_option_ids": [],
            "selected_reward": {
                "reward_index": 0, "child_index": -1, "option_index": 0,
                "reward_kind": "gold", "model_id": None,
            },
        }],
        [{
            "kind": "custom_reward_choice",
            "selected_index": 1,
            "selected_option_ids": [],
            "selected_reward": {
                "reward_index": 1, "child_index": -1, "option_index": 0,
                "reward_kind": "gold", "model_id": None,
            },
        }],
    ]


def test_a_nested_choice_is_serialised_in_the_declared_key_order_and_the_identity_beside_it() -> None:
    """A nested choice's identity is a record of its own, so its bytes are declared too.

    The corpus is diffed line by line, so the order the identity's fields were filled in must not
    be able to reach the bytes: the same record assembled in another order is the same line.
    """
    row = _rows(
        offer=("SMALL_CAPSULE", "FISHING_ROD", "SILKEN_TRESS"), nested=(_reward_choice(),)
    )[1]

    recorded = json.loads(encode_row(row))["recipe"]["nested_choices"][0]
    assert list(recorded) == ["kind", "selected_index", "selected_option_ids", "selected_reward"]
    assert list(recorded["selected_reward"]) == [
        "reward_index", "child_index", "option_index", "reward_kind", "model_id",
    ]

    scrambled = copy.deepcopy(row)
    nested = scrambled["recipe"]["nested_choices"][0]
    nested["selected_reward"] = _reversed_keys(nested["selected_reward"])
    scrambled["recipe"]["nested_choices"] = [_reversed_keys(nested)]
    assert encode_row(scrambled) == encode_row(row)


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


# -- failure rows ------------------------------------------------------------------------


def test_an_indirect_first_combat_relic_is_excluded_before_entering_the_fight() -> None:
    worker = FakeRunWorker(
        offer=("GOLDEN_PEARL", "NEOWS_TORMENT", "LARGE_CAPSULE"),
        relics_after_choice={2: ("BURNING_BLOOD", "LARGE_CAPSULE", "GAMBLING_CHIP", "MERCURY_HOURGLASS")},
    )

    rows = _rows(worker)

    assert [row["record_type"] for row in rows] == [SCENARIO_RECORD, SCENARIO_RECORD, FAILURE_RECORD]
    excluded = rows[2]
    assert excluded["recipe"]["ancient_choice"] == {"option_index": 2, "relic_model_id": "LARGE_CAPSULE"}
    assert excluded["stage"] == "first_combat"
    assert excluded["error"]["kind"] == "unsupported_interactive_first_combat_relic"
    assert "GAMBLING_CHIP" in excluded["error"]["message"]
    assert "combat_initial_state" not in excluded and "state_hash" not in excluded
    assert worker.steps.count(FIRST_ROW_ONE_ACTION) == 2


def test_excluding_a_relic_after_an_ancient_nested_choice_preserves_later_choices() -> None:
    worker = FakeRunWorker(
        offer=("GAMBLING_CHIP", "GOLDEN_PEARL", "LARGE_CAPSULE"),
        nested=(_card_choice("choose_cards:first", "choose_cards:second"),),
        relics_after_choice={0: ("BURNING_BLOOD", "GAMBLING_CHIP")},
    )

    rows = _rows(worker)

    assert [row["record_type"] for row in rows] == [FAILURE_RECORD, SCENARIO_RECORD, SCENARIO_RECORD]
    assert rows[0]["stage"] == "first_combat"
    assert rows[0]["error"]["kind"] == "unsupported_interactive_first_combat_relic"
    assert rows[0]["recipe"]["ancient_choice"] == {"option_index": 0, "relic_model_id": "GAMBLING_CHIP"}
    assert worker.steps.count(FIRST_ROW_ONE_ACTION) == 2


def _choice_crash(offer: tuple[str, ...], index: int) -> dict[str, BaseException]:
    """A crash on one offered choice's own action, and on nothing else."""
    return {_choice_action(index, offer[index]): WORKER_CRASH}


def test_a_run_that_does_not_reach_a_fight_is_recorded_as_a_failure_row() -> None:
    row = _row(row_one="event")

    assert row["schema"] == ROW_SCHEMA
    assert row["record_type"] == FAILURE_RECORD
    assert set(row["game_build"]) == {"version", "assembly_sha256", "pck_sha256"}
    assert row["stage"] == "first_combat"
    # The tag a reader counts on, spelled out: a failure row's kind is part of the corpus format.
    assert row["error"]["kind"] == "run" == ERROR_RUN
    assert "event_choice" in row["error"]["message"]


def test_a_room_that_does_not_hand_back_the_map_is_recorded_as_a_failure_row() -> None:
    row = _row(leave="run_event_choice")

    assert row["record_type"] == FAILURE_RECORD
    assert row["stage"] == "leave_ancient"
    assert "event_choice" in row["error"]["message"]


def test_a_failure_row_carries_the_recipe_resolved_so_far_and_no_combat_state() -> None:
    row = _row(row_one="event")

    # The same envelope a scenario row carries, minus the fight and with the failure in its place.
    assert set(row) == {"schema", "record_type", "game_build", "recipe", "stage", "error"}
    assert set(row["recipe"]) == {"character", "ascension", "seed", "act_variant", "ancient_choice"}
    assert row["recipe"]["character"] == "IRONCLAD"
    assert row["recipe"]["ascension"] == 0
    assert row["recipe"]["seed"] == SEED
    assert row["recipe"]["act_variant"] == CAPTURES["run_combat_action"]["run"]["act_variant"]
    assert row["recipe"]["ancient_choice"] == {"option_index": 0, "relic_model_id": RECORDED_OFFER[0]}
    # No combat state, partial or otherwise: there is no state to carry and no hash of one, and
    # the recipe stops where the run stopped rather than where the generation meant to go.
    assert "combat_initial_state" not in row and "state_hash" not in row
    assert "node" not in row["recipe"] and "encounter" not in row["recipe"]


def test_a_failure_row_keeps_the_raw_seed_diagnostic_when_the_caller_supplied_one() -> None:
    row = generate_rows(_request("ANCIENT01"), FakeRunWorker(row_one="event"))[0]

    assert set(row["recipe"]) == {"character", "ascension", "seed", "raw_seed", "act_variant", "ancient_choice"}
    assert row["recipe"]["seed"] == SEED and row["recipe"]["raw_seed"] == "ANCIENT01"


def test_a_failure_before_the_choice_is_known_carries_only_what_the_run_reached() -> None:
    rows = _rows(crash_on={ANCIENT_ACTION: WORKER_CRASH})

    # The offer is exactly what this failure prevented learning, so the element owes one row and
    # no more: there is nothing to say how many choices the run would have offered.
    assert len(rows) == 1
    row = rows[0]
    assert row["record_type"] == FAILURE_RECORD
    assert row["stage"] == "ancient_room"
    assert set(row["recipe"]) == {"character", "ascension", "seed", "act_variant"}


def test_a_first_drive_that_stops_after_the_offer_still_gives_every_choice_a_row() -> None:
    """The offer was read before the failure, so the elements after it are known and are recorded."""
    worker = FakeRunWorker(row_one="event")

    rows = _rows(worker=worker)

    assert [row["record_type"] for row in rows] == [FAILURE_RECORD] * len(RECORDED_OFFER)
    assert [row["recipe"]["ancient_choice"] for row in rows] == [
        {"option_index": index, "relic_model_id": relic} for index, relic in enumerate(RECORDED_OFFER)
    ]
    assert {row["stage"] for row in rows} == {"first_combat"}
    assert summarize_rows(rows)["failed"] == len(RECORDED_OFFER)
    assert worker.steps.count(FIRST_ROW_ONE_ACTION) == len(RECORDED_OFFER), "a failed element was retried"


def test_a_failed_restore_names_its_choice_and_leaves_later_choices_recorded() -> None:
    """An offered choice keeps its identity even when its branch cannot be restored."""
    worker = FakeRunWorker(crash_on_restores={1: WORKER_CRASH})
    rows = _rows(worker=worker)

    assert [row["record_type"] for row in rows] == [SCENARIO_RECORD, FAILURE_RECORD, SCENARIO_RECORD]
    stopped = rows[1]
    assert stopped["stage"] == "ancient_choice"
    assert stopped["recipe"]["ancient_choice"] == {"option_index": 1, "relic_model_id": RECORDED_OFFER[1]}
    assert "combat_initial_state" not in stopped
    assert worker.resets == 1


def test_a_run_that_never_starts_carries_the_declared_recipe_alone() -> None:
    row = _row(crash_on_resets={1: WORKER_CRASH})

    assert row["record_type"] == FAILURE_RECORD
    assert row["stage"] == "run_start"
    assert set(row["recipe"]) == {"character", "ascension", "seed"}


def test_a_worker_error_is_recorded_with_the_workers_own_code_as_its_kind() -> None:
    row = _row(crash_on={"leave_event": WORKER_CRASH})

    assert row["record_type"] == FAILURE_RECORD
    assert row["stage"] == "leave_ancient"
    # The worker's own code is the kind and its own text is the message, without the two repeated.
    assert row["error"] == {"kind": "worker_crashed", "message": "worker exited 1"}
    assert "logs" not in json.dumps(row), "the worker's details leaked into the row"
    # The recipe went as far as the worker did, so the choice the run had taken is on it.
    assert row["recipe"]["ancient_choice"] == {"option_index": 0, "relic_model_id": RECORDED_OFFER[0]}


def test_a_captured_state_with_a_floating_point_quantity_becomes_a_failure_row() -> None:
    """A quantity the record cannot hold is that element's failure, not a corpus that drifts.

    `3.0` and `3` are one number and two byte strings, and the schema check accepts both — `1.0` is
    an integer to JSON Schema — so the record refuses the float itself, and it is refused where the
    row is built, so the element is a failure row in a batch that still completes.
    """
    rows = _rows(float_quantity=True)

    assert [row["record_type"] for row in rows] == [FAILURE_RECORD] * len(RECORDED_OFFER)
    row = rows[0]
    assert row["stage"] == "record"
    assert row["error"]["kind"] == ERROR_RUN
    assert "combat.energy" in row["error"]["message"] and "3.0" in row["error"]["message"]
    # A state the record cannot carry is not carried at all, partially or otherwise.
    assert "combat_initial_state" not in row and "state_hash" not in row
    assert row["recipe"]["ancient_choice"] == {"option_index": 0, "relic_model_id": RECORDED_OFFER[0]}


def test_a_failing_element_is_recorded_once_and_the_rest_of_the_request_still_completes() -> None:
    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("SEED1", "SEED2"))
    worker = FakeRunWorker(crash_on={ANCIENT_ACTION: WORKER_CRASH})

    rows = generate_rows(request, worker)

    # One failure row per element that failed, in the request's order, and the run after it was
    # still driven: a failure is recorded rather than retried, and it does not end the batch.
    assert [row["record_type"] for row in rows] == [FAILURE_RECORD, FAILURE_RECORD]
    assert [row["recipe"]["seed"] for row in rows] == ["SEED1", "SEED2"]
    assert summarize_rows(rows) == {
        "rows": {SCENARIO_RECORD: 0, FAILURE_RECORD: 2},
        "succeeded": 0,
        "failed": 2,
        "total": 2,
    }
    assert worker.steps.count(ANCIENT_ACTION) == 2, "a failed element was attempted more than once"


def test_a_choice_that_fails_leaves_the_choices_after_it_recorded() -> None:
    offer = ("LAVA_ROCK", "PHIAL_HOLSTER", "SILKEN_TRESS")
    worker = FakeRunWorker(offer=offer, crash_on=_choice_crash(offer, 1))

    rows = _rows(worker=worker)

    assert [row["record_type"] for row in rows] == [SCENARIO_RECORD, FAILURE_RECORD, SCENARIO_RECORD]
    assert rows[1]["recipe"]["ancient_choice"] == {"option_index": 1, "relic_model_id": offer[1]}
    assert worker.steps.count(_choice_action(1, offer[1])) == 1, "a failed element was attempted more than once"


def test_the_summary_counts_the_rows_that_succeeded_and_the_rows_that_failed() -> None:
    offer = ("LAVA_ROCK", "PHIAL_HOLSTER", "SILKEN_TRESS")

    assert summarize_rows(_rows(offer=offer, crash_on=_choice_crash(offer, 1))) == {
        "rows": {SCENARIO_RECORD: 2, FAILURE_RECORD: 1},
        "succeeded": 2,
        "failed": 1,
        "total": 3,
    }
    # A batch that lost nothing says so, rather than leaving a reader to infer it from an absent
    # row type.
    assert summarize_rows(_rows()) == {
        "rows": {SCENARIO_RECORD: len(RECORDED_OFFER), FAILURE_RECORD: 0},
        "succeeded": len(RECORDED_OFFER),
        "failed": 0,
        "total": len(RECORDED_OFFER),
    }


def test_the_summary_refuses_a_row_type_it_does_not_know() -> None:
    """A corpus that gained a third row type must not be counted as if it had lost rows."""
    with pytest.raises(ValueError):
        summarize_rows([{"record_type": "episode_summary"}])


def test_the_same_element_fails_again_with_the_same_error_kind() -> None:
    offer = ("LAVA_ROCK", "PHIAL_HOLSTER", "SILKEN_TRESS")
    cases: tuple[tuple[dict[str, Any], str], ...] = (
        ({"row_one": "event"}, ERROR_RUN),
        ({"crash_on_resets": {1: WORKER_CRASH}}, "worker_crashed"),
        ({"offer": offer, "crash_on": _choice_crash(offer, 1)}, "worker_crashed"),
    )

    for options, kind in cases:
        first, second = _rows(**options), _rows(**options)

        assert first == second, f"a re-run of {options} is not the same rows"
        assert {row["error"]["kind"] for row in first if row["record_type"] == FAILURE_RECORD} == {kind}


# -- the sharded corpus ------------------------------------------------------------------


class _BatchStopped(BaseException):
    """A batch that stopped the way a killed process does: nothing catches it, nothing records it.

    It is a `BaseException` on purpose. Everything the generator records as a row is an
    `Exception`; only the death of the batch itself is outside that vocabulary.
    """


@pytest.fixture
def corpus_roots() -> Iterator[Callable[[], Path]]:
    """A factory for writable artifact roots a corpus can be written into, removed again afterwards.

    A test that compares two runs of one request needs two roots, and a test that compares one
    request at several worker counts needs several, so the fixture makes them on demand rather than
    deciding for the test how many corpora it is allowed to write.
    """
    created: list[Path] = []

    def make() -> Path:
        root = Path(tempfile.gettempdir()) / uuid.uuid4().hex
        root.mkdir(parents=True)
        created.append(root)
        return root

    try:
        yield make
    finally:
        for root in created:
            shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def corpus_root(corpus_roots: Callable[[], Path]) -> Path:
    """One writable artifact root a corpus can be written into, removed again afterwards."""
    return corpus_roots()


def _four_element_request() -> ScenarioRequest:
    """Two characters by two seeds, so a two-worker batch owns two elements per shard."""
    return ScenarioRequest(characters=("IRONCLAD", "DEFECT"), ascensions=(0,), seeds=("SEED1", "SEED2"))


def _offline_game_assembly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    game = tmp_path / "game"
    (game / "data").mkdir(parents=True)
    assembly = game / "data" / "sts2.dll"
    assembly.touch()
    (game / "SlayTheSpire2.pck").write_bytes(b"small offline pack")
    monkeypatch.setattr(_scenario_corpus, "find_game_assembly", lambda: assembly)


@pytest.mark.skipif(_scenario_corpus.os.name != "nt", reason="PCK hints are supported on Windows")
def test_a_multi_shard_batch_shares_one_parent_pck_fingerprint_through_its_worker_factory(
    corpus_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _offline_game_assembly(tmp_path, monkeypatch)
    measured: list[PckFingerprint] = []
    real_measure = PckFingerprint.measure

    def measure(path: Path) -> PckFingerprint:
        result = real_measure(path)
        measured.append(result)
        return result

    monkeypatch.setattr(PckFingerprint, "measure", measure)
    class FingerprintWorker(FakeRunWorker):
        def __init__(self, fingerprint: PckFingerprint | None) -> None:
            super().__init__()
            self.parent_fingerprint = fingerprint
            self.pck_fingerprint = {
                "source": "pool" if fingerprint is not None else "worker",
                "bytes_hashed": 0 if fingerprint is not None else 18,
            }

    started: list[FingerprintWorker] = []

    def worker_factory(_shard: int, *, pck_fingerprint: PckFingerprint | None = None) -> FingerprintWorker:
        worker = FingerprintWorker(pck_fingerprint)
        started.append(worker)
        return worker

    summary = generate_corpus(_four_element_request(), 2, corpus_root, worker_factory=worker_factory)

    assert summary["complete"] is True
    assert len(measured) == 1
    assert len(started) == 2
    assert all(worker.parent_fingerprint is measured[0] for worker in started)
    assert all(worker.pck_fingerprint == {"source": "pool", "bytes_hashed": 0} for worker in started)


@pytest.mark.skipif(_scenario_corpus.os.name != "nt", reason="PCK hints are supported on Windows")
@pytest.mark.parametrize("workers", (1, 2))
def test_a_batch_with_one_nonempty_shard_does_not_measure_a_parent_fingerprint(
    workers: int, corpus_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _scenario_corpus, "find_game_assembly",
        lambda: pytest.fail("one active shard should not discover the game pack"),
    )
    started: list[PckFingerprint | None] = []

    def worker_factory(_shard: int, *, pck_fingerprint: PckFingerprint | None = None) -> FakeRunWorker:
        started.append(pck_fingerprint)
        return FakeRunWorker()

    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("SEED1",))

    summary = generate_corpus(request, workers, corpus_root, worker_factory=worker_factory)

    assert summary["complete"] is True
    assert started == [None]


def _fresh_worker(_shard: int) -> FakeRunWorker:
    """One fresh double per shard, which is what a real worker factory builds."""
    return FakeRunWorker()


def _recording_worker(created: list[int], **options: Any) -> Callable[[int], FakeRunWorker]:
    """A factory that says which shards it was asked for, and builds the same double for each."""
    def build(shard: int) -> FakeRunWorker:
        created.append(shard)
        return FakeRunWorker(**options)
    return build


def _shard_rows(root: Path, name: str) -> list[dict[str, Any]]:
    """One shard's rows, read back through the corpus reader a caller would use."""
    return list(read_corpus(root / name))


def _read_corpus(root: Path) -> list[dict[str, Any]]:
    """Every row of a corpus, in the shard order the repository's corpus readers collect them."""
    return list(read_corpus(root))


def _recorded_summary(root: Path) -> dict[str, Any]:
    """The corpus's summary, as a reader of the artifact root finds it."""
    return json.loads((root / SUMMARY_FILE).read_text(encoding="utf-8"))


def _corpus_files(root: Path) -> dict[str, bytes]:
    """Everything a corpus wrote into its root, by name, as the bytes a diff of two corpora holds.

    The shards, compressed as they are, and the summary beside them: regenerating a corpus and
    diffing it compares all of them, so all of them are what must not move.
    """
    return {path.name: path.read_bytes() for path in sorted(root.iterdir()) if path.is_file()}


def _gzip_metadata(data: bytes) -> tuple[int, bytes]:
    """A gzip member's flags byte and modification time: the two header fields a writer may stamp.

    Read out of a gzip member as the format defines it, which is how "the metadata is pinned" is a
    measurement rather than a claim about the writer: the flags byte says whether a file name is
    embedded and the four bytes after it are the modification time.
    """
    assert data[:2] == b"\x1f\x8b", "the shard is not a gzip member"
    return data[3], data[4:8]


def _wait_until(condition: Callable[[], bool], timeout: float = 30.0) -> None:
    """Block until another shard's worker has durably recorded something, or fail the test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if condition():
                return
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(0.005)
    raise AssertionError("the corpus never recorded the shard this test was waiting for")


def test_a_batch_writes_one_shard_per_worker_and_a_summary_that_names_them(corpus_root: Path) -> None:
    summary = generate_corpus(_four_element_request(), 2, corpus_root, worker_factory=_fresh_worker)

    # Two workers, two shards, and the summary is the file a reader finds beside them.
    assert sorted(path.name for path in corpus_root.glob("*.jsonl.gz")) == ["worker-00.jsonl.gz", "worker-01.jsonl.gz"]
    assert _recorded_summary(corpus_root) == summary
    assert summary["schema"] == CORPUS_SCHEMA
    assert summary["request"] == {
        "characters": ["IRONCLAD", "DEFECT"], "ascensions": [0], "seeds": ["SEED1", "SEED2"],
    }
    assert summary["game_build"] == FakeRunWorker().build
    assert summary["workers"] == 2

    # Four elements of three offered choices each, split into contiguous blocks of two elements.
    assert summary["rows"] == {SCENARIO_RECORD: 12, FAILURE_RECORD: 0}
    assert (summary["succeeded"], summary["failed"], summary["total"]) == (12, 0, 12)
    assert summary["worker_replacements"] == 0
    assert summary["complete"] is True
    assert [
        (shard["index"], shard["file"], shard["elements"], shard["total"], shard["worker_replacements"], shard["complete"])
        for shard in summary["shards"]
    ] == [
        (0, "worker-00.jsonl.gz", [0, 1], 6, 0, True),
        (1, "worker-01.jsonl.gz", [2, 3], 6, 0, True),
    ]


def test_shard_assignment_and_row_order_are_fixed_by_the_request_and_not_by_completion_timing(
    corpus_root: Path,
) -> None:
    """A deliberately late worker moves no row to another shard and changes no row's position."""
    request = _four_element_request()
    # The second shard's worker takes its time before every run it starts, so the first shard is
    # finished and recorded long before it.
    def slow(shard: int) -> FakeRunWorker:
        return FakeRunWorker(delay_seconds=0.01 if shard else 0.0)

    generate_corpus(request, 2, corpus_root, worker_factory=slow)

    # The elements the request expands to, in order, are the rows `generate_rows` produces; the
    # shards are that sequence cut into the blocks the request assigns, whatever the timing.
    expected = generate_rows(request, FakeRunWorker())
    assert [_shard_rows(corpus_root, "worker-00.jsonl.gz"), _shard_rows(corpus_root, "worker-01.jsonl.gz")] == [
        expected[:6], expected[6:],
    ]
    assert [shard["elements"] for shard in _recorded_summary(corpus_root)["shards"]] == [[0, 1], [2, 3]]


def test_a_seed_that_fails_leaves_the_other_shards_intact_and_the_batch_completes(corpus_root: Path) -> None:
    request = _four_element_request()
    # The second shard's worker cannot reach the Ancient room, which is a failure of both of its
    # elements and of nothing else.
    def failing(shard: int) -> FakeRunWorker:
        return FakeRunWorker(crash_on={ANCIENT_ACTION: WORKER_CRASH} if shard else {})

    summary = generate_corpus(request, 2, corpus_root, worker_factory=failing)
    assert _shard_rows(corpus_root, "worker-00.jsonl.gz") == generate_rows(request, FakeRunWorker())[:6]
    failed = _shard_rows(corpus_root, "worker-01.jsonl.gz")
    assert [row["record_type"] for row in failed] == [FAILURE_RECORD, FAILURE_RECORD]
    assert {row["stage"] for row in failed} == {"ancient_room"}
    # The batch completed, and it says how much of it is not a scenario.
    assert summary["complete"] is True
    assert summary["rows"] == {SCENARIO_RECORD: 6, FAILURE_RECORD: 2}
    assert (summary["succeeded"], summary["failed"], summary["total"]) == (6, 2, 8)


def test_a_batch_resumes_without_redoing_a_completed_shard_or_changing_its_records(corpus_root: Path) -> None:
    request = _four_element_request()
    created: list[int] = []

    def interrupting(shard: int) -> FakeRunWorker:
        created.append(shard)
        if shard == 1:
            # The batch stops once the first shard is durably recorded, so what is left behind is
            # the state a killed process leaves: one complete shard and one that never landed.
            _wait_until(lambda: _recorded_summary(corpus_root)["shards"][0]["complete"])
            raise _BatchStopped
        return FakeRunWorker()

    with pytest.raises(_BatchStopped):
        generate_corpus(request, 2, corpus_root, worker_factory=interrupting)

    assert created == [0, 1]
    assert sorted(path.name for path in corpus_root.glob("*.jsonl.gz")) == ["worker-00.jsonl.gz"]
    assert _recorded_summary(corpus_root)["complete"] is False
    written, recorded = (corpus_root / "worker-00.jsonl.gz").read_bytes(), _shard_rows(corpus_root, "worker-00.jsonl.gz")

    created.clear()
    summary = generate_corpus(request, 2, corpus_root, worker_factory=_recording_worker(created))

    # Only the shard that never landed drew a worker, and the completed shard was left alone.
    assert created == [1]
    assert (corpus_root / "worker-00.jsonl.gz").read_bytes() == written
    assert _shard_rows(corpus_root, "worker-00.jsonl.gz") == recorded
    assert summary["complete"] is True
    assert _read_corpus(corpus_root) == generate_rows(request, FakeRunWorker())


def test_a_worker_that_reports_another_game_build_stops_the_batch(corpus_root: Path) -> None:
    """One corpus is of one build: rows from two would be indistinguishable once written."""
    other = copy.deepcopy(FakeRunWorker().build)
    other["version"] = "another-build"

    def mismatched(shard: int) -> FakeRunWorker:
        if shard == 0:
            return FakeRunWorker()
        _wait_until(lambda: _recorded_summary(corpus_root)["shards"][0]["complete"])
        worker = FakeRunWorker()
        worker.build = other
        return worker

    with pytest.raises(ScenarioRequestError) as raised:
        generate_corpus(_four_element_request(), 2, corpus_root, worker_factory=mismatched)

    assert "another-build" in str(raised.value)
    assert not (corpus_root / "worker-01.jsonl.gz").exists(), "a shard was written on the wrong build"
    assert _recorded_summary(corpus_root)["game_build"] == FakeRunWorker().build


def test_a_batch_whose_shards_are_all_recorded_reuses_them_without_starting_a_worker(corpus_root: Path) -> None:
    request = _four_element_request()
    first = generate_corpus(request, 2, corpus_root, worker_factory=_fresh_worker)
    created: list[int] = []

    again = generate_corpus(request, 2, corpus_root, worker_factory=_recording_worker(created))

    assert created == [], "a batch that had nothing left to write started a worker"
    assert again == first
    assert _read_corpus(corpus_root) == generate_rows(request, FakeRunWorker())


def test_a_crashed_worker_is_replaced_and_the_replacement_is_visible_in_the_summary(corpus_root: Path) -> None:
    request = _four_element_request()
    built: Counter[int] = Counter()

    def dying(shard: int) -> FakeRunWorker:
        built[shard] += 1
        # The first shard's first worker dies on its first element; its replacement is healthy.
        if shard == 0 and built[shard] == 1:
            return FakeRunWorker(die_on={ANCIENT_ACTION: WORKER_CRASH})
        return FakeRunWorker()

    summary = generate_corpus(request, 2, corpus_root, worker_factory=dying)

    assert (built[0], built[1]) == (2, 1), "the crashed shard's worker was not replaced, or another was"
    assert summary["worker_replacements"] == 1
    assert [shard["worker_replacements"] for shard in summary["shards"]] == [1, 0]
    # The element the worker died on is a failure row, and the element after it was still
    # recorded — on the replacement, which is why the batch survived the crash.
    rows = _shard_rows(corpus_root, "worker-00.jsonl.gz")
    assert [row["record_type"] for row in rows] == [FAILURE_RECORD, SCENARIO_RECORD, SCENARIO_RECORD, SCENARIO_RECORD]
    assert rows[0]["error"]["kind"] == "worker_crashed"
    assert _shard_rows(corpus_root, "worker-01.jsonl.gz") == generate_rows(request, FakeRunWorker())[6:]
    assert summary["complete"] is True


def test_excluded_first_combat_relic_keeps_the_corpus_worker_and_bytes_reproducible(
    corpus_roots: Callable[[], Path],
) -> None:
    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("SEED1", "SEED2"))
    first, second = corpus_roots(), corpus_roots()
    created: list[FakeRunWorker] = []

    def worker_factory(_shard: int) -> FakeRunWorker:
        worker = FakeRunWorker(
            offer=("GOLDEN_PEARL", "NEOWS_TORMENT", "LARGE_CAPSULE"),
            relics_after_choice={2: ("BURNING_BLOOD", "LARGE_CAPSULE", "GAMBLING_CHIP")},
        )
        created.append(worker)
        return worker

    first_summary = generate_corpus(request, 1, first, worker_factory=worker_factory)
    second_summary = generate_corpus(request, 1, second, worker_factory=worker_factory)

    assert len(created) == 2
    assert [worker.resets for worker in created] == [2, 2]
    assert all(worker.alive() for worker in created)
    assert first_summary["rows"] == {SCENARIO_RECORD: 4, FAILURE_RECORD: 2}
    assert first_summary["worker_replacements"] == 0
    assert first_summary == second_summary
    assert _corpus_files(first) == _corpus_files(second)
    assert [row["record_type"] for row in _read_corpus(first)] == [
        SCENARIO_RECORD, SCENARIO_RECORD, FAILURE_RECORD,
        SCENARIO_RECORD, SCENARIO_RECORD, FAILURE_RECORD,
    ]


def test_a_batch_with_more_workers_than_elements_still_writes_one_shard_per_worker(corpus_root: Path) -> None:
    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("SEED1",))
    created: list[int] = []

    summary = generate_corpus(request, 2, corpus_root, worker_factory=_recording_worker(created))

    assert sorted(path.name for path in corpus_root.glob("*.jsonl.gz")) == ["worker-00.jsonl.gz", "worker-01.jsonl.gz"]
    assert created == [0], "a shard that owns no element started a worker"
    assert summary["shards"][1]["elements"] == []
    assert summary["shards"][1]["complete"] is True
    assert _read_corpus(corpus_root) == generate_rows(request, FakeRunWorker())


def test_shard_names_stay_in_shard_order_past_the_second_digit(corpus_root: Path) -> None:
    """A corpus is collected by name, so a batch of a hundred shards must not sort `worker-100` first."""
    request = ScenarioRequest(
        characters=("IRONCLAD",), ascensions=(0,), seeds=tuple(f"SEED{index:03d}" for index in range(101))
    )

    summary = generate_corpus(request, 101, corpus_root, worker_factory=_fresh_worker)

    names = [path.name for path in sorted(corpus_root.glob("*.jsonl.gz"))]
    assert names == [shard["file"] for shard in summary["shards"]], "name order is not shard order"
    assert names[:2] == ["worker-000.jsonl.gz", "worker-001.jsonl.gz"] and names[-1] == "worker-100.jsonl.gz"
    assert _read_corpus(corpus_root) == generate_rows(request, FakeRunWorker())


def test_a_corpus_holds_every_branch_of_every_element_and_stays_byte_identical(
    corpus_roots: Callable[[], Path],
) -> None:
    """A branched element's rows are the corpus's rows, in order, whatever worker count wrote them.

    The element is still the shard's unit — its Ancient choices and their options are discovered by
    driving it — so a corpus holds every branch of it, written once, in element order and then in
    the order the run offered the branches. Another worker count therefore moves the shard
    boundaries and the rows by nothing.
    """
    request = _four_element_request()
    first, second, other = corpus_roots(), corpus_roots(), corpus_roots()

    def shard_worker(_shard: int) -> FakeRunWorker:
        return _branched_worker()

    summary = generate_corpus(request, 2, first, worker_factory=shard_worker)
    generate_corpus(request, 2, second, worker_factory=shard_worker)
    generate_corpus(request, 4, other, worker_factory=shard_worker)

    expected = generate_rows(request, _branched_worker())
    assert len(expected) == 16, "four elements of two reward branches and two prompt-free choices"
    assert summary["rows"] == {SCENARIO_RECORD: 16, FAILURE_RECORD: 0}
    assert _read_corpus(first) == expected
    assert _corpus_files(first) == _corpus_files(second)
    assert _read_corpus(other) == expected, "another worker count moved the rows, not only the boundaries"
    # The boundaries are the worker count's: four elements at four workers is one element each.
    assert [shard["elements"] for shard in _recorded_summary(other)["shards"]] == [[0], [1], [2], [3]]


def test_the_repositorys_existing_corpus_reader_collects_the_shards_it_wrote(
    corpus_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`compile_native_rollouts` is the repository's reader for a corpus of shards: it must find
    this corpus's files and parse them, which is what "an existing reader can consume it" means."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "python"))
    from tools.compile_native_rollouts import shard_paths

    generate_corpus(_four_element_request(), 2, corpus_root, worker_factory=_fresh_worker)

    assert shard_paths([str(corpus_root)]) == [
        corpus_root / "worker-00.jsonl.gz", corpus_root / "worker-01.jsonl.gz",
    ]


def test_a_worker_that_cannot_start_is_replaced_and_the_batch_completes(corpus_root: Path) -> None:
    """A process that will not come up is a worker, not a corpus: it is replaced like a crash."""
    created: Counter[int] = Counter()

    def failing_to_start(shard: int) -> FakeRunWorker:
        created[shard] += 1
        if shard == 0 and created[shard] == 1:
            raise NativeSimError("worker_crashed", "worker exited 1")
        return FakeRunWorker()

    summary = generate_corpus(_four_element_request(), 2, corpus_root, worker_factory=failing_to_start)

    assert (created[0], created[1]) == (2, 1), "a worker that would not start was not replaced"
    assert summary["worker_replacements"] == 1
    assert _shard_rows(corpus_root, "worker-00.jsonl.gz") == generate_rows(_four_element_request(), FakeRunWorker())[:6]
    assert summary["complete"] is True


def test_a_worker_that_will_not_start_twice_stops_the_batch(corpus_root: Path) -> None:
    def never_starts(_shard: int) -> FakeRunWorker:
        raise NativeSimError("worker_crashed", "worker exited 1")

    with pytest.raises(NativeSimError):
        generate_corpus(_four_element_request(), 1, corpus_root, worker_factory=never_starts)


def test_a_root_holding_another_request_is_refused_before_anything_is_written(corpus_root: Path) -> None:
    generate_corpus(ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("SEED1",)), 1, corpus_root,
                    worker_factory=_fresh_worker)
    before = _recorded_summary(corpus_root)
    created: list[int] = []

    with pytest.raises(ScenarioRequestError) as raised:
        generate_corpus(ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("SEED2",)), 1, corpus_root,
                        worker_factory=_recording_worker(created))

    assert created == [], "a refused request started a worker"
    assert "SEED1" in str(raised.value) and "SEED2" in str(raised.value)
    assert _recorded_summary(corpus_root) == before


def test_resuming_with_another_worker_count_is_refused_rather_than_moving_shard_boundaries(corpus_root: Path) -> None:
    request = _four_element_request()
    generate_corpus(request, 2, corpus_root, worker_factory=_fresh_worker)
    created: list[int] = []

    with pytest.raises(ScenarioRequestError) as raised:
        generate_corpus(request, 3, corpus_root, worker_factory=_recording_worker(created))

    assert created == []
    assert "2" in str(raised.value) and "3" in str(raised.value)


def test_resuming_at_another_compression_level_is_refused(corpus_root: Path) -> None:
    """A corpus is written one way: its shards cannot be at two gzip levels under one summary."""
    request = _four_element_request()
    generate_corpus(request, 2, corpus_root, worker_factory=_fresh_worker, compression=3)
    created: list[int] = []

    with pytest.raises(ScenarioRequestError) as raised:
        generate_corpus(request, 2, corpus_root, worker_factory=_recording_worker(created), compression=6)

    assert created == []
    assert "3" in str(raised.value) and "6" in str(raised.value)


def test_a_root_holding_a_summary_this_batch_did_not_write_is_refused(corpus_root: Path) -> None:
    """`native_rollout_farm` writes a `summary.json` too, and adopting it would mix two corpora."""
    (corpus_root / SUMMARY_FILE).write_text('{"workers": 6}\n', encoding="utf-8")
    created: list[int] = []

    with pytest.raises(ScenarioRequestError):
        generate_corpus(_four_element_request(), 1, corpus_root, worker_factory=_recording_worker(created))

    assert created == []
    assert json.loads((corpus_root / SUMMARY_FILE).read_text(encoding="utf-8")) == {"workers": 6}


def test_the_written_corpus_reads_back_through_the_repositorys_corpus_convention(corpus_root: Path) -> None:
    request = _four_element_request()
    summary = generate_corpus(request, 2, corpus_root, worker_factory=_fresh_worker)

    assert _read_corpus(corpus_root) == generate_rows(request, FakeRunWorker())
    assert [shard["file"] for shard in summary["shards"]] == [
        path.name for path in sorted(corpus_root.glob("*.jsonl.gz"))
    ]


def test_the_scenario_corpus_reader_names_the_format_and_keeps_the_old_alias(corpus_root: Path) -> None:
    request = _four_element_request()
    generate_corpus(request, 2, corpus_root, worker_factory=_fresh_worker)

    assert list(read_scenario_corpus(corpus_root)) == generate_rows(request, FakeRunWorker())
    assert read_corpus is read_scenario_corpus


def test_two_runs_of_one_request_write_a_byte_identical_corpus(
    corpus_roots: Callable[[], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clock is not part of a corpus, so the two runs are written far apart in clock terms.

    A gzip member carries a modification time, and the writer this repository's other corpora use
    takes it from the clock. Moving the clock between the two runs is what makes this a check rather
    than a hope: a writer that stamps the time writes different compressed bytes for the second root
    while every row agrees, and a writer that pins the metadata writes both roots alike.
    """
    request = _four_element_request()
    first, second = corpus_roots(), corpus_roots()

    monkeypatch.setattr(time, "time", lambda: 1_000_000.0)
    generate_corpus(request, 2, first, worker_factory=_fresh_worker)
    monkeypatch.setattr(time, "time", lambda: 2_000_000.0)
    generate_corpus(request, 2, second, worker_factory=_fresh_worker)

    written = _corpus_files(first)
    assert sorted(written) == [SUMMARY_FILE, "worker-00.jsonl.gz", "worker-01.jsonl.gz"]
    assert written == _corpus_files(second)
    assert _read_corpus(second) == generate_rows(request, FakeRunWorker())


def test_a_shard_holds_the_row_bytes_and_the_line_ending_the_record_declares(corpus_root: Path) -> None:
    """A shard's uncompressed bytes are the serialised rows, and nothing about the host.

    A text-mode gzip handle translates ``\\n`` to the platform's line separator, so the same corpus
    written on Windows is not the same bytes as the same corpus written anywhere else — and a reader
    that decodes with universal newlines never sees the difference, which is what makes it worth a
    test rather than a note.
    """
    request = _four_element_request()
    generate_corpus(request, 2, corpus_root, worker_factory=_fresh_worker)

    payload = gzip.decompress((corpus_root / "worker-00.jsonl.gz").read_bytes())

    rows = generate_rows(request, FakeRunWorker())
    assert payload == "".join(encode_row(row) for row in rows[:6]).encode("utf-8")
    assert b"\r" not in payload and payload.endswith(b"\n")


def test_a_shard_is_written_with_no_embedded_name_and_no_timestamp(corpus_root: Path) -> None:
    """The two gzip header fields a writer may stamp, read out of a shard a batch wrote.

    A run twice in the same second would agree by luck; a name the writer happened to choose — a
    temporary's — would make the bytes a property of the file layout rather than of the rows. Both
    fields are read here, because pinning the timestamp is what a clock cannot prove on its own.
    """
    generate_corpus(_four_element_request(), 2, corpus_root, worker_factory=_fresh_worker)

    for name in ("worker-00.jsonl.gz", "worker-01.jsonl.gz"):
        flags, mtime = _gzip_metadata((corpus_root / name).read_bytes())
        assert flags & 0x08 == 0, "the shard embeds the file name it was written as"
        assert mtime == b"\x00\x00\x00\x00", "the shard is stamped with the clock"


def test_another_worker_count_produces_the_same_rows_at_other_shard_boundaries(
    corpus_roots: Callable[[], Path],
) -> None:
    """The invariant across worker counts is the row set; the boundaries are the worker count's."""
    request = _four_element_request()
    expected = generate_rows(request, FakeRunWorker())
    boundaries: dict[int, list[list[int]]] = {}

    for workers in (1, 2, 3, 4):
        root = corpus_roots()
        summary = generate_corpus(request, workers, root, worker_factory=_fresh_worker)
        boundaries[workers] = [shard["elements"] for shard in summary["shards"]]

        assert len(list(root.glob("*.jsonl.gz"))) == workers, "a worker count did not name the shard count"
        assert _read_corpus(root) == expected, f"{workers} workers read back as other rows"

    # Four elements, so the block a shard owns is a restatement of the worker count — and no two of
    # these are the same split, which is what "a different worker count moves the boundaries" means.
    assert boundaries == {
        1: [[0, 1, 2, 3]],
        2: [[0, 1], [2, 3]],
        3: [[0, 1], [2], [3]],
        4: [[0], [1], [2], [3]],
    }


def test_a_corpus_is_byte_identical_when_the_workers_finish_in_another_order(
    corpus_roots: Callable[[], Path],
) -> None:
    """A slow worker changes when a row lands, never which bytes a shard holds."""
    request = _four_element_request()
    first, second = corpus_roots(), corpus_roots()

    def first_shard_late(shard: int) -> FakeRunWorker:
        return FakeRunWorker(delay_seconds=0.02 if shard == 0 else 0.0)

    def second_shard_late(shard: int) -> FakeRunWorker:
        return FakeRunWorker(delay_seconds=0.02 if shard == 1 else 0.0)

    generate_corpus(request, 2, first, worker_factory=second_shard_late)
    generate_corpus(request, 2, second, worker_factory=first_shard_late)

    assert _corpus_files(first) == _corpus_files(second)


# -- the bytes a corpus is made of --------------------------------------------------------


def _no_floats(token: str) -> Any:
    """Refuse a floating-point token, which is how a float in a row's *bytes* is caught."""
    raise AssertionError(f"a row serialised {token}, a floating-point number")


def _reversed_keys(record: dict[str, Any]) -> dict[str, Any]:
    """One of the record's own documents with its keys in the reverse order."""
    return {key: record[key] for key in reversed(list(record))}


def _serialised(request: ScenarioRequest, worker: RunWorker) -> str:
    """One request's rows as the bytes a shard holds them in: one serialised line per row."""
    return "".join(encode_row(row) for row in generate_rows(request, worker))


def test_no_row_serialises_a_floating_point_quantity() -> None:
    """Every quantity a record carries is an integer or a string, and its bytes say so.

    The line is parsed with a float parser that refuses to parse one, so it is the serialised bytes
    that are checked and not the row a reader gets back: `1e-05` and `0.30000000000000004` are what a
    drift looks like in a corpus, and neither is what an integer looks like.
    """
    rows = generate_rows(_four_element_request(), FakeRunWorker())

    assert len(rows) == 4 * len(RECORDED_OFFER)
    for row in rows:
        json.loads(encode_row(row), parse_float=_no_floats)


def test_a_row_is_written_in_the_declared_key_order_and_not_the_order_it_holds() -> None:
    """The record declares its key order, so the same record is the same line however it was built."""
    row = _row()

    assert list(json.loads(encode_row(row))) == [
        "schema", "record_type", "game_build", "recipe", "combat_initial_state", "state_hash",
    ]
    recipe = json.loads(encode_row(row))["recipe"]
    assert list(recipe) == [
        "character", "ascension", "seed", "act_variant", "ancient_options", "ancient_choice",
        "nested_choices", "node", "encounter",
    ]
    assert list(recipe["ancient_options"][0]) == ["option_index", "relic_model_id"]
    assert list(recipe["ancient_choice"]) == ["option_index", "relic_model_id"]
    assert list(recipe["node"]) == ["col", "row", "point_type"]

    # The record's own documents, in another order, are the same bytes: the order is the
    # declaration's and not the caller's.
    scrambled = _reversed_keys(row)
    scrambled["recipe"] = _reversed_keys(row["recipe"])
    for nested in ("ancient_choice", "node"):
        scrambled["recipe"][nested] = _reversed_keys(row["recipe"][nested])
    assert encode_row(scrambled) == encode_row(row)

    # A failure row's own keys and its error's are declared the same way.
    failure = json.loads(encode_row(_row(row_one="event")))
    assert list(failure) == ["schema", "record_type", "game_build", "recipe", "stage", "error"]
    assert list(failure["error"]) == ["kind", "message"]
    assert list(failure["recipe"]) == ["character", "ascension", "seed", "act_variant", "ancient_choice"]

    # The two values the *worker* owns are written as the capture reported them, in its order: their
    # shape is the published schema's — which is not a serialisation order — and the byte guarantee
    # is scoped to one game build, which is what fixes that order along with the values.
    capture = CAPTURES["run_combat_action"]
    state = json.loads(encode_row(row))["combat_initial_state"]
    assert list(state) == list(capture)
    assert list(state["combat"]) == list(capture["combat"])
    assert list(state["run"]) == list(capture["run"])


def test_the_same_request_serialises_to_the_same_bytes_through_the_rows_interface() -> None:
    """The row seam's format pin: one compact UTF-8 line per row, with the declared separators.

    A shard is these lines, gzipped, so this is where a row's line shape is fixed — and unlike the
    corpus-level tests above it is a pin rather than a discriminator: two runs of a deterministic
    generator serialised the same way are the same bytes whether or not the serialiser was ever at
    fault. What it holds is that a row stays one line with the declared separators, which is what
    makes the gzip metadata the only thing a corpus diff could still be reporting.
    """
    first = _serialised(_request("ancient01"), FakeRunWorker())
    second = _serialised(_request("ancient01"), FakeRunWorker())

    assert first == second
    lines = first.splitlines(keepends=True)
    assert len(lines) == len(RECORDED_OFFER) and all(line.endswith("\n") for line in lines)
    for line in lines:
        # The separators and the encoding are the record's, not an encoder default's: the line is
        # exactly what the declared serialisation of its own content is.
        assert line == json.dumps(json.loads(line), separators=(",", ":")) + "\n"


# -- the console entry point -------------------------------------------------------------


def test_the_console_entry_point_writes_the_batch_as_a_corpus(
    corpus_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sts2_native_sim import cli

    _offline_game_assembly(tmp_path, monkeypatch)
    monkeypatch.setattr(scenarios, "NativeWorker", lambda **_: FakeRunWorker())
    with pytest.raises(SystemExit) as raised:
        cli.main([
            "scenario",
            "--character", "IRONCLAD",
            "--character", "DEFECT",
            "--ascension", "0",
            "--workers", "2",
            "--output-dir", str(corpus_root),
            "--seed", "ancient01",
        ])
    assert raised.value.code == 0

    request = ScenarioRequest(characters=("IRONCLAD", "DEFECT"), ascensions=(0,), seeds=("ancient01",))
    assert _read_corpus(corpus_root) == generate_rows(request, FakeRunWorker())
    assert "6 scenario rows, 0 failure rows" in capsys.readouterr().err


def test_the_console_entry_point_writes_failure_rows_and_reports_the_counts(
    corpus_root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sts2_native_sim import cli

    monkeypatch.setattr(scenarios, "NativeWorker", lambda **_: FakeRunWorker(row_one="event"))
    with pytest.raises(SystemExit) as raised:
        cli.main(["scenario", "--character", "IRONCLAD", "--seed", "ancient01", "--output-dir", str(corpus_root)])
    assert raised.value.code == 0

    request = ScenarioRequest(characters=("IRONCLAD",), ascensions=(0,), seeds=("ancient01",))
    captured = capsys.readouterr()
    assert _read_corpus(corpus_root) == generate_rows(request, FakeRunWorker(row_one="event")), (
        "a failure row was not written as a row"
    )
    assert "0 scenario rows, 3 failure rows" in captured.err


def test_the_console_entry_point_refuses_a_colliding_request_without_starting_a_worker(
    corpus_root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sts2_native_sim import cli

    started: list[int] = []
    monkeypatch.setattr(scenarios, "NativeWorker", lambda **_: started.append(1) or FakeRunWorker())

    with pytest.raises(SystemExit) as raised:
        cli.main([
            "scenario", "--character", "IRONCLAD", "--seed", "ANCIENT01", "--seed", "anc1ent01",
            "--output-dir", str(corpus_root),
        ])

    assert raised.value.code == 2
    assert started == [], "a rejected request started a worker"
    assert list(corpus_root.iterdir()) == [], "a rejected request wrote output"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ANCIENT01" in captured.err and "anc1ent01" in captured.err
