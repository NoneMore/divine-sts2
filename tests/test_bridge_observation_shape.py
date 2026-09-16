"""Offline checks that the bridge's combat block is the repository's combat projection, not a third one.

The full-app bridge compiles against the shipped game and is only exercised end to end by an
acceptance script, so what the repository can check offline is the shape: the bridge's own DTO
declarations, the simulator's per-combat projection they have to agree with, and a capture recorded
from the shipped-game-backed worker that shows the shape a real fight has. These tests compare all
three, which is what stops the bridge drifting into a vocabulary of its own between acceptance runs.

The ordered piles and the per-card fields are the same kind of check taken further: a fight is five
ordered piles of cards, and a card is the shape the simulator's own pile projection gives one, so a
comparison of a draw pile's order and of one card's identity has something to read.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sts2_native_sim import paths

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "canonical-observations.json"
CAPTURES: dict[str, dict[str, object]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

BRIDGE_DIR = paths.REPOSITORY_ROOT / "src" / "Sts2.NativeSim.FullAppBridge"
PROTOCOL_MESSAGES = BRIDGE_DIR / "ProtocolMessages.cs"
ENVIRONMENT = paths.REPOSITORY_ROOT / "src" / "Sts2.NativeSim.Core" / "PersistentNativeCombatEnvironment.cs"

#: The fight the fixture records in a run, which is the shape a bridged fight has to have.
COMBAT_CAPTURE = "run_combat_action"

#: The fields of a fight this ticket converges: the ones the simulator's combat block carries and
#: the bridge's did not. `orbs`, which the simulator carries, is in neither the bridge nor the parity
#: contract, so the bridge is allowed to be a strict subset of the simulator's block.
CONVERGED_COMBAT_KEYS = frozenset({"encounter", "turn", "phase", "energy", "max_energy", "stars", "creatures", "piles"})

#: The five combat piles, in the order every projection reports them: the hand first, then every
#: pile a card can move to, and the play pile — which no bridge projection had before — last.
PILE_ORDER = ("Hand", "DrawPile", "DiscardPile", "ExhaustPile", "PlayPile")

#: The pile's name paired with the game's own word for its type, as the recorded captures report it.
PILE_TYPES = {
    "Hand": "Hand",
    "DrawPile": "Draw",
    "DiscardPile": "Discard",
    "ExhaustPile": "Exhaust",
    "PlayPile": "Play",
}

#: A card's members, minus `enchantment`: a card carries one only when it is enchanted, and every
#: projection drops the null member, so no recorded capture has to show one for the shape to be right.
CARD_KEYS = frozenset(
    {
        "instance_id",
        "net_id",
        "model_id",
        "card_type",
        "target_type",
        "energy_cost",
        "costs_x",
        "upgrades",
        "native_state",
    }
)

#: The bridge's own signatures the tests below read a body through, so a rename fails a test rather
#: than silently reading nothing.
CARD_ROW_SIGNATURE = "private static CardObservationDto CardObservation(PlayerCombatState fight, CardModel card)"
PILE_ROW_SIGNATURE = (
    "private static PileObservationDto PileObservation(PlayerCombatState fight, string name, CardPile pile)"
)


def dto_properties() -> dict[str, list[str]]:
    """Every bridge DTO's JSON member names, in declaration order, read from its own declarations."""
    source = PROTOCOL_MESSAGES.read_text(encoding="utf-8")
    classes = re.findall(r"public sealed class (\w+)\s*\n?\s*\{(.*?)\n\}", source, re.DOTALL)
    return {name: re.findall(r'\[JsonPropertyName\("([^"]+)"\)\]', body) for name, body in classes}


def recorded_combat_shape() -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    """The key sets of every recorded fight: combat block, creature, move, intent and power rows."""
    combat: set[str] = set()
    creature: set[str] = set()
    move: set[str] = set()
    intent: set[str] = set()
    power: set[str] = set()
    for capture in CAPTURES.values():
        block = capture.get("combat")  # type: ignore[union-attr]
        if not isinstance(block, dict):
            continue
        combat |= set(block)
        for row in block["creatures"]:
            creature |= set(row)
            power |= {key for entry in row.get("powers", []) for key in entry}
            if "next_move" in row:
                move |= set(row["next_move"])
                intent |= {key for entry in row["next_move"]["intents"] for key in entry}
    return combat, creature, move, intent, power


def recorded_piles() -> list[dict[str, object]]:
    """Every recorded fight's piles, in recorded order, as the shape a bridged fight has to have."""
    piles: list[dict[str, object]] = []
    for capture in CAPTURES.values():
        block = capture.get("combat")
        if not isinstance(block, dict):
            continue
        rows = block.get("piles")
        if isinstance(rows, list):
            piles.extend(dict(row) for row in rows if isinstance(row, dict))
    return piles


def recorded_pile_orders() -> list[list[tuple[object, object]]]:
    """Every recorded fight's piles as (name, type) pairs, in the order it recorded them."""
    orders: list[list[tuple[object, object]]] = []
    for capture in CAPTURES.values():
        block = capture.get("combat")
        if not isinstance(block, dict):
            continue
        rows = block.get("piles")
        if isinstance(rows, list) and rows:
            orders.append([(row["name"], row["type"]) for row in rows if isinstance(row, dict)])
    return orders


def recorded_cards() -> list[dict[str, object]]:
    """Every recorded card row, which is the shape a bridged card has to have."""
    cards: list[dict[str, object]] = []
    for pile in recorded_piles():
        rows = pile.get("cards")
        if isinstance(rows, list):
            cards.extend(dict(row) for row in rows if isinstance(row, dict))
    return cards


def bridge_card_projection() -> str:
    """The body of the bridge's own card row, which is where a card's members are read from."""
    return bridge_method_body(CARD_ROW_SIGNATURE)


def bridge_method_body(signature: str) -> str:
    """The body of one block-bodied method of the bridge's state tracker."""
    source = (BRIDGE_DIR / "FullAppStateTracker.cs").read_text(encoding="utf-8")
    body = re.search(rf"{re.escape(signature)}\s*\n\s*\{{(.*?)\n    \}}", source, re.DOTALL)
    assert body, f"this test no longer reads {signature}"
    return body.group(1)


def test_the_bridge_dtos_this_test_reads_are_the_ones_the_bridge_declares() -> None:
    names = dto_properties()
    assert {
        "CombatObservationDto",
        "CreatureObservationDto",
        "NextMoveObservationDto",
        "PileObservationDto",
        "CardObservationDto",
    } <= set(names)


def test_the_bridge_combat_block_carries_the_fields_the_simulator_carries() -> None:
    bridge = set(dto_properties()["CombatObservationDto"])
    missing = CONVERGED_COMBAT_KEYS - bridge
    assert not missing, f"the bridge's combat block does not report {sorted(missing)}"


def test_the_bridge_combat_block_words_those_fields_the_way_the_simulator_does() -> None:
    source = ENVIRONMENT.read_text(encoding="utf-8")
    start = source.index("Dictionary<string, object?> combatObservation = new()")
    simulator = set(re.findall(r'\["([a-z_]+)"\] = ', source[start : source.index("if (_reset!.CaptureOrbs", start)]))
    assert CONVERGED_COMBAT_KEYS <= simulator, "this test no longer reads the simulator's combat block"

    bridge = set(dto_properties()["CombatObservationDto"])
    # The bridge may carry less than the simulator (the orbs the contract does not mention) and
    # nothing else: a converged field has to be spelled the way the simulator spells it.
    assert CONVERGED_COMBAT_KEYS <= bridge <= simulator


def test_the_bridge_no_longer_carries_its_older_hand_seam() -> None:
    """The hand list and the three pile counts were the card seam the ordered piles replace."""
    combat = set(dto_properties()["CombatObservationDto"])
    assert "hand" not in combat
    counted = {name for name in combat if name.endswith("_pile_count")}
    assert not counted, f"the combat block still counts piles instead of reporting them: {sorted(counted)}"

    source = (BRIDGE_DIR / "FullAppStateTracker.cs").read_text(encoding="utf-8")
    assert "PileType.Draw.GetPile(player).Cards.Count" not in source


def test_a_bridge_pile_row_is_word_for_word_the_recorded_pile_row() -> None:
    recorded = recorded_piles()
    assert recorded, "the fixture records no pile at all"
    keys = {key for pile in recorded for key in pile}
    assert set(dto_properties()["PileObservationDto"]) == keys


def test_a_bridge_card_row_is_word_for_word_the_recorded_card_row() -> None:
    recorded = {key for card in recorded_cards() for key in card}
    assert recorded == CARD_KEYS, "this test no longer reads the recorded card rows"
    # `enchantment` is declared but never recorded here: a card carries one only when it is
    # enchanted, and every projection drops the null member.
    assert set(dto_properties()["CardObservationDto"]) == CARD_KEYS | {"enchantment"}
    assert set(dto_properties()["EnchantmentObservationDto"]) == {"model_id", "amount"}


def test_a_bridge_card_row_matches_the_simulator_projection_it_converges_on() -> None:
    source = ENVIRONMENT.read_text(encoding="utf-8")
    body = re.search(r"private object Pile\(string name\)\s*\n\s*\{(.*?)\n    \}", source, re.DOTALL)
    assert body, "this test no longer reads the simulator's pile projection"
    simulator_names = set(re.findall(r"([a-z_]+) = ", body.group(1)))

    invented = set(dto_properties()["CardObservationDto"]) - simulator_names
    assert not invented, f"the bridge's card row names {sorted(invented)}, which the simulator does not"


def test_the_bridge_reports_the_five_piles_in_the_order_every_projection_reports_them() -> None:
    source = (BRIDGE_DIR / "FullAppStateTracker.cs").read_text(encoding="utf-8")
    declaration = re.search(r"CombatPiles\(PlayerCombatState state\) =>\s*\[(.*?)\];", source, re.DOTALL)
    assert declaration, "this test no longer reads the bridge's pile list"
    assert re.findall(r'\("(\w+)"', declaration.group(1)) == list(PILE_ORDER)

    # The same order, and the same game-typed pile behind each name, is what a recorded fight has.
    orders = recorded_pile_orders()
    assert orders, "the fixture records no pile at all"
    for order in orders:
        assert order == [(name, PILE_TYPES[name]) for name in PILE_ORDER]

    # The type word is the game's own for the pile the bridge walked, not a word the bridge chose.
    assert "Type = pile.Type.ToString()" in bridge_method_body(PILE_ROW_SIGNATURE)


def test_a_bridge_card_row_reads_the_accessors_the_repositorys_other_projections_read() -> None:
    """Two fields used to look present while reading the wrong thing.

    The hand's cost came from a different accessor than every other projection reads, so the two
    could disagree for the same card, and the hand's upgrade count was declared but never assigned,
    so it always read zero.
    """
    card = bridge_card_projection()
    assert "EnergyCost.GetResolved()" in card, "the bridge's card row does not read the resolved cost"
    assert "EnergyCost.Canonical" not in card, "the bridge's card row reads the card's own canonical cost"
    assert "CurrentUpgradeLevel" in card, "the bridge's card row does not read the card's upgrade count"


def test_the_bridge_mints_card_instance_ids_from_its_own_registry() -> None:
    """Instance ids are the bridge's, so the comparison can treat them structurally.

    `net_id` is the opposite case: the game mints it, so it is reported literally.
    """
    registry = BRIDGE_DIR / "CardIdentity.cs"
    assert registry.is_file(), "the bridge has no card identity registry of its own"
    assert "ReferenceEqualityComparer.Instance" in registry.read_text(encoding="utf-8")

    card = bridge_card_projection()
    assert re.search(r"InstanceId = \w+\.IdFor\(", card), "the card row does not take its instance id from the registry"
    assert "NetCombatCardDb" in card, "the card's net id is not the one the game mints"


def test_a_bridge_creature_row_is_word_for_word_the_recorded_creature_row() -> None:
    _combat, creature, move, intent, power = recorded_combat_shape()
    bridge = dto_properties()

    assert set(bridge["CreatureObservationDto"]) == creature
    assert set(bridge["NextMoveObservationDto"]) == move
    assert set(bridge["IntentObservationDto"]) == intent
    assert set(bridge["PowerObservationDto"]) == power


def test_a_bridge_creature_row_matches_the_simulator_projection_it_converges_on() -> None:
    source = ENVIRONMENT.read_text(encoding="utf-8")
    body = re.search(r"private object Creature\(object c\)\s*\n\s*\{(.*?)\n    \}", source, re.DOTALL)
    assert body, "this test no longer reads the simulator's creature projection"
    simulator_names = set(re.findall(r"([a-z_]+) = ", body.group(1)))

    bridge_names = set(dto_properties()["CreatureObservationDto"])
    invented = bridge_names - simulator_names
    assert not invented, f"the bridge's creature row names {sorted(invented)}, which the simulator does not"


def test_the_bridge_reports_the_player_as_a_creature_row_rather_than_a_side_of_its_own() -> None:
    source = (BRIDGE_DIR / "FullAppStateTracker.cs").read_text(encoding="utf-8")
    assert "foreach (Creature creature in combatState.Creatures)" in source, (
        "the combat block must walk every creature, the player's own row included"
    )


def test_the_bridge_no_longer_carries_its_own_enemy_row_shape() -> None:
    source = PROTOCOL_MESSAGES.read_text(encoding="utf-8")
    names = {name for members in dto_properties().values() for name in members}
    assert "EnemyObservationDto" not in source
    assert "enemies" not in names and "is_alive" not in names and "intent" not in names


def test_the_bridge_reaches_no_field_through_the_simulators_assembly() -> None:
    project = (BRIDGE_DIR / "Sts2.NativeSim.FullAppBridge.csproj").read_text(encoding="utf-8")
    assert "Sts2.NativeSim.Core" not in project
    for path in BRIDGE_DIR.glob("*.cs"):
        assert "Sts2.NativeSim.Core" not in path.read_text(encoding="utf-8"), (
            f"{path.name} references the simulator's own assembly"
        )


def test_the_bridge_writes_the_same_null_shape_as_the_other_projections() -> None:
    """A member that can be null is absent in the simulator's captures, so it has to be here too.

    Other projections write `null` as an absent member (`JsonIgnoreCondition.WhenWritingNull` in the
    native host and the trace exporter). A bridge that wrote `null` instead would make a
    field-by-field comparison report a difference for a state the two encoders agree on.
    """
    bridge_json = (BRIDGE_DIR / "BridgeJson.cs").read_text(encoding="utf-8")
    assert "JsonIgnoreCondition.WhenWritingNull" in bridge_json

    for path in (BRIDGE_DIR / "FullAppStateTracker.cs", BRIDGE_DIR / "FullAppBridgeServer.cs"):
        assert "BridgeJson.Options" in path.read_text(encoding="utf-8"), f"{path.name} does not use the shared options"
