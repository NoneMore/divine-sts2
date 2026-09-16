"""Shipped-game acceptance for the scenario record the generator writes.

`sts2_native_sim.scenarios.generate_rows` is the generator's public interface: a request in,
rows out. This script drives real native workers through it and checks, per sample, the claims
a generated scenario makes — with the game, not with the generator's own helpers:

* the record's seed is the canonical form the shipped ``SeedHelper.CanonicalizeSeed`` derives
  from the string the caller passed, and the raw string is kept as a diagnostic exactly when
  the two differ;
* the Act variant on the record is the one an independent port of the shipped act roll
  produces for that canonical seed;
* the offered Ancient options are the ones an independent port of ``Neow``'s
  ``GenerateInitialOptions`` produces, *in the order the run offered them*;
* **every Ancient choice the run offers is recorded**: one row per offered option, in offer
  order, each row taking the option at its own index and carrying the same offer and the same
  run identity — so no opening is invented and none is skipped;
* the row-1 node is on row 1 and typed ``Monster``, and the record names its coordinate;
* the combat initial state is a canonical observation, validates against the published
  schema, and carries the enemies with their generated HP, every ordered pile — the hand and
  the draw pile included — the relics, the potions by slot, the player's HP and the run's gold
  and named RNG counters;
* **the record is a recipe**: a second run driven from the recorded fields alone — the
  canonical seed, the Ancient choice *index*, each nested choice's *index*, and the node
  *coordinate* — reaches the same state hash as the record. That is the simulator-side half of
  "paste the seed into the shipped game's custom run screen and the same fight is there": it
  shows the record carries enough to reproduce the situation and nothing that a fresh run
  cannot reproduce;
* the same request on a second worker produces the same rows, field for field (byte-identical
  *output* is ticket 10's, and needs the serialiser this script does not use).

The nested choice is resolved by a fixed rule (the first legal action the prompt reports), so
the sample says which nested-prompt kinds it actually covered: the recorded table carries the
kinds each Ancient choice's row resolved, and a kind that stops being covered is a failure
rather than a silent narrowing.

Requires the shipped game and a Godot-hosted worker (the repository's ``*_acceptance.py``
convention). ``--snapshot`` prints the per-sample facts instead of asserting them, which is
how the recorded table below is maintained.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from act_variant_acceptance import rolled_act_variant
from ancient_room_acceptance import neow_offer
from sts2_native_sim import NativeWorkerPool
from sts2_native_sim.ancient import MAP_CHOICE, ancient_action, choice_actions
from sts2_native_sim.scenarios import SCENARIO_RECORD, ScenarioRequest, canonicalize_seed, generate_rows
from sts2_native_sim.schema import validate_observation

_EVENT_COMPLETE = "event_complete"
#: The row-1 nodes are the act's weak monsters, and the run's floor bookkeeping is at 2 there:
#: one entry for the Ancient room and one for the node.
_ROW_ONE_POINT_TYPE = "Monster"
_FIRST_FIGHT_FLOOR = 2


@dataclass(frozen=True)
class Sample:
    """One request the script records, and what makes it worth recording."""

    character: str
    ascension: int
    seed: str

    @property
    def label(self) -> str:
        return f"{self.character}@A{self.ascension}/{self.seed}"


# Both Act variants, two characters, a non-default Ascension, and both halves of the seed
# diagnostic: `SCENAR10A01`, `TRACERBULLET` and `GYMSCENAR10` are already canonical, while
# `ANCIENT01`, `ANCIENT03` and `ANCIENT06` are rewritten by the shipped transform (their `I`
# becomes `1`), so their rows must carry the raw string beside the canonical one.
_SAMPLE = (
    Sample("IRONCLAD", 0, "SCENAR10A01"),
    Sample("IRONCLAD", 0, "ANCIENT01"),
    Sample("IRONCLAD", 0, "GYMSCENAR10"),
    Sample("IRONCLAD", 2, "ANCIENT03"),
    Sample("DEFECT", 0, "TRACERBULLET"),
    Sample("DEFECT", 0, "ANCIENT06"),
)

# What this sample observed on the build below, recorded with `--snapshot`: the canonical
# seed, the offered relic ids in offer order, the choice taken, the nested-prompt kinds each
# record answered, the node it travelled to, the encounter and the fight's state hash. The
# table pins the sample's coverage — three prompt-free records and three that resolved a
# nested choice, `card_choice` and `custom_reward_choice` among them — so a change in either
# is visible rather than silent. Each entry is the row for the *first* offered choice; the
# other choices have a row of their own, and `_assert_enumeration` covers those.
_OBSERVED_BUILD = "A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52"
_OBSERVED: dict[str, dict[str, Any]] = {
    "IRONCLAD@A0/SCENAR10A01": {
        "canonical_seed": "SCENAR10A01", "raw_seed": None, "act_variant": "OVERGROWTH",
        "offered": ["ARCANE_SCROLL", "LAVA_ROCK", "LEAFY_POULTICE"],
        "chosen": {"option_index": 0, "relic_model_id": "ARCANE_SCROLL"},
        "nested_kinds": [], "node": {"col": 1, "row": 1, "point_type": "Monster"},
        "encounter": "NIBBITS_WEAK",
        "state_hash": "8CB1BA64112F0F3C3FCC23CFAA2B3A8A763EB1906B5BA727A8E898BCB0EC467C",
    },
    "IRONCLAD@A0/ANCIENT01": {
        "canonical_seed": "ANC1ENT01", "raw_seed": "ANCIENT01", "act_variant": "OVERGROWTH",
        "offered": ["BOOMING_CONCH", "GOLDEN_PEARL", "PRECARIOUS_SHEARS"],
        "chosen": {"option_index": 0, "relic_model_id": "BOOMING_CONCH"},
        "nested_kinds": [], "node": {"col": 0, "row": 1, "point_type": "Monster"},
        "encounter": "SLIMES_WEAK",
        "state_hash": "92807FCE02322DEB374757D3089819469491647BD61436CEBB6338D7D02935B4",
    },
    "IRONCLAD@A0/GYMSCENAR10": {
        "canonical_seed": "GYMSCENAR10", "raw_seed": None, "act_variant": "UNDERDOCKS",
        "offered": ["BOOMING_CONCH", "SCROLL_BOXES", "LEAFY_POULTICE"],
        "chosen": {"option_index": 0, "relic_model_id": "BOOMING_CONCH"},
        "nested_kinds": [], "node": {"col": 0, "row": 1, "point_type": "Monster"},
        "encounter": "SEAPUNK_WEAK",
        "state_hash": "53ACDAB2886CC07E57CB14AC5D26FB2CF1876AB6E51AA94B4A0805150D8933C3",
    },
    "IRONCLAD@A2/ANCIENT03": {
        "canonical_seed": "ANC1ENT03", "raw_seed": "ANCIENT03", "act_variant": "UNDERDOCKS",
        "offered": ["NEW_LEAF", "NEOWS_TORMENT", "NEOWS_BONES"],
        "chosen": {"option_index": 0, "relic_model_id": "NEW_LEAF"},
        "nested_kinds": ["card_choice"], "node": {"col": 1, "row": 1, "point_type": "Monster"},
        "encounter": "SEAPUNK_WEAK",
        "state_hash": "D2193DDC0B599467E3906395BD51673E03C61F8FB9D9F6DEF17092C3A47C90E1",
    },
    "DEFECT@A0/TRACERBULLET": {
        "canonical_seed": "TRACERBULLET", "raw_seed": None, "act_variant": "OVERGROWTH",
        "offered": ["PRECISE_SCISSORS", "BOOMING_CONCH", "SILKEN_TRESS"],
        "chosen": {"option_index": 0, "relic_model_id": "PRECISE_SCISSORS"},
        "nested_kinds": ["card_choice"], "node": {"col": 0, "row": 1, "point_type": "Monster"},
        "encounter": "SLIMES_WEAK",
        "state_hash": "DAAB57C1BEE778896E9598164EF7FAB3A1BE7BF992527E66BA956FBE4BDDA69E",
    },
    "DEFECT@A0/ANCIENT06": {
        "canonical_seed": "ANC1ENT06", "raw_seed": "ANCIENT06", "act_variant": "UNDERDOCKS",
        "offered": ["LOST_COFFER", "NEOWS_TALISMAN", "LEAFY_POULTICE"],
        "chosen": {"option_index": 0, "relic_model_id": "LOST_COFFER"},
        "nested_kinds": ["custom_reward_choice", "custom_reward_choice"],
        "node": {"col": 2, "row": 1, "point_type": "Monster"},
        "encounter": "CORPSE_SLUGS_WEAK",
        "state_hash": "923DDDF8E11C99D3CED8B2CCA159A3950ECA52A9EDEBBB08DCECE251378F5416",
    },
}

# What the batch recorded for each sample, one entry per Ancient choice the run offered, in
# offer order: the choice taken, the nested-prompt kinds that choice's row resolved, the node it
# travelled to, and the fight's state hash. This is the enumeration the generator promises —
# every offered choice, and nothing but offered choices — pinned against the game. Maintained
# with `--snapshot`, whose `choices` list is this literal.
_OBSERVED_CHOICES: dict[str, list[dict[str, Any]]] = {
    "IRONCLAD@A0/SCENAR10A01": [
        {
            "ancient_choice": {"option_index": 0, "relic_model_id": "ARCANE_SCROLL"},
            "nested_kinds": [],
            "node": {"col": 1, "row": 1, "point_type": "Monster"},
            "state_hash": "8CB1BA64112F0F3C3FCC23CFAA2B3A8A763EB1906B5BA727A8E898BCB0EC467C",
        },
        {
            "ancient_choice": {"option_index": 1, "relic_model_id": "LAVA_ROCK"},
            "nested_kinds": [],
            "node": {"col": 1, "row": 1, "point_type": "Monster"},
            "state_hash": "B131A6AE2F6F20E1AE07DAB003262B14EF242A327E6479CEFF18460F1546CA65",
        },
        {
            "ancient_choice": {"option_index": 2, "relic_model_id": "LEAFY_POULTICE"},
            "nested_kinds": [],
            "node": {"col": 1, "row": 1, "point_type": "Monster"},
            "state_hash": "3F6B437EE520C61A02F4490D7AF07BA829B389162AB01B291220F53859150514",
        },
    ],
    "IRONCLAD@A0/ANCIENT01": [
        {
            "ancient_choice": {"option_index": 0, "relic_model_id": "BOOMING_CONCH"},
            "nested_kinds": [],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "92807FCE02322DEB374757D3089819469491647BD61436CEBB6338D7D02935B4",
        },
        {
            "ancient_choice": {"option_index": 1, "relic_model_id": "GOLDEN_PEARL"},
            "nested_kinds": [],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "24C84A8D6149F61B3404ED9A7BD2751482E55642D08CDEEEF95F2C9B08CF63AF",
        },
        {
            "ancient_choice": {"option_index": 2, "relic_model_id": "PRECARIOUS_SHEARS"},
            "nested_kinds": ["card_choice"],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "39728C896A5AA22C2ACBA91D5F3C350F2AA82C3F1F08AE06B5A5C3A003BCF452",
        },
    ],
    "IRONCLAD@A0/GYMSCENAR10": [
        {
            "ancient_choice": {"option_index": 0, "relic_model_id": "BOOMING_CONCH"},
            "nested_kinds": [],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "53ACDAB2886CC07E57CB14AC5D26FB2CF1876AB6E51AA94B4A0805150D8933C3",
        },
        {
            "ancient_choice": {"option_index": 1, "relic_model_id": "SCROLL_BOXES"},
            "nested_kinds": ["option_choice"],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "C0A5E68ECE7056DEF167A4351172AAFFE07884F18BFC3D4CAC3708C41C4BA3A6",
        },
        {
            "ancient_choice": {"option_index": 2, "relic_model_id": "LEAFY_POULTICE"},
            "nested_kinds": [],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "76FDECEFE556B89D3A853C8B7F201D854E4D720A30198C5D7B9783EA5ADCA46C",
        },
    ],
    "IRONCLAD@A2/ANCIENT03": [
        {
            "ancient_choice": {"option_index": 0, "relic_model_id": "NEW_LEAF"},
            "nested_kinds": ["card_choice"],
            "node": {"col": 1, "row": 1, "point_type": "Monster"},
            "state_hash": "D2193DDC0B599467E3906395BD51673E03C61F8FB9D9F6DEF17092C3A47C90E1",
        },
        {
            "ancient_choice": {"option_index": 1, "relic_model_id": "NEOWS_TORMENT"},
            "nested_kinds": [],
            "node": {"col": 1, "row": 1, "point_type": "Monster"},
            "state_hash": "539C0AFC8B87CE0B593C67023C8A0F4D033B357C531639342EBFB10E36DC28E2",
        },
        {
            "ancient_choice": {"option_index": 2, "relic_model_id": "NEOWS_BONES"},
            "nested_kinds": ["custom_reward_choice", "card_choice", "custom_reward_choice"],
            "node": {"col": 1, "row": 1, "point_type": "Monster"},
            "state_hash": "3198B7540CDE7FD461694231F3A0490E3C0BAD3EA0C1F90223A8B7300940D5FC",
        },
    ],
    "DEFECT@A0/TRACERBULLET": [
        {
            "ancient_choice": {"option_index": 0, "relic_model_id": "PRECISE_SCISSORS"},
            "nested_kinds": ["card_choice"],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "DAAB57C1BEE778896E9598164EF7FAB3A1BE7BF992527E66BA956FBE4BDDA69E",
        },
        {
            "ancient_choice": {"option_index": 1, "relic_model_id": "BOOMING_CONCH"},
            "nested_kinds": [],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "370BD043FB3BE1CA3F989CBFE2A31175D05C887C5F6CAE8E14044B12C29D0FF0",
        },
        {
            "ancient_choice": {"option_index": 2, "relic_model_id": "SILKEN_TRESS"},
            "nested_kinds": [],
            "node": {"col": 0, "row": 1, "point_type": "Monster"},
            "state_hash": "71A681A9F718461170F90B4EC7E938B3910463155FA381A749FFFE5A1CB33958",
        },
    ],
    "DEFECT@A0/ANCIENT06": [
        {
            "ancient_choice": {"option_index": 0, "relic_model_id": "LOST_COFFER"},
            "nested_kinds": ["custom_reward_choice", "custom_reward_choice"],
            "node": {"col": 2, "row": 1, "point_type": "Monster"},
            "state_hash": "923DDDF8E11C99D3CED8B2CCA159A3950ECA52A9EDEBBB08DCECE251378F5416",
        },
        {
            "ancient_choice": {"option_index": 1, "relic_model_id": "NEOWS_TALISMAN"},
            "nested_kinds": [],
            "node": {"col": 2, "row": 1, "point_type": "Monster"},
            "state_hash": "50D432CF8CB4CE50291AE8D0D26962C0BF7612BA4ECA1DA1FA479356E6C7E263",
        },
        {
            "ancient_choice": {"option_index": 2, "relic_model_id": "LEAFY_POULTICE"},
            "nested_kinds": [],
            "node": {"col": 2, "row": 1, "point_type": "Monster"},
            "state_hash": "09A0BB5AC6E1780BE003A97FA1A44C01F039D30B5040B35D93A913DC790B5F47",
        },
    ],
}


def _run_state(sample: Sample, seed: str) -> dict[str, Any]:
    """The run-start request for one sample: the fully unlocked shipped starting loadout."""
    return {
        "game_build": {},
        "seed": seed,
        "rng_counters": {},
        "character": sample.character,
        "ascension": sample.ascension,
        "encounter": "first",
        "current_hp": 80,
        "max_hp": 80,
        "deck": [],
        "gold": 99,
        "use_character_starting_loadout": True,
    }


def _rows(worker: Any, sample: Sample) -> list[dict[str, Any]]:
    """Every row one acceptance sample records: one per Ancient choice its run offers.

    The sample declares one character, one Ascension and one seed. The Ancient choices are the
    fourth dimension of the request and the run supplies them, so this one call is the sample's
    whole batch.
    """
    request = ScenarioRequest(
        characters=(sample.character,), ascensions=(sample.ascension,), seeds=(sample.seed,)
    )
    return generate_rows(request, worker)


def _replay(worker: Any, sample: Sample, row: dict[str, Any]) -> str:
    """Drive a fresh run from the record's own fields and return the fight's state hash.

    Nothing here comes from the generator: the seed, the Ancient choice index, each nested
    choice's index and the node coordinate are the only inputs, which is exactly the claim
    that the row is a recipe rather than a snapshot of one worker's history.
    """
    recipe = row["recipe"]
    state = worker.run_reset(_run_state(sample, recipe["seed"]))

    ancient = ancient_action(state)
    if ancient is None:
        raise AssertionError(f"{sample.label}: the replay's run does not start on the Ancient")
    entered = worker.run_step(ancient["action_id"])

    option_index = recipe["ancient_choice"]["option_index"]
    offered = choice_actions(entered)
    choice = next((action for action in offered if action["parameters"]["option_index"] == option_index), None)
    if choice is None:
        raise AssertionError(f"{sample.label}: the Ancient no longer offers choice {option_index}")
    if choice["parameters"]["relic_model_id"] != recipe["ancient_choice"]["relic_model_id"]:
        raise AssertionError(
            f"{sample.label}: choice {option_index} grants {choice['parameters']['relic_model_id']}, "
            f"the record says {recipe['ancient_choice']['relic_model_id']}"
        )
    state = worker.run_step(choice["action_id"])

    for nested in recipe["nested_choices"]:
        kind = state["observation"]["decision"]["kind"]
        if kind != nested["kind"]:
            raise AssertionError(f"{sample.label}: expected a {nested['kind']} prompt, the run is at {kind!r}")
        state = worker.run_step(state["legal_actions"][nested["selected_index"]]["action_id"])
    if state["observation"]["decision"]["kind"] != _EVENT_COMPLETE:
        raise AssertionError(
            f"{sample.label}: the recorded nested choices left the run in "
            f"{state['observation']['decision']['kind']!r}"
        )

    state = worker.run_step("leave_event")
    if state["observation"]["decision"]["kind"] != MAP_CHOICE:
        raise AssertionError(f"{sample.label}: leaving the Ancient did not return the run to its map")
    node = recipe["node"]
    action = next(
        (
            candidate for candidate in state["legal_actions"]
            if (candidate["parameters"]["col"], candidate["parameters"]["row"]) == (node["col"], node["row"])
        ),
        None,
    )
    if action is None:
        raise AssertionError(f"{sample.label}: the map no longer offers the recorded node {node}")
    if action["parameters"]["point_type"] != node["point_type"]:
        raise AssertionError(
            f"{sample.label}: the recorded node is a {node['point_type']}, the run reports "
            f"{action['parameters']['point_type']}"
        )
    return worker.run_step(action["action_id"])["state_hash"]


def _facts(row: dict[str, Any]) -> dict[str, Any]:
    recipe = row["recipe"]
    return {
        "canonical_seed": recipe["seed"],
        "raw_seed": recipe.get("raw_seed"),
        "act_variant": recipe["act_variant"],
        "offered": [option["relic_model_id"] for option in recipe["ancient_options"]],
        "chosen": recipe["ancient_choice"],
        "nested_kinds": [nested["kind"] for nested in recipe["nested_choices"]],
        "node": recipe["node"],
        "encounter": recipe["encounter"],
        "state_hash": row["state_hash"],
    }


def _choice_facts(row: dict[str, Any]) -> dict[str, Any]:
    """What one element of a sample's batch recorded: the choice, and what taking it produced."""
    recipe = row["recipe"]
    return {
        "ancient_choice": recipe["ancient_choice"],
        "nested_kinds": [nested["kind"] for nested in recipe["nested_choices"]],
        "node": recipe["node"],
        "state_hash": row["state_hash"],
    }


def _assert_record(
    worker: Any, sample: Sample, row: dict[str, Any], offered_index: int, build: dict[str, Any]
) -> None:
    """Every claim one row makes about the run that produced it."""
    recipe, state = row["recipe"], row["combat_initial_state"]
    canonical = canonicalize_seed(sample.seed)

    def check(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(f"{sample.label}: {message}")

    check(row["schema"].endswith("/1"), f"the row schema tag is {row['schema']!r}")
    check(row["record_type"] == SCENARIO_RECORD, f"the row type is {row['record_type']!r}")
    check(row["game_build"] == build, "the row does not name the build the run was played on")
    check("state_handle" not in json.dumps(row), "the row carries a simulator state handle")

    # The recipe: the seed, the identity of the choices, and the node.
    check(recipe["seed"] == canonical, f"the recorded seed {recipe['seed']!r} is not canonical ({canonical!r})")
    if sample.seed == canonical:
        check("raw_seed" not in recipe, "a canonical request still recorded a raw-seed diagnostic")
    else:
        check(recipe.get("raw_seed") == sample.seed, f"the raw seed {sample.seed!r} is not kept")
    check(state["run"]["seed"] == canonical, "the run was not started with the canonical seed")
    check(recipe["character"] == sample.character, f"the character is {recipe['character']!r}")
    check(recipe["ascension"] == sample.ascension, f"the Ascension is {recipe['ascension']!r}")
    expected_variant = rolled_act_variant(canonical)
    check(recipe["act_variant"] == expected_variant,
          f"the Act variant is {recipe['act_variant']}, the shipped roll says {expected_variant}")

    expected_offer = neow_offer(canonical)
    offered = [option["relic_model_id"] for option in recipe["ancient_options"]]
    check(offered == expected_offer, f"the record offers {offered}, the ported offer is {expected_offer}")
    check([option["option_index"] for option in recipe["ancient_options"]] == list(range(len(offered))),
          "the offered options do not report their offer order")
    check(recipe["ancient_choice"] == recipe["ancient_options"][offered_index],
          f"the choice taken is {recipe['ancient_choice']}, not the option at index {offered_index}")
    for nested in recipe["nested_choices"]:
        check(nested["selected_index"] == 0,
              f"a {nested['kind']} was resolved by index {nested['selected_index']}, not the first legal action")

    node = recipe["node"]
    check(node["row"] == 1 and node["point_type"] == _ROW_ONE_POINT_TYPE, f"the node is {node}")
    check(recipe["encounter"] == state["combat"]["encounter"], "the recipe and the capture disagree about the encounter")
    check(bool(recipe["encounter"]), "the record names no encounter")

    # The combat initial state, as the parity contract defines it.
    validate_observation(state)
    combat, run, inventory = state["combat"], state["run"], state["inventory"]
    check(run["total_floor"] == _FIRST_FIGHT_FLOOR and run["act_floor"] == _FIRST_FIGHT_FLOOR,
          f"the first fight is at floor {run['total_floor']}/{run['act_floor']}, not {_FIRST_FIGHT_FLOOR}")
    check(run["act_index"] == 0, f"the act index is {run['act_index']}, not 0")
    check(run["rng_counters"], "the record carries no named RNG counters")
    check(isinstance(run["gold"], int), "the record's gold is not an integer")
    enemies = [creature for creature in combat["creatures"] if creature["side"] == "Enemy"]
    check(bool(enemies) and all(creature["hp"] > 0 for creature in enemies),
          f"the enemies are {[(creature['model_id'], creature['hp']) for creature in enemies]}")
    players = [creature for creature in combat["creatures"] if creature["side"] == "Player"]
    check(len(players) == 1 and players[0]["hp"] > 0 and players[0]["model_id"] == sample.character,
          f"the player's row is {players}")
    names = [pile["name"] for pile in combat["piles"]]
    check("Hand" in names and "DrawPile" in names, f"the ordered piles are {names}")
    check(all(card["instance_id"] for pile in combat["piles"] for card in pile["cards"]),
          "a recorded card has no instance id")
    check(bool(inventory["relics"]), "the record carries no relics")
    check(len(inventory["potions"]) >= 3, f"the record carries {len(inventory['potions'])} potion slots")

    # The recipe reproduces the situation: the same run, driven from the row's own fields, is
    # the same fight.
    replayed = _replay(worker, sample, row)
    check(replayed == row["state_hash"], f"the replay reached {replayed}, the record says {row['state_hash']}")


def _assert_enumeration(sample: Sample, rows: list[dict[str, Any]]) -> None:
    """Every Ancient choice the run offers has a row, and no row invents a choice.

    The rows' choices, in order, have to be exactly the offer the run reports: choice *k*'s row
    takes offered option *k*. Every row of one sample shares the run's identity — character,
    Ascension, seed, Act variant, the offer and the node — so the choice is the dimension the rows
    differ by; what a choice resolved is that row's own record, not a second dimension.
    """
    offered = rows[0]["recipe"]["ancient_options"]
    choices = [row["recipe"]["ancient_choice"] for row in rows]
    if len(rows) != len(offered):
        raise AssertionError(f"{sample.label}: the run offers {len(offered)} choices, the batch recorded {len(rows)} rows")
    if choices != offered:
        raise AssertionError(f"{sample.label}: the rows took {choices}, the run offers {offered}")
    for key in ("character", "ascension", "seed", "act_variant", "ancient_options", "node"):
        values = {json.dumps(row["recipe"][key], sort_keys=True) for row in rows}
        if len(values) != 1:
            raise AssertionError(f"{sample.label}: the rows of one run disagree about {key}: {sorted(values)}")


def _assert_observed_choices(records: dict[str, list[dict[str, Any]]]) -> None:
    """The recorded batch is a statement about one build; fail closed when it disagrees.

    One entry per Ancient choice the run offered, in offer order — so this pins the enumeration
    the generator promises (every offered choice, and nothing but offered choices) together with
    what taking each choice produced, including the nested-prompt kinds each row resolved. A
    nested kind that stops being covered is a failure rather than a silent narrowing.
    """
    if not _OBSERVED_CHOICES:
        raise AssertionError("the recorded choice table is empty; record it with --snapshot")
    for sample in _SAMPLE:
        facts = [_choice_facts(row) for row in records[sample.label]]
        recorded = _OBSERVED_CHOICES.get(sample.label)
        if recorded is None:
            raise AssertionError(f"{sample.label}: the recorded choice table has no entry for this sample")
        if facts != recorded:
            raise AssertionError(f"{sample.label}: the batch's choices moved\nrecorded: {recorded}\nnow: {facts}")


def _assert_observed(records: dict[str, list[dict[str, Any]]]) -> None:
    """The recorded table is a statement about one build; fail closed when it disagrees.

    Each entry pins the row for the sample's first offered choice; the rest of the batch has no
    recorded counterpart of its own, and :func:`_assert_enumeration` and :func:`_assert_record`
    hold those to the run itself.
    """
    if not _OBSERVED:
        raise AssertionError("the observed table is empty; record it with --snapshot before trusting this run")
    for sample in _SAMPLE:
        facts, recorded = _facts(records[sample.label][0]), _OBSERVED.get(sample.label)
        if recorded is None:
            raise AssertionError(f"{sample.label}: the observed table has no entry for this sample")
        for key, value in recorded.items():
            if facts[key] != value:
                raise AssertionError(f"{sample.label}: {key} moved ({value} -> {facts[key]})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3, help="native workers to spread the sample over")
    parser.add_argument("--snapshot", action="store_true", help="print the per-sample facts instead of asserting")
    arguments = parser.parse_args()

    with NativeWorkerPool(arguments.workers) as pool:
        records = {
            sample.label: _rows(pool.workers[index % arguments.workers], sample)
            for index, sample in enumerate(_SAMPLE)
        }
        if arguments.snapshot:
            print(json.dumps(
                {
                    sample.label: {
                        "first_choice": _facts(records[sample.label][0]),
                        "choices": [_choice_facts(row) for row in records[sample.label]],
                    }
                    for sample in _SAMPLE
                },
                indent=2, sort_keys=True,
            ))
            return

        build = pool.workers[0].build
        if build["assembly_sha256"] != _OBSERVED_BUILD:
            raise AssertionError(
                f"the observed table is for game assembly {_OBSERVED_BUILD}, this host runs "
                f"{build['assembly_sha256']}; re-record it with --snapshot"
            )
        _assert_observed(records)
        _assert_observed_choices(records)
        for index, sample in enumerate(_SAMPLE):
            rows = records[sample.label]
            _assert_enumeration(sample, rows)
            for offered_index, row in enumerate(rows):
                _assert_record(pool.workers[index % arguments.workers], sample, row, offered_index, build)

        # Determinism: the same request on another worker produces the same rows.
        first, second = _SAMPLE[0], _SAMPLE[1]
        repeated = _rows(pool.workers[(len(_SAMPLE) + 1) % arguments.workers], second)
        if repeated != records[second.label]:
            raise AssertionError(f"{second.label}: a second worker produced different rows")
        again = _rows(pool.workers[(len(_SAMPLE) + 2) % arguments.workers], first)
        if again != records[first.label]:
            raise AssertionError(f"{first.label}: the same request run twice produced different rows")

        print(json.dumps({
            "success": True,
            "game_build": build,
            "samples": [_facts(records[sample.label][0]) for sample in _SAMPLE],
            "rows_per_sample": {sample.label: len(records[sample.label]) for sample in _SAMPLE},
            "nested_kinds_covered": sorted({
                nested["kind"]
                for rows in records.values()
                for row in rows
                for nested in row["recipe"]["nested_choices"]
            }),
            "repeated": [first.label, second.label],
        }, indent=2))


if __name__ == "__main__":
    main()
