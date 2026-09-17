"""The parity contract in one shape, and the one comparison that reads it.

A generated scenario claims that the fight it recorded is the fight the shipped game produces for
the same situation: the same character, Ascension, canonical run seed, Act variant, Ancient choice
and nested choices, travelled to the same row-1 node. Checking that claim means comparing two
observations that two different encoders produced — the full-app bridge's observation of a real
``SlayTheSpire2.exe`` process, and the simulator's recorded combat initial state — and the two do
not word everything the same way.

This module is where they are made to. :func:`project_bridge` and :func:`project_record` each turn
one encoder's observation into the *same* shape, :data:`CONTRACT_FIELDS` is the list of field paths
that shape covers, and :func:`compare_contract` compares two projections with the repository's own
per-path helper — :func:`sts2_native_sim.parity.compare_snapshots`, which flattens both sides into leaf
paths and keeps every mismatch, and which had no caller until this comparison existed. A mismatch names
the field path that differed. The oracle, the offline tests and the evidence document all read the one
list :data:`CONTRACT_FIELDS` holds, so no field can be compared that the contract does not name, and
none can be dropped without the list moving.

Two path vocabularies meet here, and the difference is only in spelling. The contract's own list names
a *field* with an empty row marker (`$.creatures[].hp`), because a field is what the contract declares;
the helper reports an *instance* (`creatures[0].hp`), because that is what differed. The comparison
reports the helper's path with the same `$` root, so one reader can go from a mismatch to the field it
belongs to — `creatures[0].hp` is a `$.creatures[].hp` that moved.

Three things are normalised rather than compared, and each is a difference that would otherwise be
reported as a false mismatch:

* **The phase vocabulary.** The bridge words the situation twice — ``phase`` is the stage its driver
  stands in (``combat``) and ``combat.phase`` is the shipped turn phase (``Play``) — while the
  simulator words the record's decision once, as ``decision.kind`` (``combat_action``).
  :func:`_bridge_decision_kind` reads both vocabulary tables from
  :mod:`sts2_native_sim.decision_vocabulary`, so the shared shape's ``combat.decision_kind`` is one
  word on both sides.
* **The act-index base.** :data:`ACT_INDEX_BASE` is where the base the shared shape reports is
  declared, once, for both encoders. Both report the run's own zero-based ``CurrentActIndex`` — the
  bridge's one-based act *number* was repaired before this comparison existed — so the declaration is
  the whole of the normalisation, and a value that moved base is still a difference rather than being
  absorbed by a per-side guess.
* **Card identity.** ``instance_id`` is minted by whichever encoder produced the state, so two
  encoders never agree on it for the same card; the contract compares a card as its position within
  an ordered pile plus its other attributes, and :data:`EXCLUDED_FIELDS` says so. The identities the
  game itself mints — ``net_id``, a model id, the encounter id — are compared literally.

What is deliberately *not* here: any state hash. The two encoders hash different things (one hashes a
versioned observation plus a transition kernel, the other its own DTO with neither), so a hash match
would prove nothing; ``state_hash`` is an excluded field, the projections never read it, and
:func:`compare_contract` therefore cannot compare one.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .decision_vocabulary import decision_kinds_for_bridge_phase, decision_kinds_for_combat_phase
from .parity import compare_snapshots

#: The base every act index in the shared shape is reported in: zero, the run's own
#: ``CurrentActIndex``. Both encoders report it that way, so this one declaration is what keeps the
#: comparison from having two bases to reconcile — and the value is moved into the base rather than
#: assumed to be in it, so an encoder whose index moved base is a difference, not a silent conversion.
ACT_INDEX_BASE: Final[int] = 0

#: The rows the shared shape is built from: the keys of one row of each kind, in the order the
#: comparison reads them. Every row is built through :func:`_row`, which refuses a key these do not
#: name, so the shape cannot gain a member — or lose one — without the contract saying so.
BUILD_KEYS: Final[tuple[str, ...]] = ("version", "assembly_sha256", "pck_sha256")
RUN_KEYS: Final[tuple[str, ...]] = (
    "seed", "ascension", "gold", "act_variant", "act_index", "act_floor", "total_floor", "rng_counters",
)
COMBAT_KEYS: Final[tuple[str, ...]] = (
    "encounter", "turn", "phase", "decision_kind", "energy", "max_energy", "stars",
)
CREATURE_KEYS: Final[tuple[str, ...]] = (
    "combat_id", "model_id", "side", "hp", "max_hp", "block", "alive", "next_move", "powers",
)
MOVE_KEYS: Final[tuple[str, ...]] = ("id", "intents")
INTENT_KEYS: Final[tuple[str, ...]] = ("intent_type", "damage", "repeats")
POWER_KEYS: Final[tuple[str, ...]] = ("model_id", "amount")
PILE_KEYS: Final[tuple[str, ...]] = ("name", "type", "cards")
CARD_KEYS: Final[tuple[str, ...]] = (
    "net_id", "model_id", "card_type", "target_type", "energy_cost", "costs_x", "upgrades",
    "enchantment", "native_state",
)
ENCHANTMENT_KEYS: Final[tuple[str, ...]] = ("model_id", "amount")
RELIC_KEYS: Final[tuple[str, ...]] = ("model_id", "counter", "native_state")
POTION_KEYS: Final[tuple[str, ...]] = ("slot", "model_id")
ROOT_KEYS: Final[tuple[str, ...]] = ("game_build", "run", "combat", "creatures", "piles", "inventory")

#: The members whose value is one opaque object rather than a row of named fields: the run's named
#: RNG counters and a card's or relic's own saved state. The contract says *that* they are equal, not
#: that any particular key inside them is, so :func:`shape_paths` stops at them.
OPAQUE_MEMBERS: Final[tuple[str, ...]] = ("rng_counters", "native_state")

#: The members that are only ever a place other fields live, so :func:`shape_paths` names them as a
#: prefix rather than as a field of the contract. Two members are deliberately not here — a creature's
#: ``next_move`` and a card's ``enchantment`` are fields the contract declares *and* the blocks their
#: own members live in, which is why the projection writes neither of them as a plain scalar.
CONTAINER_MEMBERS: Final[tuple[str, ...]] = (
    "game_build", "run", "combat", "creatures", "piles", "inventory",
    "intents", "powers", "cards", "relics", "potions",
)


@dataclass(frozen=True)
class ExcludedField:
    """One thing the comparison deliberately does not cover, and why.

    A field a reader believes is compared but is not is worse than one that is missing: it is the
    difference between "the two encoders agree here" and "nobody looked". So each is named with the
    reason the contract leaves it out, and the oracle reports them beside the fields it does compare.
    """

    path: str
    reason: str


#: What the comparison does not cover, each with its reason.
EXCLUDED_FIELDS: Final[tuple[ExcludedField, ...]] = (
    ExcludedField(
        "piles[].cards[].instance_id",
        "minted by whichever encoder produced the state, so two encoders never agree on it for the "
        "same card; a card is compared as its position within an ordered pile plus its other "
        "attributes, and the net card id the game itself mints is compared literally",
    ),
    ExcludedField(
        "creatures[].next_move.intents[].implementation",
        "the class that implements an intent. The contract names an intent's type, damage and repeats, "
        "and a C# type name is not state a policy reads, so the projection writes an intent row without "
        "it rather than comparing a name the contract never asked for",
    ),
    ExcludedField(
        "{record,bridge}.state_hash",
        "the two encoders' hashes are incomparable by construction — one hashes a versioned "
        "observation plus a transition kernel, the other its own DTO with neither — so a hash match "
        "would prove nothing, and this comparison compares fields instead",
    ),
    ExcludedField(
        "{record,bridge}.* other than the contract's own members",
        "the record's schema tag, row type, recipe, state handle and simulator hash are the "
        "generator's own bookkeeping rather than state the shipped game has, the bridge's room, "
        "action list and coordinate are its decision surface, and everything presentational has no "
        "counterpart on the other side; the build is the one envelope member both encoders measure "
        "about the game, and it is compared",
    ),
)

#: Every leaf path of the shared shape the comparison covers, in the order it reads them. This is the
#: contract's field list: the oracle reports it, the offline tests hold a fully populated projection
#: to it, and :func:`compare_contract` can compare nothing that is not on it. Two of these are carried
#: beyond the contract's literal bullet list and are declared here rather than left implicit —
#: ``run.act_variant``, which names the Act the situation is in and is therefore part of a record's
#: identity, and ``combat.decision_kind``, which is the one word the bridge's two phase words are
#: normalised into.
CONTRACT_FIELDS: Final[tuple[str, ...]] = (
    "$.game_build.version",
    "$.game_build.assembly_sha256",
    "$.game_build.pck_sha256",
    "$.run.seed",
    "$.run.ascension",
    "$.run.gold",
    "$.run.act_variant",
    "$.run.act_index",
    "$.run.act_floor",
    "$.run.total_floor",
    "$.run.rng_counters",
    "$.combat.encounter",
    "$.combat.turn",
    "$.combat.phase",
    "$.combat.decision_kind",
    "$.combat.energy",
    "$.combat.max_energy",
    "$.combat.stars",
    "$.creatures[].combat_id",
    "$.creatures[].model_id",
    "$.creatures[].side",
    "$.creatures[].hp",
    "$.creatures[].max_hp",
    "$.creatures[].block",
    "$.creatures[].alive",
    "$.creatures[].next_move",
    "$.creatures[].next_move.id",
    "$.creatures[].next_move.intents[].intent_type",
    "$.creatures[].next_move.intents[].damage",
    "$.creatures[].next_move.intents[].repeats",
    "$.creatures[].powers[].model_id",
    "$.creatures[].powers[].amount",
    "$.piles[].name",
    "$.piles[].type",
    "$.piles[].cards[].net_id",
    "$.piles[].cards[].model_id",
    "$.piles[].cards[].card_type",
    "$.piles[].cards[].target_type",
    "$.piles[].cards[].energy_cost",
    "$.piles[].cards[].costs_x",
    "$.piles[].cards[].upgrades",
    "$.piles[].cards[].enchantment",
    "$.piles[].cards[].enchantment.model_id",
    "$.piles[].cards[].enchantment.amount",
    "$.piles[].cards[].native_state",
    "$.inventory.relics[].model_id",
    "$.inventory.relics[].counter",
    "$.inventory.relics[].native_state",
    "$.inventory.potions[].slot",
    "$.inventory.potions[].model_id",
)

#: The contract fields whose value is not always there: a creature with no next move, an intent that is
#: not an attack, a card with no enchantment, a relic that shows no counter. Each is written as an
#: explicit null in the shared shape, so the field is on both sides either way — and the parent member
#: is listed beside its children, because an absent block is itself a field that can differ.
OPTIONAL_FIELDS: Final[frozenset[str]] = frozenset({
    "$.creatures[].next_move",
    "$.creatures[].next_move.id",
    "$.creatures[].next_move.intents[].damage",
    "$.creatures[].next_move.intents[].repeats",
    "$.piles[].cards[].enchantment",
    "$.piles[].cards[].enchantment.model_id",
    "$.piles[].cards[].enchantment.amount",
    "$.inventory.relics[].counter",
})


class ParityProjectionError(ValueError):
    """One encoder's observation cannot be projected into the contract's shape.

    Raised where the projection reads a member the contract needs and does not find it, naming the
    member, the encoder that should have carried it and the field path it belongs to. It is not a
    parity mismatch: a projection is about whether there is something to compare at all, so the oracle
    records it as the sample's own failure rather than as a field that differed.
    """


def shape_paths(shape: Mapping[str, Any]) -> tuple[str, ...]:
    """Every leaf path one projected shape carries, with ``[]`` where a list's rows are.

    A member of :data:`OPAQUE_MEMBERS` is a leaf even though it is an object, because the contract
    compares the object rather than any key inside it, and a member of :data:`CONTAINER_MEMBERS` is a
    prefix rather than a field. A list is a container and not a field either, and every one of its rows
    is walked, so a member only one row of a fight carries — an enemy's next move — is reported. Paths
    come back in the order the shape first carries them, which is the comparison's own order, and
    repeated paths are reported once. Whether every declared field is *there* is the offline fixture's
    question, because a projection of a fight with no powers lists no power path at all, and a belt
    with every slot empty lists no potion path.
    """
    paths: dict[str, None] = {}
    for path in _shape_paths(shape, "$"):
        paths.setdefault(path, None)
    return tuple(paths)


def _shape_paths(shape: Mapping[str, Any], path: str) -> tuple[str, ...]:
    paths: list[str] = []
    for key, value in shape.items():
        child = f"{path}.{key}"
        if key in CONTAINER_MEMBERS:
            if isinstance(value, Mapping):
                paths.extend(_shape_paths(value, child))
            elif isinstance(value, list):
                for row in value:
                    if isinstance(row, Mapping):
                        paths.extend(_shape_paths(row, f"{child}[]"))
            continue
        paths.append(child)
        if isinstance(value, Mapping) and key not in OPAQUE_MEMBERS:
            paths.extend(_shape_paths(value, child))
    return tuple(paths)


def project_bridge(observation: Mapping[str, Any]) -> dict[str, Any]:
    """A full-app bridge observation in the contract's shape.

    The bridge words the decision twice and the simulator once, so the decision kind is resolved from
    the bridge's own two phase words here — see :func:`_bridge_decision_kind` — and everything else is
    read from the members the two encoders converged on (tickets 11 to 13).
    """
    combat = _object(observation, "combat", "bridge")
    return _project(observation, "bridge", decision_kind=_bridge_decision_kind(observation, combat))


def project_record(combat_initial_state: Mapping[str, Any]) -> dict[str, Any]:
    """A record's combat initial state in the contract's shape.

    This is the simulator's canonical observation of the fight verbatim, read through the same row
    builders the bridge's observation goes through, so the two projections cannot disagree about the
    shape — only about the values, which is what the comparison is for.
    """
    decision = _object(combat_initial_state, "decision", "record")
    return _project(combat_initial_state, "record", decision_kind=_text(decision, "kind", "record"))


@dataclass(frozen=True)
class ContractDifference:
    """One field the record and the shipped game disagree about.

    ``record`` and ``shipped_game`` are the two values at ``path``, and the ``*_present`` flags say
    whether each side carried the field at all. They matter because the helper compares a *path*, not a
    shape: a member one encoder dropped and the other kept is a mismatch whose two values can both read
    as ``None`` — an absent member and a member that is explicitly null look the same in the values and
    only the flags tell them apart. This is also where the projections' explicit-null convention pays
    off: a member that does not apply is written as null on *both* sides, so it does not appear here.
    """

    path: str
    record: Any
    shipped_game: Any
    record_present: bool
    shipped_present: bool


@dataclass(frozen=True)
class ContractComparison:
    """What one comparison found: how much of the contract was read, and every field that moved.

    ``compared_fields`` is the count the helper compared and ``mismatches`` is its own list of the
    fields that differed, in its order, so a caller that wants "the first difference" and a caller that
    wants the whole set both read the one comparison rather than running a second one.
    """

    compared_fields: int
    mismatches: tuple[ContractDifference, ...]

    @property
    def first(self) -> ContractDifference | None:
        """The first field that differed, which is the one a report names."""
        return self.mismatches[0] if self.mismatches else None


def compare_contract(
    combat_initial_state: Mapping[str, Any], bridge_observation: Mapping[str, Any]
) -> ContractComparison:
    """Every contract field the record and the shipped game disagree about.

    The comparison itself is the repository's own per-path helper,
    :func:`sts2_native_sim.parity.compare_snapshots`: it flattens both projections into leaf paths and
    keeps every mismatch, and this function contributes the projection on either side and reads its
    result — so no third comparator exists, and the count of fields compared comes from the helper
    rather than from a second walk over the shapes. The record is the helper's ``native`` side and the
    bridge its ``shadow`` side, which are the helper's own names for the two values it compares.

    No step of this reads either encoder's state hash: the projections do not carry one, so the
    comparison cannot compare one.
    """
    comparison = compare_snapshots(project_record(combat_initial_state), project_bridge(bridge_observation))
    return ContractComparison(
        compared_fields=comparison["total_fields"],
        mismatches=tuple(
            ContractDifference(
                path=f"$.{mismatch['path']}",
                record=mismatch["native"],
                shipped_game=mismatch["shadow"],
                record_present=mismatch["native_present"],
                shipped_present=mismatch["shadow_present"],
            )
            for mismatch in comparison["mismatches"]
        ),
    )


def _project(observation: Mapping[str, Any], side: str, *, decision_kind: str) -> dict[str, Any]:
    """One encoder's observation in the contract's shape, whichever encoder it came from."""
    combat = _object(observation, "combat", side)
    inventory = _object(observation, "inventory", side)
    return {
        "game_build": _build_row(_object(observation, "game_build", side), side),
        "run": _run_row(_object(observation, "run", side), side),
        "combat": _combat_row(combat, side, decision_kind=decision_kind),
        "creatures": [_creature_row(row, side) for row in _rows(combat, "creatures", side)],
        "piles": [_pile_row(row, side) for row in _rows(combat, "piles", side)],
        "inventory": {
            "relics": [_relic_row(row, side) for row in _rows(inventory, "relics", side)],
            "potions": [_potion_row(row, side) for row in _sequence(inventory, "potions", side)],
        },
    }


def _bridge_decision_kind(observation: Mapping[str, Any], combat: Mapping[str, Any]) -> str:
    """The simulator's word for the decision the bridge is standing in.

    The bridge names the stage its driver is in on the observation (``combat``) and the shipped turn
    phase on the fight (``Play``); the simulator names the record's decision once (``combat_action``).
    Both vocabulary tables are read, and the two words have to agree with each other: a stage nobody
    mapped, a turn phase that is not a decision boundary, and a turn phase whose kind the stage does
    not stand for are each named errors rather than comparison results, because a comparison against a
    word nobody mapped would be a guess.
    """
    stage = _text(observation, "phase", "bridge")
    try:
        stage_kinds = decision_kinds_for_bridge_phase(stage)
    except ValueError as error:
        raise ParityProjectionError(
            f"the bridge reports stage {stage!r}, which no decision kind is mapped to"
        ) from error

    turn_phase = _text(combat, "phase", "bridge")
    try:
        turn_kinds = decision_kinds_for_combat_phase(turn_phase)
    except ValueError as error:
        raise ParityProjectionError(
            f"the bridge reports turn phase {turn_phase!r}, which no decision kind is mapped to"
        ) from error
    if len(turn_kinds) != 1:
        raise ParityProjectionError(
            f"the bridge reports turn phase {turn_phase!r}, which stands for {sorted(turn_kinds)} rather than one "
            "decision kind, so the decision the fight is waiting for is not one word"
        )
    kind = next(iter(turn_kinds))
    if kind not in stage_kinds:
        raise ParityProjectionError(
            f"the bridge reports stage {stage!r} while its turn phase {turn_phase!r} stands for {kind!r}, which that "
            f"stage does not stand for ({sorted(stage_kinds)})"
        )
    return kind


def _build_row(build: Mapping[str, Any], side: str) -> dict[str, Any]:
    """The build the observation was taken on: both encoders fingerprint the same install."""
    return _row({key: _text(build, key, side, "game_build") for key in BUILD_KEYS}, BUILD_KEYS, side, "game_build")


def _run_row(run: Mapping[str, Any], side: str) -> dict[str, Any]:
    """Where the run is: its identity, the Act it is in, both floors and its named counters."""
    values: dict[str, Any] = {
        "seed": _text(run, "seed", side, "run"),
        "ascension": _integer(run, "ascension", side, "run"),
        "gold": _integer(run, "gold", side, "run"),
        "act_variant": _text(run, "act_variant", side, "run"),
        "act_index": _act_index(_integer(run, "act_index", side, "run")),
        "act_floor": _integer(run, "act_floor", side, "run"),
        "total_floor": _integer(run, "total_floor", side, "run"),
        "rng_counters": _counters(_object(run, "rng_counters", side, "run"), side),
    }
    return _row(values, RUN_KEYS, side, "run")


def _act_index(value: int) -> int:
    """One encoder's act index in the base the shared shape reports.

    The base is declared once, for both encoders (:data:`ACT_INDEX_BASE`), and the value is moved into
    it rather than assumed to be in it, so the comparison never has two bases to reconcile. Both
    encoders report the run's own zero-based index today, which makes this the identity — and a value
    that moved base still shows up as a difference, because the subtraction cannot guess which side
    moved.
    """
    if value < ACT_INDEX_BASE:
        raise ParityProjectionError(f"an observation reports act index {value}, below the shared base {ACT_INDEX_BASE}")
    return value - ACT_INDEX_BASE


def _counters(counters: Mapping[str, Any], side: str) -> dict[str, int]:
    """The run's named RNG counters, compared as the one object they are."""
    resolved: dict[str, int] = {}
    for name, value in counters.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise ParityProjectionError(f"the {side} observation reports RNG counter {name} as {value!r}, not a count")
        resolved[str(name)] = value
    return resolved


def _combat_row(combat: Mapping[str, Any], side: str, *, decision_kind: str) -> dict[str, Any]:
    """The fight's own scalars, with the decision it waits for in the simulator's word."""
    values: dict[str, Any] = {
        "encounter": _text(combat, "encounter", side, "combat"),
        "turn": _integer(combat, "turn", side, "combat"),
        "phase": _text(combat, "phase", side, "combat"),
        "decision_kind": decision_kind,
        "energy": _integer(combat, "energy", side, "combat"),
        "max_energy": _integer(combat, "max_energy", side, "combat"),
        "stars": _integer(combat, "stars", side, "combat"),
    }
    return _row(values, COMBAT_KEYS, side, "combat")


def _creature_row(creature: Mapping[str, Any], side: str) -> dict[str, Any]:
    """One creature: its stable id, its body, and the move it is about to make."""
    move = creature.get("next_move")
    values: dict[str, Any] = {
        "combat_id": _integer(creature, "combat_id", side, "creature"),
        "model_id": _text(creature, "model_id", side, "creature"),
        "side": _text(creature, "side", side, "creature"),
        "hp": _integer(creature, "hp", side, "creature"),
        "max_hp": _integer(creature, "max_hp", side, "creature"),
        "block": _integer(creature, "block", side, "creature"),
        "alive": _boolean(creature, "alive", side, "creature"),
        "next_move": None if move is None else _move_row(_object_value(move, side, "creature.next_move"), side),
        "powers": [_power_row(row, side) for row in _rows(creature, "powers", side)],
    }
    return _row(values, CREATURE_KEYS, side, "creature")


def _move_row(move: Mapping[str, Any], side: str) -> dict[str, Any]:
    """The move a creature is about to make, with its ordered intents."""
    values = {
        "id": _text(move, "id", side, "next_move"),
        "intents": [_intent_row(row, side) for row in _rows(move, "intents", side)],
    }
    return _row(values, MOVE_KEYS, side, "next_move")


def _intent_row(intent: Mapping[str, Any], side: str) -> dict[str, Any]:
    """One intent. An intent that is not an attack carries no damage and no repeats on either side.

    The class that implements the intent is not compared: see :data:`EXCLUDED_FIELDS`.
    """
    values: dict[str, Any] = {
        "intent_type": _text(intent, "intent_type", side, "intent"),
        "damage": _optional_integer(intent, "damage", side, "intent"),
        "repeats": _optional_integer(intent, "repeats", side, "intent"),
    }
    return _row(values, INTENT_KEYS, side, "intent")


def _power_row(power: Mapping[str, Any], side: str) -> dict[str, Any]:
    """One power a creature holds: its model and how much of it there is."""
    values = {"model_id": _text(power, "model_id", side, "power"), "amount": _integer(power, "amount", side, "power")}
    return _row(values, POWER_KEYS, side, "power")


def _pile_row(pile: Mapping[str, Any], side: str) -> dict[str, Any]:
    """One pile: the game's word for its type and its ordered contents.

    The order of a pile's cards is part of the contract — a draw pile's order is what a policy learns
    from — so neither the pile list nor a pile's cards are sorted here.
    """
    values = {
        "name": _text(pile, "name", side, "pile"),
        "type": _text(pile, "type", side, "pile"),
        "cards": [_card_row(row, side) for row in _rows(pile, "cards", side)],
    }
    return _row(values, PILE_KEYS, side, "pile")


def _card_row(card: Mapping[str, Any], side: str) -> dict[str, Any]:
    """One card, without the instance id its own encoder minted for it.

    Every other member is the simulator's own card row, which the bridge converged on: ``net_id`` is
    the game's own net card id and is compared literally, and ``native_state`` is the card's own
    evolving state, compared as the one object it is.
    """
    enchantment = card.get("enchantment")
    values: dict[str, Any] = {
        "net_id": _integer(card, "net_id", side, "card"),
        "model_id": _text(card, "model_id", side, "card"),
        "card_type": _text(card, "card_type", side, "card"),
        "target_type": _text(card, "target_type", side, "card"),
        "energy_cost": _integer(card, "energy_cost", side, "card"),
        "costs_x": _boolean(card, "costs_x", side, "card"),
        "upgrades": _integer(card, "upgrades", side, "card"),
        "enchantment": None
        if enchantment is None
        else _enchantment_row(_object_value(enchantment, side, "card.enchantment"), side),
        "native_state": _mapping(_object(card, "native_state", side, "card"), side, "card.native_state"),
    }
    return _row(values, CARD_KEYS, side, "card")


def _enchantment_row(enchantment: Mapping[str, Any], side: str) -> dict[str, Any]:
    """The enchantment a card carries: its model and how much of it there is."""
    values = {
        "model_id": _text(enchantment, "model_id", side, "enchantment"),
        "amount": _integer(enchantment, "amount", side, "enchantment"),
    }
    return _row(values, ENCHANTMENT_KEYS, side, "enchantment")


def _relic_row(relic: Mapping[str, Any], side: str) -> dict[str, Any]:
    """One relic: its model, the counter it shows, and its own saved state.

    A relic that shows no counter carries no ``counter`` member at all in either encoder's shape,
    which is the same absent-because-there-is-nothing case as an unenchanted card; the shared shape
    writes the null, so the field is compared either way.
    """
    values: dict[str, Any] = {
        "model_id": _text(relic, "model_id", side, "relic"),
        "counter": _optional_integer(relic, "counter", side, "relic"),
        "native_state": _mapping(_object(relic, "native_state", side, "relic"), side, "relic.native_state"),
    }
    return _row(values, RELIC_KEYS, side, "relic")


def _potion_row(potion: Any, side: str) -> dict[str, Any] | None:
    """One potion slot: its own slot index and the potion in it, or null where the slot is empty.

    The slot is kept even when it is empty, because the index is part of the state: a list that
    dropped empty slots would report a potion under a slot it is not in, on either side.
    """
    if potion is None:
        return None
    row = _object_value(potion, side, "potion")
    values = {"slot": _integer(row, "slot", side, "potion"), "model_id": _text(row, "model_id", side, "potion")}
    return _row(values, POTION_KEYS, side, "potion")


def _row(values: Mapping[str, Any], keys: Sequence[str], side: str, where: str) -> dict[str, Any]:
    """One row of the shared shape, in its declared key order and carrying nothing else.

    The one place a row's key set is decided, so a projection cannot quietly add a field to the shape
    the comparison reads — and so a field the contract declares cannot be written by one builder and
    forgotten by the other.
    """
    if set(values) != set(keys):
        raise ParityProjectionError(
            f"the {side} projection builds a {where} row with the keys {sorted(values)} where the contract declares "
            f"{sorted(keys)}"
        )
    return {key: values[key] for key in keys}


def _object(container: Mapping[str, Any], key: str, side: str, where: str = "") -> Mapping[str, Any]:
    """One object-valued member of an observation, or a failure that names it."""
    return _object_value(container.get(key), side, _at(where, key))


def _object_value(value: Any, side: str, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ParityProjectionError(f"the {side} observation carries no {where} block: {value!r}")
    return value


def _rows(container: Mapping[str, Any], key: str, side: str) -> list[Mapping[str, Any]]:
    """One list-valued member whose entries are rows, or a failure that names it."""
    value = container.get(key)
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise ParityProjectionError(f"the {side} observation carries no {key} rows: {value!r}")
    return list(value)


def _sequence(container: Mapping[str, Any], key: str, side: str) -> list[Any]:
    """One list-valued member whose entries may be null, which is how an empty potion slot reads."""
    value = container.get(key)
    if not isinstance(value, list):
        raise ParityProjectionError(f"the {side} observation carries no {key} list: {value!r}")
    return list(value)


def _text(container: Mapping[str, Any], key: str, side: str, where: str = "") -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise ParityProjectionError(f"the {side} observation reports {_at(where, key)} as {value!r}, not a name")
    return value


def _integer(container: Mapping[str, Any], key: str, side: str, where: str = "") -> int:
    value = container.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ParityProjectionError(f"the {side} observation reports {_at(where, key)} as {value!r}, not a count")
    return value


def _optional_integer(container: Mapping[str, Any], key: str, side: str, where: str = "") -> int | None:
    """A member a projection drops when it does not apply, which the shared shape writes as null."""
    if container.get(key) is None:
        return None
    return _integer(container, key, side, where)


def _boolean(container: Mapping[str, Any], key: str, side: str, where: str = "") -> bool:
    value = container.get(key)
    if not isinstance(value, bool):
        raise ParityProjectionError(f"the {side} observation reports {_at(where, key)} as {value!r}, not a flag")
    return value


def _mapping(value: Any, side: str, where: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ParityProjectionError(f"the {side} observation reports {where} as {value!r}, not an object")
    return dict(value)


def _at(where: str, key: str) -> str:
    """One field path for an error message, from the block a reader and the member inside it."""
    return f"{where}.{key}" if where else key
