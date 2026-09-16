"""Offline checks that the bridge's combat block is the repository's combat projection, not a third one.

The full-app bridge compiles against the shipped game and is only exercised end to end by an
acceptance script, so what the repository can check offline is the shape: the bridge's own DTO
declarations, the simulator's per-combat projection they have to agree with, and a capture recorded
from the shipped-game-backed worker that shows the shape a real fight has. These tests compare all
three, which is what stops the bridge drifting into a vocabulary of its own between acceptance runs.
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
#: the bridge's did not. The ordered `piles` and the per-card fields are a later convergence, and
#: `orbs` is in neither the bridge nor the parity contract.
CONVERGED_COMBAT_KEYS = frozenset({"encounter", "turn", "phase", "energy", "max_energy", "stars", "creatures"})


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


def test_the_bridge_dtos_this_test_reads_are_the_ones_the_bridge_declares() -> None:
    names = dto_properties()
    assert {"CombatObservationDto", "CreatureObservationDto", "NextMoveObservationDto"} <= set(names)


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
    # The bridge may carry more (its hand and pile counts are the older card seam it still reports),
    # but every converged field has to be spelled the way the simulator spells it.
    assert CONVERGED_COMBAT_KEYS <= bridge <= simulator | {"hand", "draw_pile_count", "discard_pile_count", "exhaust_pile_count"}


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
