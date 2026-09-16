"""Acceptance for the published canonical-state schema.

The schema in `schemas/canonical-state.schema.json` describes what a native capture emits
under `observation`. This script drives the simulator through every run stage a run-mode
capture can report — the Ancient room, a fight and its room rewards, a shop, a rest site, a
treasure room, an act transition, and a fight the player loses — plus the standalone modes
that emit blocks no run stage does (an item reward's `reward` block, a reward set's
`custom_rewards` block, and a combat carrying orbs), and validates every one of those real
captures against the schema.

With `--record` it writes the captures it validated to `tests/fixtures/canonical-observations.json`,
which is what `tests/test_observation_schema.py` validates offline, so re-record that file in
the same change that changes the observation shape.

Needs the shipped game and the Godot-hosted native worker: run it the way the other
`*_acceptance.py` scripts run (`pwsh scripts/build-persistent-server.ps1 -Configuration Debug`
first, then `python python/observation_schema_acceptance.py`).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from acceptance import SCENARIO
from run_composed_utility_rooms_acceptance import best_path, matching_map_action
from run_seeded_full_act_corpus import choose_action as choose_full_act_action
from run_seeded_full_act_corpus import scenario as full_act_scenario
from sts2_native_sim import NativeWorker
from sts2_native_sim.ancient import ancient_action, choice_actions, drive_choice
from sts2_native_sim.schema import ObservationSchemaViolation, validate_observation

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "canonical-observations.json"
_RUN_SEED = "CANONICAL-SCHEMA-RUN"
_STEP_LIMIT = 2000

# The run the corpus driver walks an act with: a strong deck at 9999 HP, so that every run stage is
# reachable in one drive without dying. What the captures describe is the observation's shape, not a
# balance claim.
RUN_SCENARIO = full_act_scenario(_RUN_SEED)

# A standalone combat capture that carries what a run-mode first fight does not: orbs, a
# potion slot that is occupied and one that is not, and relic counters.
COMBAT_SCENARIO = {
    **copy.deepcopy(SCENARIO),
    "seed": "CANONICAL-SCHEMA-COMBAT",
    "character": "DEFECT",
    "current_hp": 70,
    "max_hp": 75,
    "deck": (
        [{"instance_id": f"strike-{index}", "model_id": "STRIKE_DEFECT"} for index in range(4)]
        + [{"instance_id": f"defend-{index}", "model_id": "DEFEND_DEFECT"} for index in range(4)]
        + [{"instance_id": "zap-0", "model_id": "ZAP"}, {"instance_id": "dualcast-0", "model_id": "DUALCAST"}]
    ),
    "initial_hand": [],
    "relics": [{"model_id": "CRACKED_CORE"}, {"model_id": "HAPPY_FLOWER", "counter": 2}],
    "potions": [{"model_id": "ENERGY_POTION", "slot": 0}],
    "capture_orbs": True,
    "invoke_combat_entry_hooks": True,
}


def record_first(captures: dict[str, Any], name: str, observation: dict[str, Any]) -> None:
    """Keep the first capture seen under `name`; later ones describe the same shape."""
    captures.setdefault(name, observation)


def choose_action(state: dict[str, Any], planned_step: tuple[int, int, str] | None) -> str | None:
    """The action this drive takes from `state`: the planned map step, else the corpus driver's rule.

    The decision-kind cascade belongs to `run_seeded_full_act_corpus`, which walks whole acts; this
    drive only adds the planned map steps that put a shop, a rest site and a treasure room in front
    of it, so that every run stage is captured in one pass.
    """
    if state["observation"]["decision"]["kind"] == "map_choice" and planned_step is not None:
        return matching_map_action(state, planned_step)
    return choose_full_act_action(state)


def drive_run(worker: NativeWorker, captures: dict[str, Any]) -> dict[str, Any]:
    """Drive one run through the Ancient room and a full act, capturing every stage it shows.

    The drive ends at the act transition rather than walking into act 2: acts beyond act 1 are
    out of scope for this feature, and act 2's Ancient opens nested prompts the run-mode walk
    this drive uses cannot answer.
    """
    state = worker.run_reset(RUN_SCENARIO)
    record_first(captures, "run_map_choice", state["observation"])

    ancient = ancient_action(state)
    if ancient is None:
        raise AssertionError("a run does not start on the act's Ancient node")
    state = worker.run_step(ancient["action_id"])
    record_first(captures, "run_event_choice", state["observation"])
    driven = drive_choice(worker, choice_actions(state)[0])
    record_first(captures, "run_event_complete", driven.state["observation"])
    state = worker.run_step("leave_event")
    # The map the Ancient room hands back: it is a map capture like the run-start one, and the
    # floor the room advanced is the whole point of capturing both.
    record_first(captures, "run_map_after_ancient", state["observation"])

    starts = [(a["parameters"]["col"], a["parameters"]["row"]) for a in state["legal_actions"]]
    planned = best_path(state["observation"], starts)
    step_index = 0
    for _ in range(_STEP_LIMIT):
        kind = state["observation"]["decision"]["kind"]
        record_first(captures, f"run_{kind}", state["observation"])
        if kind in {"act_transition", "map_terminal", "run_terminal", "terminal"}:
            return state
        planned_step = None
        if kind == "map_choice":
            planned_step = planned[step_index] if step_index < len(planned) else None
            if planned_step is not None:
                step_index += 1
        action = choose_action(state, planned_step)
        if action is None:
            raise AssertionError(f"the run cannot leave stage {kind}")
        state = worker.run_step(action)
    raise AssertionError(f"the run exceeded {_STEP_LIMIT} native decisions")


def drive_fatal_run(worker: NativeWorker, captures: dict[str, Any]) -> None:
    """Capture the terminal observation: a run-mode fight the player loses.

    The run starts at 1 HP with no block in the deck, so the first row-1 fight ends it. Nothing
    else reports `terminal` true with the player dead, and the schema's `terminal`/`victory`
    booleans are only meaningful once a capture carries them.
    """
    state = worker.run_reset({
        **copy.deepcopy(SCENARIO),
        "seed": "CANONICAL-SCHEMA-DEATH",
        "current_hp": 1,
        "max_hp": 1,
        "deck": [{"instance_id": f"strike-{index}", "model_id": "STRIKE_IRONCLAD"} for index in range(5)],
        "initial_hand": [],
    })
    ancient = ancient_action(state)
    if ancient is None:
        raise AssertionError("a run does not start on the act's Ancient node")
    state = worker.run_step(ancient["action_id"])
    state = drive_choice(worker, choice_actions(state)[0]).state
    state = worker.run_step("leave_event")
    for _ in range(_STEP_LIMIT):
        if state["observation"]["decision"]["kind"] == "terminal":
            record_first(captures, "run_combat_terminal", state["observation"])
            return
        action = choose_full_act_action(state)
        if action is None:
            raise AssertionError("the fatal run cannot reach a terminal decision")
        state = worker.run_step(action)
    raise AssertionError(f"the fatal run exceeded {_STEP_LIMIT} native decisions")


def drive_standalone(worker: NativeWorker, captures: dict[str, Any]) -> None:
    """Capture the standalone modes that emit blocks no run stage emits."""
    record_first(captures, "standalone_combat", worker.reset(COMBAT_SCENARIO)["observation"])
    record_first(captures, "standalone_card_reward", worker.reward_reset(copy.deepcopy(SCENARIO))["observation"])
    record_first(
        captures,
        "standalone_item_reward",
        worker.item_reward_reset(copy.deepcopy(SCENARIO), "relic")["observation"],
    )
    rewards = worker.custom_reward_reset(copy.deepcopy(SCENARIO), ["card_removal", "gold"])
    record_first(captures, "standalone_custom_rewards", rewards["observation"])
    # The card-removal reward opens a card select, which is the one capture that carries an
    # outstanding choice; without taking it, that block would never be exercised.
    removal = next(
        action
        for action in rewards["legal_actions"]
        if action["parameters"].get("reward_kind") == "cardremoval"
    )
    record_first(
        captures,
        "standalone_card_select",
        worker.custom_reward_step(removal["action_id"])["observation"],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true", help=f"write the validated captures to {FIXTURE_PATH}")
    args = parser.parse_args()

    captures: dict[str, Any] = {}
    with NativeWorker() as worker:
        drive_standalone(worker, captures)
        drive_fatal_run(worker, captures)
        final = drive_run(worker, captures)

    for name, observation in captures.items():
        try:
            validate_observation(observation)
        except ObservationSchemaViolation as error:
            raise AssertionError(f"capture '{name}' does not match the published schema: {error}") from error

    if args.record:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # `newline="\n"` because the repository pins `eol=lf` in `.gitattributes`: a fixture
        # written with the platform's line endings would come back modified after a commit.
        FIXTURE_PATH.write_text(
            json.dumps(captures, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )

    print(
        json.dumps(
            {
                "success": True,
                "captures": sorted(captures),
                "capture_count": len(captures),
                "final_decision": final["observation"]["decision"]["kind"],
                "recorded_fixture": str(FIXTURE_PATH) if args.record else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
