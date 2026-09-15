"""Driving the act's Ancient room at run start.

A run the simulator starts sits on the map with the act's Ancient as its only legal
map action, exactly as a shipped run does before it enters the room: the map's own
starting point, which the shipped map screen makes travelable until the run has
travelled once. Travelling to it appends the map-point history entry a shipped run
appends and opens the Ancient's run-start choice, which the caller then sees as an
ordinary run-mode decision.

:func:`drive_choice` then resolves that choice and every prompt it opens, through the
same headless decision loop as any other run-mode decision, so a caller reaches the map
without a scene tree and without replaying the run.

Which Ancient choice a *record* takes belongs to the scenario generator, not to this
module; :func:`leave_ancient` exists only so a caller that wants the run's map back can
get there without answering every nested prompt by hand, and the rule it uses is stated
there rather than being a recording decision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .client import NativeWorker, NativeWorkerPool

ANCIENT_POINT_TYPE = "Ancient"
EVENT_COMPLETE = "event_complete"
#: The decision kind the run reports once the Ancient's choice, and everything it opened,
#: has been resolved. The room still has to be left; see :func:`leave_ancient`.
MAP_CHOICE = "map_choice"

# Ancient choices whose relic pick-up runs no second prompt. A caller that takes one of
# these reaches the map without answering a nested card, bundle, relic or reward
# prompt, so it never depends on which nested prompt kinds the simulator can drive.
# `python/ancient_choice_acceptance.py` carries the complete classification of what every
# offered Ancient relic opens, observed over the offer sweep; this is the subset the
# reachability rule below needs, kept conservative on purpose so that the rule cannot
# start preferring a choice whose prompt kind this host has not driven.
PROMPT_FREE_CHOICES = frozenset({
    "BOOMING_CONCH", "FISHING_ROD", "GOLDEN_PEARL", "PHIAL_HOLSTER", "NUTRITIOUS_OYSTER",
    "STONE_HUMIDIFIER", "LAVA_ROCK", "WINGED_BOOTS", "NEOWS_TALISMAN", "SILKEN_TRESS",
    "SILVER_CRUCIBLE",
})

_MAX_NESTED_STEPS = 64


def ancient_action(state: dict[str, Any]) -> dict[str, Any] | None:
    """The run-start map action that opens the act's Ancient room, if one is offered."""
    for action in state.get("legal_actions") or []:
        if action.get("kind") == "choose_map" and action.get("parameters", {}).get("point_type") == ANCIENT_POINT_TYPE:
            return action
    return None


def choice_actions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The Ancient's offered choices, in the order the run offered them."""
    return [action for action in state.get("legal_actions") or [] if action.get("kind") == "choose_event"]


def prompt_free_choice_action(state: dict[str, Any]) -> dict[str, Any] | None:
    """The first offered Ancient choice that opens no second prompt, index order."""
    for action in choice_actions(state):
        if action.get("parameters", {}).get("relic_model_id") in PROMPT_FREE_CHOICES:
            return action
    return None


@dataclass(frozen=True)
class NestedDecision:
    """One nested decision a choice opened, and the legal action the caller took from it."""

    state: dict[str, Any]
    action_id: str


@dataclass(frozen=True)
class DrivenChoice:
    """What taking one Ancient choice saw.

    ``decisions`` is every nested decision the choice opened, in the order they were presented,
    each with the action the caller selected from it; ``state`` is the state in which the event
    reports itself complete.
    """

    decisions: tuple[NestedDecision, ...]
    state: dict[str, Any]


def drive_choice(
    worker: NativeWorker,
    action: dict[str, Any],
    *,
    choose: Callable[[dict[str, Any]], str] | None = None,
) -> DrivenChoice:
    """Take one offered Ancient choice and answer every prompt it opens.

    The choice is applied through the game's own option-completion path, so the relic it grants
    and any randomness that consumes come from the game. Whatever it opens next — a card select,
    a reward set, a bundle pick, or a reward set inside a reward set — is a further decision on
    the same headless loop, and `choose` selects the action id to take from each one. By default
    the first legal action is taken, which is what a caller with no opinion about the nested
    choice uses; a record's own nested-choice rule belongs to the scenario generator.
    """
    state = worker.run_step(action["action_id"])
    decisions: list[NestedDecision] = []
    while state["observation"]["decision"]["kind"] != EVENT_COMPLETE:
        if not state.get("legal_actions") or len(decisions) >= _MAX_NESTED_STEPS:
            raise ValueError(
                f"the Ancient choice did not finish: "
                f"{state['observation']['decision']['kind']} after {len(decisions)} nested steps"
            )
        pick = choose(state) if choose is not None else state["legal_actions"][0]["action_id"]
        decisions.append(NestedDecision(state, pick))
        state = worker.run_step(pick)
    return DrivenChoice(tuple(decisions), state)


def leave_ancient(worker: NativeWorker, state: dict[str, Any]) -> dict[str, Any]:
    """Finish the Ancient room and return the run's map state.

    The choice is the first offered one that opens no second prompt
    (:func:`prompt_free_choice_action`), falling back to the first offered choice; any
    nested prompt it still opens is resolved by :func:`drive_choice`. That is a
    reachability rule for callers that want the map, not a record's choice rule.
    """
    choice = prompt_free_choice_action(state)
    if choice is None:
        choices = choice_actions(state)
        if not choices:
            raise ValueError("the Ancient room offers no choice to take")
        choice = choices[0]
    drive_choice(worker, choice)
    return worker.run_step("leave_event")


def start_past_ancient(pool: NativeWorkerPool, reset: dict[str, Any]) -> list[dict[str, Any]]:
    """Reset every worker into `reset` and return its run sitting on the act map.

    Every worker starts the same run, travels through the act's Ancient room and comes
    back to the map, which is the state a run-driving script wants: the Ancient is
    behind it, and the row-1 nodes are the legal map actions.
    """
    width = len(pool.workers)
    states = pool.map(lambda worker, request: worker.run_reset(request), [reset] * width)
    ancient = ancient_action(states[0])
    if ancient is None:
        raise ValueError("a run does not start on the act's Ancient node")
    states = pool.map(lambda worker, action: worker.run_step(action), [ancient["action_id"]] * width)
    states = [leave_ancient(pool.workers[index], state) for index, state in enumerate(states)]
    if any(state["observation"]["decision"]["kind"] != MAP_CHOICE for state in states):
        raise ValueError("leaving the Ancient room did not return the run to its map")
    return states
