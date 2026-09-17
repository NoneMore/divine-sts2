#!/usr/bin/env python3
"""Shipped-game acceptance for the full-app bridge's combat observation.

Parity is compared through the full-app bridge, so the bridge's own combat block is on the critical
path: whatever it does not report is a field the oracle cannot compare and an audit cannot read.
This script drives one real ``SlayTheSpire2.exe`` headless through the act-1 Ancient room to the
row-1 fight, and checks the combat block field by field against the shape the simulator and the
trace exporter already report — the encounter, the granular turn phase, energy and max energy and
stars inside the combat block, every creature with its side, its complete ordered intent list and
its powers, the player's own creature row, and the fight's five ordered piles of cards with each
card's identity, model, type, target, cost, cost-x flag, upgrades, enchantment and native state.

Everything a fight does not carry is checked beside it, because the parity contract is wider than
the fight: the build the observation was taken on; the run's own seed, Ascension, gold, zero-based
act index, Act variant, act floor, total floor and named RNG counters; the coordinate the run
stands on, which is the row-0 Ancient from the first observation on and the row-1 node at the fight;
and the inventory — relics in order as objects with their counter and native state, and potions by
slot with the empty slots kept, so a slot index survives.

The turn phase is checked through ``sts2_native_sim.decision_vocabulary``, which is the one place
that says which simulator decision kind a bridge phase word stands for, so a phase word the
mapping does not know fails here rather than in the field-by-field parity run.

Three things this run cannot observe by itself, and it says so rather than implying otherwise.
Whether the bridge's hand cost agrees with the repository's other projections of the same card:
there is no second projection of a hand card on the bridge, so that agreement is the field-by-field
parity run's to check, and the accessor is pinned offline in
``tests/test_bridge_observation_shape.py``. Whether an upgrade count is real: a starting deck is
unupgraded, so the field is observed present and typed here and its accessor is pinned offline. And
the relic counter's *present* case: neither relic this drive holds shows one, so what is observed
here is the absent case and the shape of the member, while the accessor that reads the two members
a counter comes from is pinned offline against the trace exporter's and the simulator's own
inventories.

Requires the shipped game (the repository's ``*_acceptance.py`` convention). The sandbox is
hard-linked beside the install, so it has to sit on the install's volume.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).parent))

from sts2_native_sim import decision_vocabulary
from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig

SEED = "A1B2C3D4E5"
CHARACTER = "IRONCLAD"
ASCENSION = 0

#: The fields a fight has to name for the parity contract to be comparable at all.
REQUIRED_COMBAT_KEYS = ("encounter", "turn", "phase", "energy", "max_energy", "stars", "creatures", "piles")
#: Every creature row reports these. `next_move` is not among them: a creature with no move (the
#: player) has none, and every projection drops the member rather than writing null.
REQUIRED_CREATURE_KEYS = ("combat_id", "model_id", "side", "hp", "max_hp", "block", "alive", "powers")

#: The build block, worded as the simulator's worker, the trace exporter and the published schema
#: all word it.
BUILD_KEYS = ("version", "assembly_sha256", "pck_sha256")

#: The run block's members, which are the simulator's own combat-run projection. The act index is
#: zero-based, the Act variant names the model in play, and the two floors are the act's and the
#: run's.
RUN_KEYS = (
    "seed",
    "ascension",
    "gold",
    "act_variant",
    "act_index",
    "act_floor",
    "total_floor",
    "rng_counters",
)

#: Every named RNG counter a run reports: the shipped `RunRngType` members, in the game's own
#: spelling. The simulator's worker, the trace exporter and the bridge all key their counters by
#: these names, so a counter set a comparison cannot line up is a failure here.
RUN_RNG_COUNTERS = (
    "CombatCardGeneration",
    "CombatCardSelection",
    "CombatEnergyCosts",
    "CombatOrbs",
    "CombatPotionGeneration",
    "CombatTargets",
    "MonsterAi",
    "Niche",
    "Shuffle",
    "TreasureRoomRelics",
    "UnknownMapPoint",
    "UpFront",
)

#: The Act variants act 1 can be, named as the shipped game names them.
ACT_VARIANTS = ("OVERGROWTH", "UNDERDOCKS")

#: Every relic row reports a model id and its own saved state, and a counter only when the relic
#: shows one.
RELIC_KEYS = ("model_id", "native_state")
OPTIONAL_RELIC_KEYS = ("counter",)
#: Every occupied potion slot reports its slot, its model and its own (always empty) saved state.
POTION_KEYS = ("slot", "model_id", "native_state")


#: The five piles, in the order every projection reports them: each pile's name, and the game's own
#: word for its type. The bridge states this order, the offline shape test states it independently
#: and so does this script, so a projection that stops agreeing fails rather than being normalised.
PILE_ORDER = (
    ("Hand", "Hand"),
    ("DrawPile", "Draw"),
    ("DiscardPile", "Discard"),
    ("ExhaustPile", "Exhaust"),
    ("PlayPile", "Play"),
)

#: Every card member and the type it is reported as. `enchantment` is not among them: a card carries
#: one only when it is enchanted, and every projection drops the null member rather than writing null.
CARD_FIELD_TYPES: dict[str, type] = {
    "instance_id": str,
    "net_id": int,
    "model_id": str,
    "card_type": str,
    "target_type": str,
    "energy_cost": int,
    "costs_x": bool,
    "upgrades": int,
    "native_state": dict,
}

#: What the bridge hands the driver on the way to the fight, so a stall names where it stalled.
MAX_STEPS = 40

#: The opening state of a weak fight carries no powers, so the fight is played on until one is
#: granted — which is the only way the power row is observed rather than merely declared.
MAX_FIGHT_TURNS = 4


def _check(condition: bool, record: dict[str, Any], message: str) -> None:
    if not condition:
        raise AssertionError(f"{message}\nobserved: {json.dumps(record, indent=2, sort_keys=True)}")


def _pile(observation: dict[str, Any], name: str) -> dict[str, Any]:
    for pile in observation["combat"]["piles"]:
        if pile["name"] == name:
            return pile
    reported = [pile["name"] for pile in observation["combat"]["piles"]]
    raise AssertionError(f"the fight reports no {name} pile: {reported}")


def _cards(observation: dict[str, Any]) -> list[dict[str, Any]]:
    return [card for pile in observation["combat"]["piles"] for card in pile["cards"]]


def _cards_by_identity(observation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {card["instance_id"]: card for card in _cards(observation)}


def _draw_pile_order(observation: dict[str, Any]) -> list[tuple[str, str]]:
    """The draw pile as what a policy learns from: its order, in the bridge's own identities."""
    return [(card["instance_id"], card["model_id"]) for card in _pile(observation, "DrawPile")["cards"]]


def _identity_drift(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[str]:
    """Identities a rebuilt observation gives to a card whose attributes disagree with the earlier read.

    Only the attributes that cannot legitimately differ between two reads of one card are compared:
    a cost modifier can be granted and expire within a fight, and `native_state` is a card's evolving
    state (a Genetic Algorithm's stored block, say), so neither is an identity.
    """
    stable = ("model_id", "card_type", "target_type", "costs_x", "upgrades")
    return [
        f"{instance_id}: {tuple(earlier[key] for key in stable)} -> {tuple(card[key] for key in stable)}"
        for instance_id, card in after.items()
        if (earlier := before.get(instance_id)) is not None
        and tuple(earlier[key] for key in stable) != tuple(card[key] for key in stable)
    ]


def _block(observation: dict[str, Any], member: str, record: dict[str, Any]) -> dict[str, Any]:
    """One object-valued member of an observation, or a failure that names what was reported."""
    value = observation.get(member)
    _check(isinstance(value, dict), record, f"the observation reports no {member} block: {value!r}")
    return cast(dict[str, Any], value)


def _check_build(observation: dict[str, Any], hello: dict[str, Any], record: dict[str, Any]) -> None:
    """The build the observation was taken on, which is what attributes a mismatch to a build.

    The worker reports the same block to a client that only says hello, and both come from one
    measurement of one process, so the two have to agree — a build that moved between them would mean
    the observation is of a different install than the worker claims.
    """
    build = _block(observation, "game_build", record)
    _check(set(build) == set(BUILD_KEYS), record, f"the build reports {sorted(build)}, not {sorted(BUILD_KEYS)}")
    for key in BUILD_KEYS:
        _check(isinstance(build[key], str) and bool(build[key]), record, f"the build reports {key}={build[key]!r}")
    _check(hello.get("game_build") == build, record,
           f"the worker's hello build {hello.get('game_build')!r} is not the observation's {build!r}")


def _check_run(observation: dict[str, Any], record: dict[str, Any], *, act_floor: int, total_floor: int) -> None:
    """The run block, checked against the shape and the values this drive can know.

    The two floors are the ones this stage has travelled to: one map point at the Ancient, two at the
    row-1 node, which is the counter the per-encounter generator is seeded with.
    """
    run = _block(observation, "run", record)
    _check(set(run) == set(RUN_KEYS), record, f"the run block reports {sorted(run)}, not {sorted(RUN_KEYS)}")

    _check(run["seed"] == SEED, record, f"the run reports seed {run['seed']!r}, not the requested {SEED!r}")
    _check(run["ascension"] == ASCENSION, record, f"the run reports Ascension {run['ascension']!r}")
    _check(isinstance(run["gold"], int) and run["gold"] >= 0, record, f"the run reports gold {run['gold']!r}")
    _check(run["act_variant"] in ACT_VARIANTS, record, f"the run reports Act variant {run['act_variant']!r}")
    # The act index is the run's own zero-based one, not the one-based number this seam used to
    # report; the drive stays in act 1 throughout.
    _check(run["act_index"] == 0, record, f"the act index is {run['act_index']}, not the run's own zero-based 0")
    _check(run["act_floor"] == act_floor, record,
           f"the act floor is {run['act_floor']}, not the {act_floor} map points travelled in this act")
    _check(run["total_floor"] == total_floor, record,
           f"the run's total floor is {run['total_floor']}, not the {total_floor} map points it travelled")

    counters = run["rng_counters"]
    _check(isinstance(counters, dict), record, f"the run reports rng_counters {counters!r}")
    _check(set(counters) == set(RUN_RNG_COUNTERS), record,
           f"the run reports counters {sorted(counters)}, not the run's own {sorted(RUN_RNG_COUNTERS)}")
    for name, value in counters.items():
        _check(isinstance(value, int) and value >= 0, record, f"counter {name} is {value!r}, not a count")


def _check_map_coord(observation: dict[str, Any], expected_row: int, record: dict[str, Any], where: str) -> dict[str, Any]:
    """The coordinate the run stands on: the row-0 Ancient, then the row-1 node it travelled to."""
    coord = _block(observation, "map_coord", record)
    _check(set(coord) == {"col", "row"}, record, f"{where}: the coordinate reports {sorted(coord)}")
    _check(coord["row"] == expected_row, record, f"{where}: the run stands on row {coord['row']}, not {expected_row}")
    _check(isinstance(coord["col"], int) and coord["col"] >= 0, record, f"{where}: the column is {coord['col']!r}")
    return dict(coord)


def _check_inventory(observation: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """The relics as ordered objects and the potions by slot, empty slots included."""
    inventory = _block(observation, "inventory", record)
    _check(set(inventory) == {"relics", "potions"}, record, f"the inventory reports {sorted(inventory)}")

    relics = inventory["relics"]
    _check(isinstance(relics, list), record, f"the inventory reports relics as {relics!r}")
    # A fully unlocked Ironclad holds its starting relic, and the first Ancient choice grants one.
    _check(len(relics) >= 2, record, f"the run holds {len(relics)} relics after the Ancient and the row-1 node")
    for index, relic in enumerate(relics):
        _check(isinstance(relic, dict), record, f"relic {index} is {relic!r}, not an object")
        reported = set(relic)
        _check(set(RELIC_KEYS) <= reported <= set(RELIC_KEYS) | set(OPTIONAL_RELIC_KEYS), record,
               f"relic {index} reports the members {sorted(reported)}")
        _check(isinstance(relic["model_id"], str) and bool(relic["model_id"]), record,
               f"relic {index} reports model id {relic['model_id']!r}")
        _check(isinstance(relic["native_state"], dict), record,
               f"relic {index} reports native state {relic['native_state']!r}")
        if "counter" in relic:
            _check(isinstance(relic["counter"], int), record, f"relic {index} reports counter {relic['counter']!r}")

    potions = inventory["potions"]
    _check(isinstance(potions, list), record, f"the inventory reports potions as {potions!r}")
    # One entry per slot, and an Ascension-0 Ironclad's belt has three of them.
    _check(len(potions) >= 3, record, f"the belt reports {len(potions)} slots, not at least the three it starts with")
    for slot, potion in enumerate(potions):
        if potion is None:
            continue
        _check(isinstance(potion, dict), record, f"potion slot {slot} is {potion!r}, not an object or null")
        _check(set(potion) == set(POTION_KEYS), record, f"potion slot {slot} reports the members {sorted(potion)}")
        # The slot index is part of the state: a list that skipped an empty slot would report a
        # potion under a slot it is not in.
        _check(potion["slot"] == slot, record, f"the potion at position {slot} reports slot {potion['slot']!r}")
        _check(isinstance(potion["model_id"], str) and bool(potion["model_id"]), record,
               f"potion slot {slot} reports model id {potion['model_id']!r}")
        _check(isinstance(potion["native_state"], dict), record,
               f"potion slot {slot} reports native state {potion['native_state']!r}")

    return {
        "relics": [relic["model_id"] for relic in relics],
        "potion_slots": [None if potion is None else potion["model_id"] for potion in potions],
    }


def _drive_to_first_fight(client: FullAppBridgeClient, observation: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Take the first legal action the bridge reports until a combat observation appears.

    Every observation on the way names the stage the bridge is standing in, and that word has to be
    one the decision vocabulary maps onto the simulator's decision kinds — so a bridge that grows a
    stage nobody mapped fails here rather than quietly in a comparison.
    """
    phases: list[str] = []
    for _ in range(MAX_STEPS):
        if observation.get("combat"):
            return observation, phases
        stage = str(observation.get("phase"))
        try:
            decision_vocabulary.decision_kinds_for_bridge_phase(stage)
        except ValueError as error:
            raise AssertionError(f"the bridge reports stage {stage!r}, which the vocabulary does not map: {error}") from error
        phases.append(stage)
        actions = client.legal_actions()
        if not actions:
            raise AssertionError(
                f"the run stalled in phase {observation.get('phase')!r} with no legal action, so no fight was reached: "
                f"phases seen {phases}"
            )
        observation = client.step(actions[0]["action_id"]).get("observation", {})
    raise AssertionError(f"no fight within {MAX_STEPS} decisions; phases seen {phases}")


def _check_combat_block(observation: dict[str, Any], *, complete_piles: bool = False) -> dict[str, Any]:
    combat = observation["combat"]
    record = {"combat": combat, "phases_seen_on_the_way": None}

    missing = [key for key in REQUIRED_COMBAT_KEYS if key not in combat]
    _check(not missing, record, f"the combat block does not report {missing}")
    _check("enemies" not in combat, record, "the combat block still carries its own enemy rows")
    _check("hand" not in combat, record, "the combat block still carries the older hand list")
    counted = [key for key in combat if key.endswith("_pile_count")]
    _check(not counted, record, f"the combat block still counts piles instead of reporting them: {counted}")

    encounter = combat["encounter"]
    _check(isinstance(encounter, str) and bool(encounter), record, f"the fight does not name its encounter: {encounter!r}")

    # The granular turn phase, and the one mapping that says what it means.
    phase = combat["phase"]
    decision_kinds = decision_vocabulary.decision_kinds_for_combat_phase(phase)
    _check(
        "combat_action" in decision_kinds,
        record,
        f"the bridge offered actions in turn phase {phase!r}, which the vocabulary maps onto {sorted(decision_kinds)}",
    )

    energy, max_energy, stars = combat["energy"], combat["max_energy"], combat["stars"]
    for name, value in (("energy", energy), ("max_energy", max_energy), ("stars", stars)):
        _check(isinstance(value, int), record, f"combat.{name} is {value!r}, not an integer")
    _check(max_energy >= 1, record, f"combat.max_energy is {max_energy}")
    _check(0 <= energy <= max_energy, record, f"combat.energy is {energy} of max {max_energy}")
    _check(energy == observation["player_energy"], record,
           f"combat.energy ({energy}) reads a different accessor than the observation ({observation['player_energy']})")

    creatures = combat["creatures"]
    _check(bool(creatures), record, "the combat block reports no creature at all")

    for index, creature in enumerate(creatures):
        missing = [key for key in REQUIRED_CREATURE_KEYS if key not in creature]
        _check(not missing, record, f"creature {index} does not report {missing}")
        _check(creature["side"] in ("Player", "Enemy"), record, f"creature {index} reports side {creature['side']!r}")
        _check(isinstance(creature["hp"], int) and isinstance(creature["max_hp"], int), record,
               f"creature {index} reports hp {creature['hp']!r} of {creature['max_hp']!r}")
        _check(0 <= creature["hp"] <= creature["max_hp"], record,
               f"creature {index} reports hp {creature['hp']} of {creature['max_hp']}")
        _check(isinstance(creature["alive"], bool), record, f"creature {index} reports alive {creature['alive']!r}")
        _check(isinstance(creature["powers"], list), record, f"creature {index} reports powers {creature['powers']!r}")

        for power in creature["powers"]:
            _check(set(power) == {"model_id", "amount"}, record, f"creature {index} reports a power as {power!r}")
            _check(isinstance(power["amount"], int), record, f"creature {index} reports power amount {power['amount']!r}")

        move = creature.get("next_move")
        if move is None:
            continue
        _check(isinstance(move.get("id"), str) and move["id"], record, f"creature {index} reports a move without an id")
        _check(isinstance(move.get("intents"), list), record, f"creature {index} reports intents {move.get('intents')!r}")
        for intent in move["intents"]:
            _check({"intent_type", "implementation"} <= set(intent), record,
                   f"creature {index} reports an intent as {intent!r}")
            if intent["intent_type"] == "Attack":
                _check(isinstance(intent.get("damage"), int) and intent["damage"] >= 0, record,
                       f"creature {index} reports an attack intent without damage: {intent!r}")
                _check(isinstance(intent.get("repeats"), int) and intent["repeats"] >= 1, record,
                       f"creature {index} reports an attack intent without a repeat count: {intent!r}")
            else:
                # An intent that is not an attack has no damage and no repeats, and every other
                # projection drops those members rather than writing null; the bridge must too.
                _check("damage" not in intent and "repeats" not in intent, record,
                       f"creature {index} reports a non-attack intent with attack fields: {intent!r}")

    players = [creature for creature in creatures if creature["side"] == "Player"]
    _check(len(players) == 1, record, f"the fight reports {len(players)} player creature rows")
    player_row = players[0]
    _check(player_row["model_id"] == observation["character"], record,
           f"the player row reports {player_row['model_id']!r}, not {observation['character']!r}")
    for name in ("hp", "max_hp", "block"):
        _check(player_row[name] == observation[f"player_{name}"], record,
               f"the player row's {name} ({player_row[name]}) disagrees with the observation's ({observation[f'player_{name}']})")
    _check({power["model_id"]: power["amount"] for power in player_row["powers"]} == observation["player_powers"], record,
           "the player row's powers disagree with the observation's flat player_powers")

    enemies = [creature for creature in creatures if creature["side"] == "Enemy"]
    _check(bool(enemies), record, "the fight reports no enemy creature row")
    _check(any(enemy.get("next_move") and enemy["next_move"]["intents"] for enemy in enemies), record,
           "no enemy reports an ordered intent list")

    # The five ordered piles, which is where a draw pile's order — what a policy learns from — and
    # every card's identity live.
    piles = combat["piles"]
    _check([(pile["name"], pile["type"]) for pile in piles] == list(PILE_ORDER), record,
           f"the fight does not report its five piles in order: {[(pile['name'], pile['type']) for pile in piles]}")
    cards = _cards(observation)
    identities = [card["instance_id"] for card in cards]
    _check(len(set(identities)) == len(identities), record, "two cards of the fight share one bridge instance id")
    _check(all(isinstance(identity, str) and identity for identity in identities), record,
           f"a card carries no instance id: {identities}")
    if complete_piles:
        # On the turn a fight opens, the five piles are the deck: every card of it is in one of them.
        _check(len(cards) == len(observation["deck_cards"]), record,
               f"the five piles hold {len(cards)} cards, not the deck's {len(observation['deck_cards'])}")
    for index, card in enumerate(cards):
        missing = [key for key in CARD_FIELD_TYPES if key not in card]
        _check(not missing, record, f"card {index} does not report {missing}")
        for key, reported_as in CARD_FIELD_TYPES.items():
            _check(type(card[key]) is reported_as, record,
                   f"card {index} reports {key} as {card[key]!r}, not {reported_as.__name__}")
        _check(card["net_id"] >= 0 and card["energy_cost"] >= 0 and card["upgrades"] >= 0, record,
               f"card {index} reports a negative quantity: {card}")
        identity = (card["instance_id"], card["model_id"], card["card_type"])
        _check(all(identity), record, f"card {index} reports an empty identity: {identity!r}")
        if "enchantment" in card:
            _check(set(card["enchantment"]) == {"model_id", "amount"}, record,
                   f"card {index} reports its enchantment as {card['enchantment']!r}")
    _check(any(card["energy_cost"] > 0 for card in cards), record,
           "no card of the fight costs energy, so the cost field is not being read from the card")

    record["phases_seen_on_the_way"] = None
    record["piles"] = {pile["name"]: len(pile["cards"]) for pile in piles}
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", type=int, default=7, help="sandbox index to run in")
    arguments = parser.parse_args(argv)

    client = FullAppBridgeClient(FullAppClientConfig(worker_id=arguments.worker_id))
    try:
        print(f"Launching a headless shipped game in {client.sandbox_dir}...", flush=True)
        client.launch(requested_character=CHARACTER)
        print(f"Worker ready on port {client.bound_port}; starting a run on {SEED}...", flush=True)

        started = client.start_run(seed=SEED, character=CHARACTER, ascension=ASCENSION)
        opening = started["observation"]
        record: dict[str, Any] = {}
        _check_build(opening, client.hello(), record)
        # The run travels to its act's Ancient before the first decision the bridge reports, so the
        # row-0 Ancient coordinate and the first floor of the act are on the very first observation.
        _check_run(opening, record, act_floor=1, total_floor=1)
        ancient_coord = _check_map_coord(opening, 0, record, "at the Ancient")
        record["run_at_the_ancient"] = opening["run"]

        observation, phases = _drive_to_first_fight(client, opening)

        record.update(_check_combat_block(observation, complete_piles=True))
        record["phases_seen_on_the_way"] = phases
        record["state_hash_at_the_first_fight"] = observation["state_hash"]
        record["draw_pile_at_the_first_fight"] = _draw_pile_order(observation)

        # Where the run is and what it carries, at the fight: the build is the same one the worker
        # said hello with, the run block is unchanged by travelling except for the floor the row-1
        # node advanced, the coordinate is that node, and the inventory is the relics and the belt.
        _check_build(observation, client.hello(), record)
        _check_run(observation, record, act_floor=2, total_floor=2)
        fight_coord = _check_map_coord(observation, 1, record, "at the first fight")
        _check(fight_coord != ancient_coord, record,
               f"the fight reports the Ancient's own coordinate {fight_coord!r}, so no node was travelled to")
        record["game_build"] = observation["game_build"]
        record["run_at_the_first_fight"] = observation["run"]
        record["ancient_coord"] = ancient_coord
        record["fight_coord"] = fight_coord
        record["inventory_at_the_first_fight"] = _check_inventory(observation, record)

        # The same state, read twice: a draw pile's order is what a policy learns from, and an
        # identity minted per observation would make two reads of one state look like two states.
        # The run's own counters and its inventory are the same claim for the run block: nothing
        # happened between the two reads, so nothing about them may move.
        again = client.observe()
        _check(again is not None, record, "the bridge reports no observation on a second read")
        _check(_draw_pile_order(again) == _draw_pile_order(observation), record,
               "the draw pile's order changed between two reads of one state")
        _check(_cards_by_identity(again) == _cards_by_identity(observation), record,
               "the bridge's card identities changed between two reads of one state")
        _check(again.get("run") == observation.get("run"), record,
               f"the run block changed between two reads of one state: {observation.get('run')} -> {again.get('run')}")
        again_inventory = _check_inventory(again, record)
        _check(again_inventory == record["inventory_at_the_first_fight"], record,
               "the inventory changed between two reads of one state")

        # A weak fight opens with no powers on either side, so the power row is observed by playing
        # the fight on: the first fight's enemies grant one with a debuff. Every observation on the
        # way is checked, and each one is a rebuilt observation of the same fight, so the identities
        # the bridge minted at the first fight have to still name the same cards.
        opening_hand = len(_pile(observation, "Hand")["cards"])
        previous = _cards_by_identity(observation)
        surviving_identities = 0
        turns_played: list[int] = []
        powers_seen: list[dict[str, Any]] = []
        while not powers_seen and len(turns_played) < MAX_FIGHT_TURNS:
            if not any(action["action_id"] == "end_turn" for action in client.legal_actions()):
                break
            observation = client.step("end_turn").get("observation", {})
            if not observation.get("combat"):
                break
            _check_combat_block(observation)
            current = _cards_by_identity(observation)
            drift = _identity_drift(previous, current)
            _check(not drift, record,
                   f"a rebuilt observation reused an instance id for a different card: {drift}")
            surviving_identities = max(surviving_identities, len(set(previous) & set(current)))
            previous = current
            turns_played.append(observation["combat"]["turn"])
            powers_seen = [
                {"creature": creature["model_id"], "side": creature["side"], **power}
                for creature in observation["combat"]["creatures"]
                for power in creature["powers"]
            ]
        _check(bool(powers_seen), record, f"no creature reported a power within {MAX_FIGHT_TURNS} turns")
        # Ending a turn moves the hand rather than replacing it, so every card that was in the
        # opening hand is still one of the fight's cards, under the identity it was minted with.
        _check(surviving_identities >= opening_hand, record,
               f"only {surviving_identities} of the opening hand's {opening_hand} cards kept their identity "
               "across a rebuilt observation, so the registry does not survive one")

        record["turns_played_before_powers"] = turns_played
        record["powers_seen"] = powers_seen
        record["cards_keeping_their_identity_across_a_rebuild"] = surviving_identities
        record["state_hash_at_powers"] = observation["state_hash"]
        print(json.dumps({"success": True, "seed": SEED, "character": CHARACTER, "ascension": ASCENSION, **record},
                         indent=2, sort_keys=True))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
