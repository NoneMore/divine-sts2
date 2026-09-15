"""Driving the act's Ancient room at run start.

A run the simulator starts sits on the map with the act's Ancient as its only legal
map action, exactly as a shipped run does before it enters the room: the map's own
starting point, which the shipped map screen makes travelable until the run has
travelled once. Travelling to it appends the map-point history entry a shipped run
appends and opens the Ancient's run-start choice, which the caller then sees as an
ordinary run-mode decision.

Which Ancient choice a *record* takes belongs to the scenario generator, not to this
module; :func:`leave_ancient` exists only so a caller that wants the run's map back can
get there without answering every nested prompt by hand, and the rule it uses is stated
there rather than being a recording decision.
"""

from __future__ import annotations

from typing import Any

from .client import NativeWorker, NativeWorkerPool

ANCIENT_POINT_TYPE = "Ancient"

# Ancient choices whose relic pick-up runs no second prompt. A caller that takes one of
# these reaches the map without answering a nested card, bundle, relic or reward
# prompt, so it never depends on which nested prompt kinds the simulator can drive.
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


def prompt_free_choice_action(state: dict[str, Any]) -> dict[str, Any] | None:
    """The first offered Ancient choice that opens no second prompt, index order."""
    for action in state.get("legal_actions") or []:
        if action.get("kind") == "choose_event" and action.get("parameters", {}).get("relic_model_id") in PROMPT_FREE_CHOICES:
            return action
    return None


def leave_ancient(worker: NativeWorker, state: dict[str, Any]) -> dict[str, Any]:
    """Finish the Ancient room and return the run's map state.

    The choice is the first offered one that opens no second prompt
    (:func:`prompt_free_choice_action`), falling back to the first offered choice; any
    nested prompt it still opens is resolved by taking the first legal action. That is a
    reachability rule for callers that want the map, not a record's choice rule.
    """
    choice = prompt_free_choice_action(state)
    if choice is None:
        choices = [action for action in state.get("legal_actions") or [] if action.get("kind") == "choose_event"]
        if not choices:
            raise ValueError("the Ancient room offers no choice to take")
        choice = choices[0]
    state = worker.run_step(choice["action_id"])
    steps = 0
    while state["observation"]["decision"]["kind"] != "event_complete":
        if not state.get("legal_actions") or steps >= _MAX_NESTED_STEPS:
            raise ValueError(
                f"the Ancient choice did not finish: "
                f"{state['observation']['decision']['kind']} after {steps} nested steps"
            )
        state = worker.run_step(state["legal_actions"][0]["action_id"])
        steps += 1
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
    if any(state["observation"]["decision"]["kind"] != "map_choice" for state in states):
        raise ValueError("leaving the Ancient room did not return the run to its map")
    return states
