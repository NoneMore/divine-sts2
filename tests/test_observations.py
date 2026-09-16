"""Offline tests for observation projection, permutation invariance, and fog-of-war masking."""
import json
from pathlib import Path
from typing import Any

import pytest
from sts2_native_sim.observations import (
    extract_agent_observation,
    project_player_visible_card_state,
    to_agent_observation,
)

# Captures recorded from the native worker by `python/observation_schema_acceptance.py --record`.
_CAPTURES: dict[str, dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "canonical-observations.json").read_text(encoding="utf-8")
)

def test_draw_pile_permutation_invariance():
    """Verify that shuffle/order changes in raw draw pile produce identical agent observations."""
    card_a = {"model_id": "STRIKE_IRONCLAD", "upgrades": 0, "energy_cost": 1, "card_type": "Attack"}
    card_b = {"model_id": "DEFEND_IRONCLAD", "upgrades": 0, "energy_cost": 1, "card_type": "Skill"}
    card_c = {"model_id": "BASH", "upgrades": 1, "energy_cost": 2, "card_type": "Attack"}

    obs_order_1 = {
        "combat": {
            "piles": [
                {"name": "DrawPile", "cards": [card_a, card_b, card_c]},
                {"name": "Hand", "cards": []},
            ],
            "creatures": [],
        },
        "run": {
            "seed": "SECRET_SEED_123",
            "rng_counters": {"Shuffle": 42},
        },
    }

    obs_order_2 = {
        "combat": {
            "piles": [
                {"name": "DrawPile", "cards": [card_c, card_a, card_b]},
                {"name": "Hand", "cards": []},
            ],
            "creatures": [],
        },
        "run": {
            "seed": "SECRET_SEED_123",
            "rng_counters": {"Shuffle": 42},
        },
    }

    agent_obs_1 = extract_agent_observation({"observation": obs_order_1})
    agent_obs_2 = extract_agent_observation({"observation": obs_order_2})

    draw_1 = agent_obs_1["combat"]["draw_pile_summary"]
    draw_2 = agent_obs_2["combat"]["draw_pile_summary"]

    assert draw_1["count"] == 3
    assert draw_1["count"] == draw_2["count"]
    assert draw_1["histogram"] == draw_2["histogram"]
    assert draw_1["cards_unordered"] == draw_2["cards_unordered"]

def test_seed_and_rng_masking():
    """Verify that seeds and RNG counters are masked."""
    raw_state = {
        "observation": {
            "run": {
                "seed": "RAW_SUPER_SECRET_SEED",
                "rng_counters": {"Combat": 10, "CardRng": 99},
            },
            "combat": {"piles": []},
        },
    }
    agent_obs = extract_agent_observation(raw_state)
    assert agent_obs["run"]["seed"] == "MASKED"
    assert agent_obs["run"]["rng_counters"] == {}

def test_act_variant_is_reported_in_the_agent_observation():
    """Verify that the Act variant in play reaches a caller while the seed stays masked."""
    raw_state = {
        "observation": {
            "run": {
                "seed": "RAW_SUPER_SECRET_SEED",
                "ascension": 0,
                "act_variant": "UNDERDOCKS",
                "rng_counters": {"UpFront": 410},
            },
            "combat": {"piles": []},
        },
    }
    agent_obs = extract_agent_observation(raw_state)
    assert agent_obs["run"]["act_variant"] == "UNDERDOCKS"
    assert agent_obs["run"]["seed"] == "MASKED"


def test_act_variant_is_not_invented_when_the_observation_omits_it():
    """Verify that an observation without an Act in play reports no Act variant."""
    agent_obs = extract_agent_observation({"observation": {"run": {"seed": "SEED"}, "combat": {"piles": []}}})
    assert "act_variant" not in agent_obs["run"]


def test_the_agent_observation_carries_every_field_of_the_canonical_run_and_combat_blocks():
    """Verify the projection cannot silently drop a field the canonical observation gained.

    A run-mode combat capture is the shape a policy is handed, so every field of its `run` and
    `combat` blocks must reach the agent observation; only the deliberately masked (`seed`,
    `rng_counters`) and transformed (`piles`) blocks may differ in value. The fixture is
    recorded from the native worker, so a new canonical field fails here until the projection
    reports it and the fixture is re-recorded.
    """
    canonical = _CAPTURES["run_combat_action"]
    agent = extract_agent_observation({"observation": canonical})

    assert set(canonical["run"]) <= set(agent["run"])
    assert set(canonical["combat"]) <= set(agent["combat"])
    assert agent["run"]["seed"] == "MASKED"
    assert agent["run"]["rng_counters"] == {}
    assert agent["run"]["act_index"] == canonical["run"]["act_index"]
    assert agent["run"]["total_floor"] == canonical["run"]["total_floor"]
    assert agent["combat"]["encounter"] == canonical["combat"]["encounter"]


def test_evolving_card_state_whitelisting():
    """Verify that player-visible dynamic state is kept while hidden flags are stripped."""
    raw_native_state = {
        "Damage": 15,
        "Block": 22,
        "MagicNumber": 3,
        "InternalPointer": 0xDEADBEEF,
        "PrivateRngStream": "HIDDEN",
        "_cachedHash": "ABC",
    }
    projected = project_player_visible_card_state(raw_native_state)
    assert "Damage" in projected
    assert "Block" in projected
    assert "MagicNumber" in projected
    assert "InternalPointer" not in projected
    assert "PrivateRngStream" not in projected
    assert "_cachedHash" not in projected
