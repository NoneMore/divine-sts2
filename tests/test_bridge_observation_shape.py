"""Offline checks that the bridge's observation is the repository's projection, not a third one.

The full-app bridge compiles against the shipped game and is only exercised end to end by an
acceptance script, so what the repository can check offline is the shape: the bridge's own DTO
declarations, the simulator's per-combat projection they have to agree with, and a capture recorded
from the shipped-game-backed worker that shows the shape a real fight has. These tests compare all
three, which is what stops the bridge drifting into a vocabulary of its own between acceptance runs.

The ordered piles and the per-card fields are the same kind of check taken further: a fight is five
ordered piles of cards, and a card is the shape the simulator's own pile projection gives one, so a
comparison of a draw pile's order and of one card's identity has something to read.

The run, inventory and build blocks are that check for everything a fight does not carry: the act
identity the bridge used to report one-based and without its variant, the two floors, the map
coordinate the run stands on — the row-0 Ancient included — the run's own named RNG counters, the
relics as objects and the potions by slot, and the build the observation was taken on.
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
RUN_ROW_SIGNATURE = "private static RunObservationDto RunObservation(RunState runState, Player? player)"
RNG_COUNTER_SIGNATURE = "private static SortedDictionary<string, int> RunRngCounters(RunState runState)"
INVENTORY_ROW_SIGNATURE = "private static InventoryObservationDto InventoryObservation(Player player)"
RELIC_ROW_SIGNATURE = "private static RelicObservationDto RelicObservation(RelicModel relic)"

#: The run block's members: the recorded combat capture's own run keys, which are the simulator's
#: combat-run projection. `act_index` is the run's zero-based `CurrentActIndex`, the base every other
#: projection in the repository reports, and `total_floor` is the counter the Ancient room advances
#: and the per-encounter generator is seeded with.
RUN_KEYS = frozenset(
    {"seed", "ascension", "gold", "act_variant", "act_index", "act_floor", "total_floor", "rng_counters"}
)

#: One relic row: the model id, the counter a relic that shows one carries, and the relic's own
#: saved state.
RELIC_KEYS = frozenset({"model_id", "counter", "native_state"})

#: One potion row: the slot it sits in, its model, and its own native state — which the shipped
#: potion's serializable form never fills, because it saves the slot and nothing else.
POTION_KEYS = frozenset({"slot", "model_id", "native_state"})

#: The build an observation was taken on, worded as the simulator, the trace exporter and the
#: published schema all word it.
BUILD_KEYS = frozenset({"version", "assembly_sha256", "pck_sha256"})

#: The flat members the run and inventory blocks replace. They were the bridge's older seams and
#: two of them read the wrong thing — `act` was one-based where the rest of the system is zero-based,
#: and `relics`/`potions` were bare model ids that dropped a potion slot's index.
REPLACED_FLAT_KEYS = frozenset({"seed", "ascension", "act", "floor", "gold", "relics", "potions"})


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


def recorded_run() -> dict[str, object]:
    """The recorded fight's run block, which is the shape a bridged fight's run block has to have."""
    block = CAPTURES[COMBAT_CAPTURE]["run"]
    assert isinstance(block, dict), "the fixture records no run block for a fight"
    return block


def recorded_inventory() -> dict[str, object]:
    """The recorded fight's inventory, which is the shape a bridged fight's inventory has to have."""
    block = CAPTURES[COMBAT_CAPTURE]["inventory"]
    assert isinstance(block, dict), "the fixture records no inventory for a fight"
    return block


def recorded_relics() -> list[dict[str, object]]:
    """Every recorded relic row, which is the shape a bridged relic has to have."""
    rows = recorded_inventory()["relics"]
    assert isinstance(rows, list), "the fixture records no relic row for a fight"
    return [dict(row) for row in rows if isinstance(row, dict)]


def simulator_inventory_row_keys(collection: str) -> set[str]:
    """The members of one row of the simulator's own inventory projection, read from its source."""
    source = ENVIRONMENT.read_text(encoding="utf-8")
    if collection == "relics":
        row = re.search(r"relics = .*?Select\(x => new \{ (.*?) \}\)", source, re.DOTALL)
    else:
        row = re.search(r"potions = .*?Select\(\(x, i\) => x is null \? null : new \{ (.*?) \}\)", source, re.DOTALL)
    assert row, f"this test no longer reads the simulator's {collection} row"
    return set(re.findall(r"(\w+) = ", row.group(1)))


def simulator_combat_run_keys() -> set[str]:
    """The members of the simulator's combat-run block, read from its own projection."""
    source = ENVIRONMENT.read_text(encoding="utf-8")
    start = source.index("Dictionary<string, object?> combatObservation = new()")
    block = re.search(r"run = new \{(.*?)\},", source[start:], re.DOTALL)
    assert block, "this test no longer reads the simulator's combat run block"
    return set(re.findall(r"(\w+) = ", block.group(1)))


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


def test_the_bridge_run_block_is_word_for_word_the_recorded_run_block() -> None:
    assert set(dto_properties()["RunObservationDto"]) == set(recorded_run()) == RUN_KEYS


def test_the_bridge_run_block_carries_the_fields_the_simulator_carries() -> None:
    simulator = simulator_combat_run_keys()
    assert RUN_KEYS <= simulator, "this test no longer reads the simulator's combat run block"
    # The bridge may carry less of the simulator's run block and nothing else, so a field it reports
    # cannot be a word the simulator does not use for the same quantity.
    assert set(dto_properties()["RunObservationDto"]) <= simulator


def test_the_bridge_reports_the_act_index_in_the_base_the_rest_of_the_system_uses() -> None:
    """The act index was reported one-based here and zero-based everywhere else.

    One-based was worse than absent: a comparison that trusted the number reported parity while
    comparing the wrong one. The base is now the run's own `CurrentActIndex`, and the Act variant is
    reported beside it rather than left to be re-derived from the seed.
    """
    run = bridge_method_body(RUN_ROW_SIGNATURE)
    assert "ActIndex = runState.CurrentActIndex" in run, "the act index is not the run's own zero-based index"
    assert not re.search(r"CurrentActIndex\s*\)?\s*\+\s*1", run), "the act index is reported one-based again"
    assert "Act.Id.Entry" in run, "the Act variant is not reported beside the act index"


def test_the_bridge_reports_both_the_act_floor_and_the_runs_total_floor() -> None:
    run = bridge_method_body(RUN_ROW_SIGNATURE)
    assert "ActFloor = runState.ActFloor" in run
    assert "TotalFloor = runState.TotalFloor" in run


def test_the_bridge_rng_counters_are_the_runs_own_named_counters() -> None:
    """The counters a comparison checks are the run's, named as the game names them.

    The simulator and the trace exporter both read `RunRngSet.ToSerializable().Counters` and key it
    by the enum member's own name; a bridge that invented a name, or keyed by an ordinal, would report
    a counter set no comparison could line up.
    """
    counters = bridge_method_body(RNG_COUNTER_SIGNATURE)
    assert "Rng.ToSerializable().Counters" in counters, "the counters are not the run's own RNG counters"
    assert "Key.ToString()" in counters, "the counters are not keyed by the game's own counter names"
    assert "SortedDictionary<string, int>" in counters, "the counters are not ordered the way the other projections order them"


def test_the_bridge_reports_the_map_coordinate_the_run_stands_on() -> None:
    """The coordinate, which includes the row-0 Ancient once the run has travelled there.

    A run travels to its act's Ancient before the first decision the bridge reports, so the coordinate
    is the row-0 node from the first observation on — which is what makes it usable as the check that
    the oracle drove the shipped game to the node a record names.
    """
    source = (BRIDGE_DIR / "FullAppStateTracker.cs").read_text(encoding="utf-8")
    assert "CurrentMapCoord" in source, "the bridge does not read the coordinate the run has travelled to"
    assert set(dto_properties()["CoordObservationDto"]) == {"col", "row"}
    assert "map_coord" in dto_properties()["ObservationDto"]


def test_the_bridge_reports_the_game_build_the_way_the_other_projections_do() -> None:
    captured = CAPTURES[COMBAT_CAPTURE]["game_build"]
    assert isinstance(captured, dict)
    assert set(dto_properties()["GameBuildDto"]) == set(captured) == BUILD_KEYS
    assert "game_build" in dto_properties()["ObservationDto"]

    build = BRIDGE_DIR / "GameBuild.cs"
    assert build.is_file(), "the bridge does not fingerprint the build it is running"
    source = build.read_text(encoding="utf-8")
    assert "ProductVersion" in source, "the build reports no version"
    assert "SHA256" in source, "the build reports no assembly or data hash"
    assert "SlayTheSpire2.pck" in source, "the build does not hash the data pack beside the assembly"


def test_the_bridge_relic_row_is_the_simulators_relic_row() -> None:
    recorded = {key for relic in recorded_relics() for key in relic}
    assert set(dto_properties()["InventoryObservationDto"]) == set(recorded_inventory()) == {"relics", "potions"}
    # The fixture's one relic shows no counter, and a null member is dropped, so `counter` is the one
    # member of the row a recorded relic does not have to exhibit.
    assert recorded == RELIC_KEYS - {"counter"}, "this test no longer reads the recorded relic rows"
    assert set(dto_properties()["RelicObservationDto"]) == simulator_inventory_row_keys("relics") == RELIC_KEYS


def test_the_bridge_potion_row_is_the_simulators_row_plus_the_state_it_carries() -> None:
    simulator = simulator_inventory_row_keys("potions")
    assert simulator == {"slot", "model_id"}, "this test no longer reads the simulator's potion row"
    assert set(dto_properties()["PotionObservationDto"]) == simulator | {"native_state"} == POTION_KEYS


def test_the_bridge_keeps_an_empty_potion_slot_as_a_null_entry() -> None:
    """A slot index is part of the state, so a list that skipped an empty slot would renumber the rest.

    The row is positional: one entry per slot, in slot order, `null` where the slot is empty — which is
    how the simulator's own inventory reports an empty belt, and what the published schema asks for.
    """
    inventory = bridge_method_body(INVENTORY_ROW_SIGNATURE)
    assert re.search(r"Potions\.Add\(potion is null \? null : ", inventory), (
        "the potion list drops empty slots instead of keeping them"
    )
    assert "for (int slot = 0; slot < player.PotionSlots.Count; slot++)" in inventory


def test_the_bridge_no_longer_carries_its_older_flat_run_and_inventory_seam() -> None:
    observation = set(dto_properties()["ObservationDto"])
    still_flat = REPLACED_FLAT_KEYS & observation
    assert not still_flat, f"the bridge still reports {sorted(still_flat)} flat beside the blocks that replace them"
    assert {"game_build", "run", "inventory", "map_coord"} <= observation


def test_the_bridge_snapshot_actually_fills_the_blocks_it_declares() -> None:
    """A declared member is not a reported one: the snapshot has to assign it.

    The blocks above are checked against their rows here, and the rows against the simulator and the
    fixture; what this pins is that the one method that builds a snapshot reaches them at all. Without
    it a block could be dropped from the snapshot and every other test would stay green, which is the
    failure the runtime acceptance exists to catch — and an offline test should catch it first.
    """
    source = (BRIDGE_DIR / "FullAppStateTracker.cs").read_text(encoding="utf-8")
    assert "obs.Run = RunObservation(runState, player);" in source
    assert "obs.Inventory = InventoryObservation(player);" in source
    assert "obs.MapCoord = new CoordObservationDto { Col = coord.col, Row = coord.row };" in source
    assert "GameBuild = GameBuild.Current," in source


def test_the_bridge_relic_row_reads_the_counter_the_way_the_other_projections_read_it() -> None:
    """A relic's counter is the one it shows, and every projection reads the same two members.

    This run's relics show no counter, so the acceptance observes the *absent* case rather than a
    value; the accessor is what is pinned here, against the simulator's and the trace exporter's own
    inventories of the same relic.
    """
    assert "relic.ShowCounter ? relic.DisplayAmount : null" in bridge_method_body(RELIC_ROW_SIGNATURE)

    trace = (paths.REPOSITORY_ROOT / "src" / "Sts2.NativeSim.TraceExporter" / "TraceExporterMod.cs").read_text(
        encoding="utf-8"
    )
    assert "x.ShowCounter ? x.DisplayAmount : (int?)null" in trace, "this test no longer reads the trace exporter"
    assert 'ReflectionTools.Get(x!, "ShowCounter")' in ENVIRONMENT.read_text(encoding="utf-8")


