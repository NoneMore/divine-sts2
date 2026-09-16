#!/usr/bin/env python3
"""Shipped-game acceptance for the full-app bridge's combat observation.

Parity is compared through the full-app bridge, so the bridge's own combat block is on the critical
path: whatever it does not report is a field the oracle cannot compare and an audit cannot read.
This script drives one real ``SlayTheSpire2.exe`` headless through the act-1 Ancient room to the
row-1 fight, and checks the combat block field by field against the shape the simulator and the
trace exporter already report — the encounter, the granular turn phase, energy and max energy and
stars inside the combat block, every creature with its side, its complete ordered intent list and
its powers, and the player's own creature row.

The turn phase is checked through ``sts2_native_sim.decision_vocabulary``, which is the one place
that says which simulator decision kind a bridge phase word stands for, so a phase word the
mapping does not know fails here rather than in the field-by-field parity run.

Requires the shipped game (the repository's ``*_acceptance.py`` convention). The sandbox is
hard-linked beside the install, so it has to sit on the install's volume.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from sts2_native_sim import decision_vocabulary
from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig

SEED = "A1B2C3D4E5"
CHARACTER = "IRONCLAD"
ASCENSION = 0

#: The fields a fight has to name for the parity contract to be comparable at all.
REQUIRED_COMBAT_KEYS = ("encounter", "turn", "phase", "energy", "max_energy", "stars", "creatures")
#: Every creature row reports these. `next_move` is not among them: a creature with no move (the
#: player) has none, and every projection drops the member rather than writing null.
REQUIRED_CREATURE_KEYS = ("combat_id", "model_id", "side", "hp", "max_hp", "block", "alive", "powers")

#: What the bridge hands the driver on the way to the fight, so a stall names where it stalled.
MAX_STEPS = 40

#: The opening state of a weak fight carries no powers, so the fight is played on until one is
#: granted — which is the only way the power row is observed rather than merely declared.
MAX_FIGHT_TURNS = 4


def _check(condition: bool, record: dict[str, Any], message: str) -> None:
    if not condition:
        raise AssertionError(f"{message}\nobserved: {json.dumps(record, indent=2, sort_keys=True)}")


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


def _check_combat_block(observation: dict[str, Any]) -> dict[str, Any]:
    combat = observation["combat"]
    record = {"combat": combat, "phases_seen_on_the_way": None}

    missing = [key for key in REQUIRED_COMBAT_KEYS if key not in combat]
    _check(not missing, record, f"the combat block does not report {missing}")
    _check("enemies" not in combat, record, "the combat block still carries its own enemy rows")

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

    record["phases_seen_on_the_way"] = None
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
        observation, phases = _drive_to_first_fight(client, started["observation"])

        record = _check_combat_block(observation)
        record["phases_seen_on_the_way"] = phases
        record["state_hash_at_the_first_fight"] = observation["state_hash"]

        # A weak fight opens with no powers on either side, so the power row is observed by playing
        # the fight on: the first fight's enemies grant one with a debuff.
        turns_played: list[int] = []
        powers_seen: list[dict[str, Any]] = []
        while not powers_seen and len(turns_played) < MAX_FIGHT_TURNS:
            if not any(action["action_id"] == "end_turn" for action in client.legal_actions()):
                break
            observation = client.step("end_turn").get("observation", {})
            if not observation.get("combat"):
                break
            _check_combat_block(observation)
            turns_played.append(observation["combat"]["turn"])
            powers_seen = [
                {"creature": creature["model_id"], "side": creature["side"], **power}
                for creature in observation["combat"]["creatures"]
                for power in creature["powers"]
            ]
        _check(bool(powers_seen), record, f"no creature reported a power within {MAX_FIGHT_TURNS} turns")

        record["turns_played_before_powers"] = turns_played
        record["powers_seen"] = powers_seen
        record["state_hash_at_powers"] = observation["state_hash"]
        print(json.dumps({"success": True, "seed": SEED, "character": CHARACTER, "ascension": ASCENSION, **record},
                         indent=2, sort_keys=True))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
