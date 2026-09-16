"""Recording one generated scenario: the run's first fight, and the recipe that reached it.

A *generated scenario* is a run-start situation together with the choices that produced it,
such that the shipped game can reproduce it from the same run seed: paste the seed into the
custom run screen, take the recorded Ancient choice, and the same fight is there. This module
is that behaviour — a request in, rows out — and `divine-sts2 scenario` is a thin wrapper
over it, so the behaviour is importable and testable rather than a sibling script.

What one row carries
--------------------

``schema`` / ``record_type``
    The versioned row tag and the row discriminator, so a corpus can hold more than one kind
    of row and a reader can tell which it has.
``game_build``
    The shipped-game build the run was played on.
``recipe``
    The portable part: the character, the Ascension, the canonical run seed (with the raw
    seed kept beside it as a diagnostic when the caller's form differed), the Act variant,
    the Ancient options the run offered *in offer order*, the Ancient choice taken, every
    nested choice resolved, the row-1 node's coordinate and point type, and the encounter id.
    This is what a caller needs to reach the same fight in the shipped game.
``combat_initial_state``
    The canonical observation of the fight at the moment it has begun and before the player
    has made any decision: the run's position and RNG counters, the encounter, turn, phase,
    energy and stars, the creatures with their generated HP and their next move, every
    ordered pile — the hand and the draw pile included, because a draw pile's order is what a
    policy learns from — and the inventory, relics in order with their counter and native
    state and potions by slot. It is a canonical observation verbatim, so it validates against
    ``schemas/canonical-state.schema.json`` and the parity comparison reads it in the shape it
    already knows.
``state_hash``
    The simulator's hash of that state, recorded so a corpus can be diffed. It is a simulator
    artifact with no shipped-game counterpart, so it is deliberately not part of the parity
    contract.

The record is a *recipe*, not a state snapshot: it stores no state handle and no portable
branch, both of which name a node in one worker's local history rather than anything the
shipped game can reproduce.

The fixed rules
---------------

Each rule is fixed so that two runs of one request cannot disagree about which situation they
mean, and each is recorded so it can be audited and later replaced:

* **The Ancient choice is the first one the run offered**, in the order the run offered it.
* **A nested prompt is answered with the first legal action the environment reports** for it —
  one rule for every nested kind, whether that is a card select, a bundle pick, a reward set,
  or a reward set opened inside one. A reward pick names a reward index rather than option
  ids, so such a choice records an empty ``selected_option_ids`` and its selected index is the
  identity of what it picked.
* **The row-1 node is the first legal map action** in the order the environment reports them,
  with the coordinate and point type it picked recorded on the row.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Protocol

from .ancient import (
    LEAVE_EVENT_ACTION,
    MAP_CHOICE,
    DrivenChoice,
    NestedDecision,
    RunStepWorker,
    ancient_action,
    choice_actions,
    drive_choice,
    map_actions,
)

#: The versioned row tag, and the discriminator a success row carries.
ROW_SCHEMA = "sts2-native-sim/scenario-record/1"
SCENARIO_RECORD = "scenario"

#: The decision the run reports when the row-1 node has resolved into a fight.
COMBAT_ACTION = "combat_action"

#: The stages a generation can stop at, named where the run stopped rather than where the
#: generation intended to go next. Ticket 08 turns one of these into a failure row's `stage`.
STAGE_ANCIENT_ROOM = "ancient_room"
STAGE_ANCIENT_CHOICE = "ancient_choice"
STAGE_LEAVE_ANCIENT = "leave_ancient"
STAGE_ROW_ONE_NODE = "row_one_node"
STAGE_FIRST_COMBAT = "first_combat"

#: The nested actions that select a reward rather than choice options, so they carry no
#: `option_ids`; every other nested action must name the option ids it selected.
_REWARD_ACTIONS = frozenset({"choose_custom_reward", "skip_custom_rewards"})


class ScenarioGenerationError(RuntimeError):
    """A run could not be driven to its first fight. ``stage`` names where it stopped."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


class RunWorker(RunStepWorker, Protocol):
    """The part of :class:`~sts2_native_sim.client.NativeWorker` a generation uses."""

    def run_reset(self, state: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ScenarioRequest:
    """One scenario to record: a character, an Ascension and a run seed as the caller typed it."""

    character: str
    ascension: int
    seed: str

    @property
    def character_model_id(self) -> str:
        """The character named the way the game names it.

        The environment looks a character up case-insensitively, and the model id it resolves
        to is the one on the player's creature row, so the record names the run's character in
        that form rather than echoing whatever case the caller typed.
        """
        return self.character.upper()


@dataclass(frozen=True)
class _DrivenRun:
    """What one drive of the run reached: the seed it started on and the fight it arrived at."""

    seed: str
    offered: list[dict[str, Any]]
    choice: dict[str, Any]
    driven: DrivenChoice
    node: dict[str, Any]
    observation: dict[str, Any]
    state_hash: str


def canonicalize_seed(seed: str) -> str:
    """Port of the shipped ``SeedHelper.CanonicalizeSeed``.

    Upper-case, ``O`` → ``0``, ``I`` → ``1``, then trim — in that order, because the shipped
    method replaces before it trims and so an internal space survives. The canonical form is
    what the shipped game stores for a run and what a corpus must paste back into the custom
    run screen, so it is what the request carries and the record stores; the caller's own form
    is kept beside it as a diagnostic rather than rejected.
    """
    return seed.upper().replace("O", "0").replace("I", "1").strip()


def generate_rows(request: ScenarioRequest, worker: RunWorker) -> list[dict[str, Any]]:
    """Drive one run to its first fight and return the scenario row it recorded.

    The tracer bullet records exactly one row per request; ticket 07 widens the request to a
    product of character, Ascension and seed sets, at which point this returns one row per
    element of the expanded request.
    """
    return [_row(request, _drive_to_first_fight(request, worker))]


def _drive_to_first_fight(request: ScenarioRequest, worker: RunWorker) -> _DrivenRun:
    """Drive one run from its start to its first fight, or fail at the stage it stopped at."""
    seed = canonicalize_seed(request.seed)
    state = worker.run_reset(_reset_state(request, seed))

    ancient = ancient_action(state)
    if ancient is None:
        raise ScenarioGenerationError(STAGE_ANCIENT_ROOM, "the run does not start on the act's Ancient node")
    state = worker.run_step(ancient["action_id"])

    offered = _offered_options(state)
    choices = choice_actions(state)
    if not choices:
        raise ScenarioGenerationError(STAGE_ANCIENT_CHOICE, "the Ancient room offers no choice to take")
    choice = choices[0]
    try:
        driven = drive_choice(worker, choice)
    except ValueError as error:
        raise ScenarioGenerationError(STAGE_ANCIENT_CHOICE, str(error)) from error

    state = worker.run_step(LEAVE_EVENT_ACTION)
    if state["observation"]["decision"]["kind"] != MAP_CHOICE:
        raise ScenarioGenerationError(
            STAGE_LEAVE_ANCIENT,
            f"leaving the Ancient room returned "
            f"{state['observation']['decision']['kind']!r} instead of the run's map",
        )

    nodes = map_actions(state)
    if not nodes:
        raise ScenarioGenerationError(STAGE_ROW_ONE_NODE, "the map after the Ancient room offers no node to travel to")
    node = nodes[0]
    combat = worker.run_step(node["action_id"])
    observation = combat["observation"]
    if observation["decision"]["kind"] != COMBAT_ACTION:
        raise ScenarioGenerationError(
            STAGE_FIRST_COMBAT,
            f"the row-1 node resolved to {observation['decision']['kind']!r}, not a fight",
        )
    return _DrivenRun(seed, offered, choice, driven, node, observation, combat["state_hash"])


def _reset_state(request: ScenarioRequest, seed: str) -> dict[str, Any]:
    """The run-start request for one scenario: the shipped starting loadout, fully unlocked.

    The character and Ascension come from the request and nothing else does, because a
    caller-supplied deck, relic set or potion list would produce a situation the shipped game
    cannot reach. The fields the starting-loadout path ignores are still sent, because the
    environment's reset request declares them.
    """
    return {
        "game_build": {},
        "seed": seed,
        "rng_counters": {},
        "character": request.character_model_id,
        "ascension": request.ascension,
        "encounter": "first",
        "current_hp": 80,
        "max_hp": 80,
        "deck": [],
        "gold": 99,
        "use_character_starting_loadout": True,
    }


def _choice_identity(parameters: dict[str, Any]) -> dict[str, Any]:
    """What identifies one offered Ancient choice: its offer index and the relic it grants.

    An event option reports the two at its top level and a `choose_event` action reports them
    under `parameters`, so one shape reads both.
    """
    return {"option_index": parameters.get("option_index"), "relic_model_id": parameters.get("relic_model_id")}


def _offered_options(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The Ancient's offered choices, in the order the run offered them."""
    event = state["observation"].get("event")
    if not isinstance(event, dict):
        raise ScenarioGenerationError(STAGE_ANCIENT_ROOM, "the Ancient node did not open the Ancient's event room")
    return [_choice_identity(option) for option in event.get("options") or []]


def _row(request: ScenarioRequest, walk: _DrivenRun) -> dict[str, Any]:
    """One scenario row, with its keys in the order the record declares them."""
    parameters = walk.choice.get("parameters") or {}
    node_parameters = walk.node["parameters"]
    recipe: dict[str, Any] = {
        "character": request.character_model_id,
        "ascension": request.ascension,
        "seed": walk.seed,
    }
    if request.seed != walk.seed:
        recipe["raw_seed"] = request.seed
    recipe.update({
        "act_variant": walk.observation["run"]["act_variant"],
        "ancient_options": walk.offered,
        "ancient_choice": _choice_identity(parameters),
        "nested_choices": [_nested_choice(decision) for decision in walk.driven.decisions],
        "node": {
            "col": node_parameters["col"],
            "row": node_parameters["row"],
            "point_type": node_parameters["point_type"],
        },
        "encounter": walk.observation["combat"]["encounter"],
    })
    return {
        "schema": ROW_SCHEMA,
        "record_type": SCENARIO_RECORD,
        "game_build": copy.deepcopy(walk.observation["game_build"]),
        "recipe": recipe,
        "combat_initial_state": copy.deepcopy(walk.observation),
        "state_hash": walk.state_hash,
    }


def _nested_choice(decision: NestedDecision) -> dict[str, Any]:
    """One nested decision, and the action the fixed rule took from it."""
    state = decision.state
    actions = state.get("legal_actions") or []
    picked = next(
        ((index, action) for index, action in enumerate(actions) if action.get("action_id") == decision.action_id),
        None,
    )
    if picked is None:
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the nested choice took {decision.action_id!r}, which the prompt did not offer",
        )
    index, action = picked
    option_ids = (action.get("parameters") or {}).get("option_ids")
    if option_ids is None and action.get("kind") not in _REWARD_ACTIONS:
        # An action that selects options has to say which; a record that quietly stored an
        # empty selection would look like a choice of nothing rather than a missing fact.
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the {action.get('kind')!r} action {decision.action_id!r} names no option ids",
        )
    return {
        "kind": state["observation"]["decision"]["kind"],
        "selected_index": index,
        "selected_option_ids": list(option_ids) if isinstance(option_ids, list) else [],
    }
