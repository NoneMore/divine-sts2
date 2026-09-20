"""Offline checks that the published canonical-state schema describes what a capture emits.

The captures in `tests/fixtures/canonical-observations.json` are recorded from the
shipped-game-backed native worker by `tests/acceptance/observation_schema_acceptance.py --record`,
which also validates them live. Re-record that file in the same change that changes the
observation shape; these tests are what makes the schema a check rather than a document.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from sts2_native_sim import paths
from sts2_native_sim.schema import (
    ObservationSchemaViolation,
    observation_schema_version,
    validate_observation,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "canonical-observations.json"
CAPTURES: dict[str, dict[str, Any]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

#: Every run stage the fixture has to cover, and the block the stage adds to the observation.
#: `None` means the stage carries only the run block and its decision — no combat block, no
#: inventory — which is the case a schema requiring either of them gets wrong.
RUN_STAGES: dict[str, str | None] = {
    "run_map_choice": "map",
    "run_map_after_ancient": "map",
    "run_event_choice": "event",
    "run_event_complete": "event",
    "run_combat_action": "combat",
    "run_combat_terminal": "combat",
    "run_room_reward_choice": "room_rewards",
    "run_rest_choice": "rest_site",
    "run_rest_complete": "rest_site",
    "run_shop_choice": "shop",
    "run_treasure_open": "treasure",
    "run_treasure_relic_choice": "treasure",
    "run_act_transition": None,
}

#: The standalone modes cover blocks no run stage emits: a reward's `reward` block, a reward
#: set's `custom_rewards` block, an outstanding choice, and a combat carrying orbs.
STANDALONE_STAGES = (
    "standalone_combat",
    "standalone_card_reward",
    "standalone_item_reward",
    "standalone_custom_rewards",
    "standalone_card_select",
)


@pytest.mark.parametrize("name", sorted(CAPTURES))
def test_every_recorded_capture_validates_against_the_published_schema(name: str) -> None:
    validate_observation(CAPTURES[name])


def test_the_fixture_covers_every_run_stage_and_the_standalone_blocks() -> None:
    missing = (set(RUN_STAGES) | set(STANDALONE_STAGES)) - set(CAPTURES)
    assert not missing, f"the recorded fixture does not cover {sorted(missing)}"


def test_the_run_stages_that_carry_no_combat_block_are_covered() -> None:
    for name, block in RUN_STAGES.items():
        if block == "combat":
            continue
        observation = CAPTURES[name]
        assert "combat" not in observation, f"{name} unexpectedly carries a combat block"
        assert "inventory" not in observation, f"{name} unexpectedly carries an inventory block"
        if block is not None:
            assert block in observation, f"{name} does not carry its {block} block"


def test_the_floor_the_ancient_room_advances_is_directly_observable() -> None:
    """The counters move 0 → 1 → 2 across the room and the row-1 node, on the observation itself."""
    start = CAPTURES["run_map_choice"]["run"]
    after_ancient = CAPTURES["run_map_after_ancient"]["run"]
    fight = CAPTURES["run_combat_action"]["run"]

    assert (start["total_floor"], after_ancient["total_floor"], fight["total_floor"]) == (0, 1, 2)
    assert (start["act_floor"], after_ancient["act_floor"], fight["act_floor"]) == (0, 1, 2)
    assert {run["act_index"] for run in (start, after_ancient, fight)} == {0}


def test_a_run_mode_combat_capture_names_its_fight_and_its_place_in_the_run() -> None:
    observation = CAPTURES["run_combat_action"]
    encounter = observation["combat"]["encounter"]
    assert isinstance(encounter, str) and encounter

    run = observation["run"]
    assert run["act_variant"] and run["act_index"] == 0
    assert run["total_floor"] == 2 and run["act_floor"] == 2


def test_a_lost_fight_reports_itself_as_a_terminal_capture() -> None:
    observation = CAPTURES["run_combat_terminal"]

    assert observation["terminal"] is True
    assert observation["victory"] is False
    assert observation["decision"] == {"kind": "terminal", "legal_actions": []}
    assert not any(creature["alive"] for creature in observation["combat"]["creatures"] if creature["side"] == "Player")


def test_the_schema_rejects_a_combat_capture_that_names_no_encounter() -> None:
    broken = copy.deepcopy(CAPTURES["run_combat_action"])
    del broken["combat"]["encounter"]

    with pytest.raises(ObservationSchemaViolation, match="encounter"):
        validate_observation(broken)


def test_the_schema_requires_a_fight_to_name_its_place_in_the_run() -> None:
    broken = copy.deepcopy(CAPTURES["run_combat_action"])
    del broken["run"]["total_floor"]

    with pytest.raises(ObservationSchemaViolation, match="total_floor"):
        validate_observation(broken)


def test_the_schema_does_not_require_a_place_in_the_run_from_a_stage_without_a_fight() -> None:
    # A stage with no combat block is not required to place the run, so stripping whatever it
    # reports about the act leaves it valid — which is what keeps the conditional requirement
    # above from applying to the ten captures it would be wrong for.
    stripped = copy.deepcopy(CAPTURES["run_shop_choice"])
    for key in ("act_index", "act_floor", "total_floor"):
        stripped["run"].pop(key, None)

    validate_observation(stripped)


def test_the_schema_rejects_a_block_it_does_not_describe() -> None:
    broken = copy.deepcopy(CAPTURES["run_map_choice"])
    broken["map"]["unexpected"] = 1

    with pytest.raises(ObservationSchemaViolation):
        validate_observation(broken)


def test_the_published_observation_and_hash_schema_versions_moved_together() -> None:
    """The observation's shape is published under two version pins, and both belong to one change.

    The schema's `const` and the environment's `ObservationSchemaVersion` must agree, and the hash
    payload's own `hash_schema_version` — which has no other home, since it is not on the wire —
    is pinned here so that reverting either half of the bump fails a test rather than nothing.
    """
    messages = (paths.REPOSITORY_ROOT / "src" / "Sts2.NativeSim.Protocol" / "Messages.cs").read_text(encoding="utf-8")
    environment = (
        paths.REPOSITORY_ROOT / "src" / "Sts2.NativeSim.Core" / "PersistentNativeCombatEnvironment.cs"
    ).read_text(encoding="utf-8")

    observation_constant = re.search(r"ObservationSchemaVersion\s*=\s*(\d+)", messages)
    hash_constant = re.search(r"hash_schema_version\s*=\s*(\d+)", environment)
    assert observation_constant, "the protocol constant is not declared where this test looks for it"
    assert hash_constant, "the hash payload version is not declared where this test looks for it"

    assert observation_schema_version() == int(observation_constant.group(1)) == 3
    assert int(hash_constant.group(1)) == 4
