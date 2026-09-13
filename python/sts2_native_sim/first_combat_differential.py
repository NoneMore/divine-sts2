"""Golden first-combat differential between the shipped application and the reconstructed fast path.

`docs/first-combat-scene-generation-plan.md` (E5) makes `full_application_native` the differential
authority for the first-combat program. This module is the comparator half of that gate:

* It normalizes each environment's own observation into one **root projection** and compares field
  by field, stopping at the first difference. Missing fields are never skipped: the frozen schema
  below names every compared field, and each field one environment cannot project is listed as
  environment-only with the reason, so the report shows exactly what was and was not compared.
* It normalizes each environment's legal actions into **semantic action keys**, so a decision is
  matched by what it means (which event option, which card copy, which target) rather than by a
  filtered ordinal of the other environment's list. Ambiguous or missing semantic identity fails
  loudly.
* It drives one enumerated fast-path branch on one shipped-application worker and requires the
  semantic legal-action set to agree at every decision boundary, then compares the root projections.
* It settles where the caller asks: `stop="root"` ends at the plan's first-combat root, proven on
  both environments by `assert_root_boundary`, while `stop="endpoint"` plays the first combat out to
  the unified endpoint. A root comparison cannot settle at an earlier coordinator boundary.
* Which decisions it takes is fixed and deterministic: the recorded trace where one is supplied,
  otherwise the smallest semantic action key with coordinator wrappers excluded. Both environments
  take the same decision, and each record lists the kinds actually taken (`decision_kinds`), so a
  report never implies more action coverage than the run exercised.

What this module does not claim
-------------------------------

It compares only the manifest entries it is given. It is not a global simulator certification, it
says nothing about policy quality, and a passing comparison does not license cheap keyframe restore.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .first_combat import FIRST_COMBAT_ROOT_BOUNDARY, is_first_combat_root, run_start_request

# Canonical record schema for one differential report. Bump when the report changes shape.
DIFFERENTIAL_SCHEMA_VERSION = 2

FAST = "reconstructed_native"
FULL = "full_application_native"

# The plan's root boundary, asserted on both environments from their own native combat state.
ROOT_TURN = 1
ROOT_PHASE = "Play"

# Card properties that form a cross-environment card signature. Environment-local handles
# (`instance_id`, `net_id`, `index`) are deliberately excluded: they identify a card inside one
# process, not across processes.
CARD_SIGNATURE_KEYS = (
    "model_id", "card_type", "target_type", "energy_cost", "costs_x", "upgrades", "enchantment", "native_state",
)

# Intent and power sub-objects are compared on a fixed key set. The two transports differ only in
# whether they emit explicit JSON nulls for absent values (the reconstructed observation drops them),
# which is a serialization artifact rather than a state difference.
INTENT_KEYS = ("intent_type", "implementation", "damage", "repeats")
POWER_KEYS = ("model_id", "amount")

# The run RNG streams the root must expose, from either environment.
COMBAT_RNG_STREAMS = (
    "Shuffle", "MonsterAi", "CombatCardGeneration", "CombatPotionGeneration",
    "CombatCardSelection", "CombatEnergyCosts", "CombatTargets", "CombatOrbs",
)

# Canonical action keys that only advance a coordinator. Each environment wraps decisions in its own
# way (the fast path needs an explicit `proceed_neow`, the shipped application claims a reward button
# before it shows the card screen), so these are consumed without being paired across environments.
# No decision-bearing action is ever a wrapper.
WRAPPER_KINDS = frozenset({"proceed", "reward_open"})

# Fields this comparator requires from both environments, and the reason each environment-only field
# is not cross-compared. Anything not listed here is a schema gap, not an ignored difference.
ROOT_SCHEMA: dict[str, Any] = {
    "schema_version": DIFFERENTIAL_SCHEMA_VERSION,
    "compared_at_every_boundary": (
        "build.version", "build.assembly_sha256", "build.pck_sha256",
        "run.seed", "run.character", "run.ascension", "run.rng_counters",
        "decision.semantic_legal_action_keys",
    ),
    "compared_at_combat_boundaries": (
        "run.hp", "run.max_hp", "run.deck_multiset", "run.relics", "run.potions", "run.potion_capacity",
        "combat.turn", "combat.phase", "combat.energy", "combat.max_energy", "combat.stars",
        "combat.creatures", "combat.enemy_models", "combat.piles",
    ),
    "environment_only": {
        "run.deck": "the reconstructed environment projects the ordered deck only outside combat; "
                    "run.deck_multiset is derived from the combat piles on both sides instead",
        "run.act_id": "reconstructed observation identifies the act by index only",
        "combat.encounter.model_id": "reconstructed combat observation does not project the encounter id; "
                                     "the shipped side additionally asserts declared == observed monster list",
        "card.instance_id/net_id, creature.combat_id, *.index": "process-local handles, asserted only within one environment",
        "prefix run.relics/potions objects": "outside combat the reconstructed environment projects relic and potion ids "
                                             "without counters or native state; the full records are compared at the root",
    },
    "coordinator_wrappers": (
        "Wrapper-only boundaries carry no decision and are consumed on whichever side exposes them "
        "(the reconstructed `proceed_neow`, the shipped event PROCEED, and a claimable reward button "
        "whose content is chosen on the next screen). Every consumed wrapper is listed in the report."
    ),
    "stops": {
        "root": "follow the shared decision policy, or the recorded trace where one is supplied, to the plan's "
                "first-combat root and require combat.turn == 1 && combat.phase == Play on BOTH environments "
                "(assert_root_boundary) before comparing there; a comparison may never settle at an earlier "
                "coordinator boundary such as the Neow decision",
        "endpoint": "continue from the root to the unified endpoint: player death, or the cleared encounter "
                    "before room rewards",
    },
    "decision_policy": (
        "Recorded trace where one is supplied, otherwise the smallest semantic action key with wrappers "
        "excluded. The combat is driven by that policy on both sides, not by the shipped application's own "
        "preference; each record's `decision_kinds` lists the kinds actually taken, so a report states what "
        "was executed rather than only how far it ran."
    ),
}


class DifferentialError(RuntimeError):
    """Raised when the differential contract itself cannot be honoured."""


@dataclass(frozen=True)
class Difference:
    path: str
    expected: Any
    actual: Any
    detail: str = ""

    def as_record(self) -> dict[str, Any]:
        return {"path": self.path, "expected": self.expected, "actual": self.actual, "detail": self.detail}


def first_difference(expected: Any, actual: Any, path: str = "$") -> Difference | None:
    """First structural difference, with int/float treated as one numeric class."""
    if isinstance(expected, bool) != isinstance(actual, bool):
        return Difference(path, expected, actual)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return None if expected == actual else Difference(path, expected, actual)
    if type(expected) is not type(actual):
        return Difference(path, expected, actual)
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return Difference(path, sorted(expected.keys()), sorted(actual.keys()), "key sets differ")
        for key in expected:
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return Difference(f"{path}.length", len(expected), len(actual))
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            difference = first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return None
    return None if expected == actual else Difference(path, expected, actual)


def _card_signature(card: dict[str, Any]) -> dict[str, Any]:
    return {key: card.get(key) for key in CARD_SIGNATURE_KEYS}


def _piles(combat: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": pile.get("name"),
            "type": pile.get("type"),
            "cards": [_card_signature(card) for card in pile.get("cards") or []],
        }
        for pile in combat.get("piles") or []
    ]


def _creatures(combat: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "side": creature.get("side"),
            "model_id": creature.get("model_id"),
            "hp": creature.get("hp"),
            "max_hp": creature.get("max_hp"),
            "block": creature.get("block"),
            "alive": creature.get("alive"),
            "next_move": _next_move(creature.get("next_move")),
            "powers": [{key: power.get(key) for key in POWER_KEYS} for power in creature.get("powers") or []],
        }
        for index, creature in enumerate(combat.get("creatures") or [])
    ]


def _next_move(move: dict[str, Any] | None) -> dict[str, Any] | None:
    if move is None:
        return None
    return {
        "id": move.get("id"),
        "intents": [{key: intent.get(key) for key in INTENT_KEYS} for intent in move.get("intents") or []],
    }


def _pile(combat: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((pile for pile in combat.get("piles") or [] if pile.get("name") == name), None)


def deck_multiset(combat: dict[str, Any]) -> list[dict[str, Any]]:
    """The deck as a sorted card-signature multiset, derived from the combat piles on both sides."""
    signatures = [
        _card_signature(card)
        for pile in combat.get("piles") or []
        if pile.get("name") in ("Hand", "DrawPile", "DiscardPile", "ExhaustPile", "PlayPile")
        for card in pile.get("cards") or []
    ]
    return sorted(signatures, key=lambda signature: canonical_json(signature))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_root(environment: str, observation: dict[str, Any], character: str) -> dict[str, Any]:
    """The frozen cross-environment root projection for one observation."""
    run = observation.get("run") or {}
    combat = observation.get("combat") or {}
    creatures = _creatures(combat)
    player_creature = next((creature for creature in creatures if creature.get("side") == "Player"), None)

    if environment == FAST:
        inventory = observation.get("inventory") or {}
        relics = [
            {"model_id": relic.get("model_id"), "counter": relic.get("counter"), "native_state": relic.get("native_state")}
            for relic in inventory.get("relics") or []
        ]
        potions = [
            None if potion is None else {"slot": potion.get("slot"), "model_id": potion.get("model_id")}
            for potion in inventory.get("potions") or []
        ]
    elif environment == FULL:
        relics = [
            {"model_id": relic.get("model_id"), "counter": relic.get("counter"), "native_state": relic.get("native_state")}
            for relic in run.get("relics") or []
        ]
        potions = [
            None if potion is None else {"slot": potion.get("slot"), "model_id": potion.get("model_id")}
            for potion in run.get("potions") or []
        ]
    else:
        raise DifferentialError(f"unknown differential environment {environment!r}")

    build = observation.get("game_build") or {}
    return {
        "build": {
            "version": build.get("version"),
            "assembly_sha256": build.get("assembly_sha256"),
            "pck_sha256": build.get("pck_sha256"),
        },
        "run": {
            "seed": run.get("seed"),
            "character": run.get("character") if environment == FULL else character,
            "ascension": run.get("ascension"),
            "gold": run.get("gold"),
            "hp": (run.get("current_hp") if environment == FULL else None) or (player_creature or {}).get("hp"),
            "max_hp": (run.get("max_hp") if environment == FULL else None) or (player_creature or {}).get("max_hp"),
            "rng_counters": dict(sorted((run.get("rng_counters") or {}).items())),
            "relics": relics,
            "potions": potions,
            "potion_capacity": len(potions),
            "deck_multiset": deck_multiset(combat),
        },
        "combat": {
            "turn": combat.get("turn"),
            "phase": combat.get("phase"),
            "energy": combat.get("energy"),
            "max_energy": combat.get("max_energy"),
            "stars": combat.get("stars"),
            "creatures": creatures,
            "enemy_models": [creature["model_id"] for creature in creatures if creature.get("side") == "Enemy"],
            "piles": _piles(combat),
        },
    }


def normalize_identity(environment: str, observation: dict[str, Any], character: str) -> dict[str, Any]:
    """The run-start identity both environments project at every boundary.

    The reconstructed environment deliberately projects a narrower run block outside combat (no HP,
    piles, gold, or relic/potion records), so the prefix is compared on run identity and the full run
    RNG counter map, and the complete projection is compared at every combat boundary. The prefix's
    effects on deck, relics, potions, gold and RNG are therefore still checked, at the root.
    """
    run = observation.get("run") or {}
    build = observation.get("game_build") or {}
    return {
        "build": {
            "version": build.get("version"),
            "assembly_sha256": build.get("assembly_sha256"),
            "pck_sha256": build.get("pck_sha256"),
        },
        "run": {
            "seed": run.get("seed"),
            "character": run.get("character") if environment == FULL else character,
            "ascension": run.get("ascension"),
            "rng_counters": dict(sorted((run.get("rng_counters") or {}).items())),
        },
    }


def is_combat_boundary(observation: dict[str, Any]) -> bool:
    combat = observation.get("combat") or {}
    return combat.get("turn") is not None and combat.get("phase") is not None


def assert_root_boundary(observation: dict[str, Any], environment: str, label: str) -> None:
    """The plan's boundary, read from the environment's own native combat state."""
    decision = observation.get("decision") or {}
    combat = observation.get("combat") or {}
    if observation.get("phase") not in ("combat", "combat_complete") and decision.get("kind") not in ("combat_action", "combat_complete"):
        raise DifferentialError(f"{label} ({environment}) is a {observation.get('phase')!r}/{decision.get('kind')!r} boundary, not combat")
    if combat.get("turn") != ROOT_TURN or combat.get("phase") != ROOT_PHASE:
        raise DifferentialError(
            f"{label} ({environment}) is not at combat.turn == {ROOT_TURN} && combat.phase == {ROOT_PHASE}: "
            f"turn={combat.get('turn')!r} phase={combat.get('phase')!r}"
        )
    if environment == FULL:
        _assert_declared_encounter(combat, label)


def _assert_declared_encounter(combat: dict[str, Any], label: str) -> None:
    encounter = combat.get("encounter")
    if not isinstance(encounter, dict) or not encounter.get("model_id"):
        raise DifferentialError(f"{label} lost the shipped encounter identity")
    declared = list(encounter.get("monster_models") or [])
    observed = [creature.get("model_id") for creature in combat.get("creatures") or [] if creature.get("side") == "Enemy"]
    difference = first_difference(declared, observed, "$.encounter.monster_models")
    if difference:
        raise DifferentialError(
            f"{label} encounter declaration {declared} does not match the observed enemy creatures {observed}"
        )


# --------------------------------------------------------------------------------------------------
# Semantic action keys
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SemanticAction:
    """One environment's legal action, described by what it means rather than by a local ordinal."""

    kind: str
    identity: tuple
    environment: str
    local_id: str
    wrapper: bool = False

    @property
    def key(self) -> tuple[str, tuple]:
        return (self.kind, self.identity)

    def as_record(self) -> dict[str, Any]:
        return {"kind": self.kind, "identity": list(self.identity), "action_id": self.local_id, "wrapper": self.wrapper}


def _card_occurrence(pile: dict[str, Any] | None, index: int) -> tuple:
    """Stable identity of the card at `index`: its signature plus its ordinal among equal copies."""
    if pile is None:
        raise DifferentialError("the observation has no pile to resolve a card identity from")
    cards = pile.get("cards") or []
    if not (0 <= index < len(cards)):
        raise DifferentialError(f"card occurrence index {index} is outside the pile of {len(cards)} card(s)")
    signature = canonical_json(_card_signature(cards[index]))
    occurrence = sum(1 for earlier in cards[:index] if canonical_json(_card_signature(earlier)) == signature)
    return (signature, occurrence)


def _card_index_by_instance(pile: dict[str, Any] | None, instance_id: Any) -> int:
    if pile is None:
        raise DifferentialError("the observation has no pile to resolve an instance id from")
    for index, card in enumerate(pile.get("cards") or []):
        if card.get("instance_id") == instance_id:
            return index
    raise DifferentialError(f"no card in the pile carries instance id {instance_id!r}")


def _creature_index(combat: dict[str, Any], combat_id: Any) -> int:
    if combat_id is None:
        return -1
    for index, creature in enumerate(combat.get("creatures") or []):
        if creature.get("combat_id") == combat_id:
            return index
    raise DifferentialError(f"no creature carries combat id {combat_id!r}")


def _option_index(options: Sequence[dict[str, Any]], option_id: Any) -> int:
    for index, option in enumerate(options):
        if option.get("option_id") == option_id:
            return index
    raise DifferentialError(f"no pending-choice option carries id {option_id!r}")


def _selection_identity(options: Sequence[dict[str, Any]], option_ids: Sequence[Any]) -> tuple:
    if not option_ids:
        return ()
    identity = []
    for option_id in option_ids:
        index = _option_index(options, option_id)
        option = options[index]
        if option.get("model_id") is None and option.get("cards") is None:
            raise DifferentialError(f"pending-choice option {option_id!r} carries no semantic identity")
        if option.get("cards") is not None:
            identity.append(("bundle", tuple(sorted(card.get("model_id") for card in option["cards"]))))
        else:
            model = option.get("model_id")
            occurrence = sum(1 for earlier in options[:index] if earlier.get("model_id") == model)
            identity.append((model, occurrence))
    return tuple(identity)


def semantic_action(environment: str, observation: dict[str, Any], action: dict[str, Any]) -> SemanticAction:
    """Translate one environment's legal action into its semantic key."""
    if environment == FAST:
        return _fast_semantic_action(observation, action)
    if environment == FULL:
        return _full_semantic_action(observation, action)
    raise DifferentialError(f"unknown differential environment {environment!r}")


def _fast_semantic_action(observation: dict[str, Any], action: dict[str, Any]) -> SemanticAction:
    kind = action.get("kind")
    params = action.get("parameters") or {}
    action_id = str(action.get("action_id"))
    combat = observation.get("combat") or {}
    options = ((observation.get("outstanding_choice") or {}).get("options")) or []

    if kind == "choose_event":
        return SemanticAction("event_option", (params.get("text_key"),), FAST, action_id)
    if kind == "choose_cards":
        return SemanticAction("card_select", _selection_identity(options, params.get("option_ids") or []), FAST, action_id)
    if kind == "choose_option":
        return SemanticAction("bundle_select", _selection_identity(options, params.get("option_ids") or []), FAST, action_id)
    if kind in ("proceed_neow", "leave_event"):
        return SemanticAction("proceed", (), FAST, action_id, wrapper=True)
    if kind == "choose_map":
        return SemanticAction("map_node", (params.get("col"), params.get("row"), params.get("point_type")), FAST, action_id)
    if kind == "choose_reward":
        if params.get("skip"):
            return SemanticAction("reward_skip", (), FAST, action_id)
        return SemanticAction("reward_claim", (params.get("model_id"),), FAST, action_id)
    if kind == "choose_custom_reward":
        return SemanticAction("reward_claim", (params.get("model_id"),), FAST, action_id)
    if kind == "skip_custom_rewards":
        return SemanticAction("reward_skip", (), FAST, action_id)
    if kind == "play_card":
        hand = _pile(combat, "Hand")
        index = _card_index_by_instance(hand, params.get("instance_id"))
        return SemanticAction(
            "play_card",
            (_card_occurrence(hand, index), _creature_index(combat, params.get("target_id"))),
            FAST,
            action_id,
        )
    if kind == "use_potion":
        return SemanticAction(
            "use_potion",
            (params.get("model_id"), params.get("slot"), _creature_index(combat, params.get("target_id"))),
            FAST,
            action_id,
        )
    if kind == "end_turn":
        return SemanticAction("end_turn", (), FAST, action_id)
    if kind == "generate_room_rewards":
        # Beyond the unified endpoint: the endpoint is the state *before* this action, so it is never
        # taken, but it must still have a key so the endpoint classification can see it.
        return SemanticAction("generate_room_rewards", (), FAST, action_id)
    if kind == "discard_potion":
        return SemanticAction("discard_potion", (params.get("slot"), params.get("model_id")), FAST, action_id)
    raise DifferentialError(f"no semantic action key is defined for the reconstructed action kind {kind!r} ({action_id})")


def _full_semantic_action(observation: dict[str, Any], action: dict[str, Any]) -> SemanticAction:
    kind = action.get("action_type")
    meta = action.get("metadata") or {}
    action_id = str(action.get("action_id"))
    combat = observation.get("combat") or {}
    room = observation.get("room") or {}
    options = ((observation.get("outstanding_choice") or {}).get("options")) or []

    if kind == "choose_event":
        text_key = meta.get("text_key")
        finished = bool((room.get("details") or {}).get("finished"))
        if finished and text_key == "PROCEED":
            return SemanticAction("proceed", (), FULL, action_id, wrapper=True)
        if text_key is None:
            raise DifferentialError(f"shipped event option {action_id} carries no text_key")
        return SemanticAction("event_option", (text_key,), FULL, action_id)
    if kind == "choose_cards":
        return SemanticAction("card_select", _selection_identity(options, meta.get("option_ids") or []), FULL, action_id)
    if kind == "choose_option":
        return SemanticAction("bundle_select", _selection_identity(options, meta.get("option_ids") or []), FULL, action_id)
    if kind == "proceed":
        if room.get("room_type") == "Rewards":
            return SemanticAction("reward_skip", (), FULL, action_id)
        return SemanticAction("proceed", (), FULL, action_id, wrapper=True)
    if kind == "choose_map":
        return SemanticAction("map_node", (meta.get("col"), meta.get("row"), meta.get("room_type")), FULL, action_id)
    if kind == "choose_reward":
        if meta.get("model_id") is None:
            # A claimable reward button whose content is chosen on the next screen: the fast path
            # fuses the claim and the choice, so the claim itself is a coordinator wrapper.
            return SemanticAction("reward_open", (), FULL, action_id, wrapper=True)
        return SemanticAction("reward_claim", (meta.get("model_id"),), FULL, action_id)
    if kind == "choose_card":
        if meta.get("card_id") is None:
            raise DifferentialError(f"shipped card reward {action_id} carries no card identity")
        return SemanticAction("reward_claim", (meta.get("card_id"),), FULL, action_id)
    if kind == "skip_card":
        return SemanticAction("reward_skip", (), FULL, action_id)
    if kind == "play_card":
        hand = _pile(combat, "Hand")
        index = meta.get("card_index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise DifferentialError(f"shipped play_card action {action_id} carries no hand index")
        target = meta.get("target_index")
        return SemanticAction("play_card", (_card_occurrence(hand, index), target if isinstance(target, int) else -1), FULL, action_id)
    if kind == "use_potion":
        target = meta.get("target_index")
        return SemanticAction(
            "use_potion",
            (meta.get("potion_id"), meta.get("potion_index"), target if isinstance(target, int) else -1),
            FULL,
            action_id,
        )
    if kind == "end_turn":
        return SemanticAction("end_turn", (), FULL, action_id)
    raise DifferentialError(f"no semantic action key is defined for the shipped action kind {kind!r} ({action_id})")


def semantic_action_keys(environment: str, observation: dict[str, Any], actions: Iterable[dict[str, Any]]) -> list[SemanticAction]:
    return [semantic_action(environment, observation, action) for action in actions]


def decision_key_set(actions: Sequence[SemanticAction]) -> list[tuple[str, tuple]]:
    """The decision-bearing part of a legal-action set: wrappers are coordinator detail."""
    return sorted((action.kind, action.identity) for action in actions if not action.wrapper)


def decision_keys_json(actions: Sequence[SemanticAction]) -> list[str]:
    return [canonical_json(action.key) for action in actions if not action.wrapper]


@dataclass
class BranchComparison:
    """One enumerated branch driven on both environments."""

    seed: str
    character: str
    ascension: int
    branch_id: str
    trace: list[str]
    status: str
    stage: str = ""
    difference: dict[str, Any] | None = None
    error: str = ""
    fast_actions: list[str] = field(default_factory=list)
    full_actions: list[str] = field(default_factory=list)
    boundaries_compared: int = 0
    fast_wrappers: list[str] = field(default_factory=list)
    full_wrappers: list[str] = field(default_factory=list)
    root_hash: str = ""
    full_state_hash: str = ""

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "seed": self.seed,
            "character": self.character,
            "ascension": self.ascension,
            "branch_id": self.branch_id,
            "trace": list(self.trace),
            "status": self.status,
            "boundaries_compared": self.boundaries_compared,
            "fast_wrappers": list(self.fast_wrappers),
            "full_wrappers": list(self.full_wrappers),
            "root_hash": self.root_hash,
            "full_state_hash": self.full_state_hash,
        }
        if self.stage:
            record["stage"] = self.stage
        if self.difference is not None:
            record["difference"] = self.difference
        if self.error:
            record["error"] = self.error
        if self.status != "match":
            record["raw"] = {"fast_actions": self.fast_actions, "full_actions": self.full_actions}
        return record


# --------------------------------------------------------------------------------------------------
# Campaign: manifest entries -> compared roots and full first-combat trajectories
# --------------------------------------------------------------------------------------------------

# Wrapper-only boundaries are coordinator detail, not decisions. Bound how many may be consumed in a
# row so a coordinator loop fails loudly instead of hanging.
MaxWrapperSteps = 6

# Action kinds one environment can expose and the other cannot, with the reason. They are reported
# explicitly instead of being silently dropped from the decision set.
UNSUPPORTED_KINDS = {
    "discard_potion": "the shipped control bridge exposes play_card/use_potion/end_turn but no potion discard",
}

# The kinds that make up the first combat itself.
COMBAT_DECISION_KINDS = frozenset({"play_card", "use_potion", "end_turn"})

# Deterministic cross-environment policy: always take the semantically smallest decision-bearing
# action. Both environments compute the same key set first, so this is the same decision on both.
def smallest_key_policy(actions: Sequence[SemanticAction]) -> SemanticAction | None:
    candidates = [action for action in actions if not action.wrapper]
    if not candidates:
        return None
    return min(candidates, key=lambda action: canonical_json(action.key))


@dataclass
class EntryResult:
    """One manifest entry: a comparison that settles at the first-combat root or at the endpoint."""

    seed: str
    character: str
    ascension: int
    label: str = ""
    status: str = "error"
    stage: str = ""
    error: str = ""
    difference: dict[str, Any] | None = None
    root_status: str = ""
    stop: str = ""
    boundaries: int = 0
    combat_steps: int = 0
    endpoint: str = ""
    decision_kinds: list[str] = field(default_factory=list)
    fast_wrappers: list[str] = field(default_factory=list)
    full_wrappers: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    fast_hash: str = ""
    full_hash: str = ""
    build: dict[str, Any] = field(default_factory=dict)
    neow_options: list[str] = field(default_factory=list)

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "seed": self.seed,
            "character": self.character,
            "ascension": self.ascension,
            "label": self.label,
            "status": self.status,
            "stop": self.stop,
            "boundaries": self.boundaries,
            "combat_steps": self.combat_steps,
            "endpoint": self.endpoint,
            "root_status": self.root_status,
            "decision_kinds": list(self.decision_kinds),
            "fast_wrappers": list(self.fast_wrappers),
            "full_wrappers": list(self.full_wrappers),
            "unsupported": sorted(set(self.unsupported)),
            "neow_options": list(self.neow_options),
            "fast_state_hash": self.fast_hash,
            "full_state_hash": self.full_hash,
        }
        for key, value in (("stage", self.stage), ("error", self.error), ("difference", self.difference)):
            if value:
                record[key] = value
        return record


def _supportable(actions: Sequence[SemanticAction]) -> tuple[list[SemanticAction], list[str]]:
    supported = [action for action in actions if not action.wrapper and action.kind not in UNSUPPORTED_KINDS]
    unsupported = [action.kind for action in actions if not action.wrapper and action.kind in UNSUPPORTED_KINDS]
    return supported, unsupported


def _endpoint_of(environment: str, observation: dict[str, Any], actions: Sequence[SemanticAction]) -> str:
    """The plan's unified endpoint: player death, or the cleared encounter before room rewards."""
    combat = observation.get("combat") or {}
    creatures = combat.get("creatures") or []
    player = next((creature for creature in creatures if creature.get("side") == "Player"), None)
    enemies = [creature for creature in creatures if creature.get("side") == "Enemy"]
    if player is not None and player.get("alive") is False:
        return "player_death"
    if enemies and not any(creature.get("alive") for creature in enemies):
        if environment == FULL and observation.get("phase") == "combat_complete":
            return "encounter_cleared"
        if environment == FAST and not any(action.kind in COMBAT_DECISION_KINDS for action in actions if not action.wrapper):
            return "encounter_cleared"
    if environment == FULL and observation.get("phase") in ("game_over", "victory"):
        return "player_death" if observation.get("phase") == "game_over" else "victory"
    return ""


def run_entry(
    fast_worker: Any,
    full_client_factory: Callable[[], Any],
    *,
    seed: str,
    character: str,
    ascension: int,
    label: str = "",
    trace: Sequence[str] | None = None,
    run_start: dict[str, Any] | None = None,
    stop: str = "endpoint",
    max_combat_steps: int = 60,
) -> EntryResult:
    """Compare one run start on both environments, down to `stop`.

    `stop="root"` follows the shared decision policy (or the recorded trace) through the Neow ->
    first-combat prefix and settles only at the plan's first-combat root, which **both** environments
    must prove with `assert_root_boundary` (`combat.turn == 1 && combat.phase == Play`, plus the
    shipped side's declared encounter). A root comparison therefore cannot silently stop at an earlier
    coordinator boundary such as the Neow decision.

    `stop="endpoint"` continues from the root to the unified endpoint (player death, or the cleared
    encounter before room rewards).

    With `trace` the fast path follows a recorded branch; without it both environments follow the
    deterministic semantic policy. Every boundary compares the semantic legal-action sets and the
    state projection, so a divergence is reported at the step that caused it. The decisions actually
    taken are recorded in `EntryResult.decision_kinds`.
    """
    if stop not in ("root", "endpoint"):
        raise DifferentialError(f"unknown differential stop {stop!r}; expected 'root' or 'endpoint'")
    result = EntryResult(
        seed=seed, character=character, ascension=ascension, label=label or f"{seed}|{character}|A{ascension}", stop=stop
    )
    result.build = dict(getattr(fast_worker, "build", {}) or {})
    try:
        full_client = full_client_factory()
    except Exception as error:  # noqa: BLE001 - a worker that cannot start is a reported failure
        result.stage = "worker_launch"
        result.error = f"{type(error).__name__}: {error}"
        result.status = "error"
        return result
    try:
        started = full_client.start_run(
            seed=seed, character=character, ascension=ascension, combat_complete=(stop == "endpoint")
        )
        full_state = started.get("observation") or {}
        fast_state = fast_worker.neow_run_reset(run_start or run_start_request(seed, character, ascension, fast_worker.build))
        remainder = list(trace or [])
        budget = len(remainder) + max_combat_steps + 6 * MaxWrapperSteps + 8

        for _ in range(budget):
            fast_observation = fast_state["observation"]
            fast_actions_raw = semantic_action_keys(FAST, fast_observation, fast_state.get("legal_actions") or [])
            full_observation = full_client.observe()
            full_state = full_observation
            full_actions_raw = semantic_action_keys(FULL, full_observation, full_client.legal_actions())

            fast_endpoint = _endpoint_of(FAST, fast_observation, fast_actions_raw)
            full_endpoint = _endpoint_of(FULL, full_observation, full_actions_raw)
            if fast_endpoint or full_endpoint:
                result.boundaries += 1
                if fast_endpoint != full_endpoint:
                    result.stage = "endpoint"
                    result.error = f"endpoint classification differs: reconstructed={fast_endpoint!r} shipped={full_endpoint!r}"
                    result.status = "error"
                    result.fast_hash = str(fast_state.get("state_hash") or "")
                    result.full_hash = str(full_observation.get("state_hash") or "")
                    return result
                projection_difference = first_difference(
                    normalize_root(FAST, fast_observation, character),
                    normalize_root(FULL, full_observation, character),
                )
                result.endpoint = fast_endpoint
                result.fast_hash = str(fast_state.get("state_hash") or "")
                result.full_hash = str(full_observation.get("state_hash") or "")
                if projection_difference:
                    result.stage = "endpoint"
                    result.difference = projection_difference.as_record()
                    result.status = "mismatch"
                    return result
                result.status = "match"
                return result

            try:
                fast_state = _consume_fast_wrappers(fast_worker, fast_state, remainder, _wrapper_sink(result))
            except DifferentialError as error:
                return _fail(result, "wrapper", str(error), fast_state, full_state)
            fast_actions = semantic_action_keys(FAST, fast_state["observation"], fast_state.get("legal_actions") or [])
            fast_supported, fast_unsupported = _supportable(fast_actions)
            result.boundaries += 1

            try:
                full_state, full_actions, _ = _consume_full_wrappers(full_client, _wrapper_sink(result), str(full_state.get("state_hash") or ""))
            except DifferentialError as error:
                return _fail(result, "wrapper", str(error), fast_state, full_state)
            full_supported, full_unsupported = _supportable(full_actions)
            result.unsupported.extend(fast_unsupported + full_unsupported)

            fast_keys = sorted(canonical_json(action.key) for action in fast_supported)
            full_keys = sorted(canonical_json(action.key) for action in full_supported)

            if fast_keys != full_keys:
                result.stage = "legal_actions"
                result.difference = _action_set_difference(fast_keys, full_keys)
                result.fast_hash = str(fast_state.get("state_hash") or "")
                result.full_hash = str(full_state.get("state_hash") or "")
                result.status = "mismatch"
                return result

            projection_difference = first_difference(
                (normalize_root if is_combat_boundary(fast_state["observation"]) else normalize_identity)(
                    FAST, fast_state["observation"], character
                ),
                (normalize_root if is_combat_boundary(fast_state["observation"]) else normalize_identity)(
                    FULL, full_state, character
                ),
            )
            if projection_difference:
                result.stage = "projection"
                result.difference = projection_difference.as_record()
                result.fast_hash = str(fast_state.get("state_hash") or "")
                result.full_hash = str(full_state.get("state_hash") or "")
                result.status = "mismatch"
                return result

            if is_first_combat_root(fast_state["observation"]):
                # The plan's root comparison: prove the boundary on both environments instead of
                # settling at whatever coordinator boundary came first (the Neow decision). An
                # endpoint trajectory passes through this boundary too, so every entry states here
                # that the root was reached, not only an entry that stops at it.
                try:
                    assert_root_boundary(fast_state["observation"], FAST, result.label)
                    assert_root_boundary(full_state, FULL, result.label)
                except DifferentialError as error:
                    return _fail(result, "root_boundary", str(error), fast_state, full_state)
                result.root_status = "match"
                if stop == "root":
                    result.status = "match"
                    result.fast_hash = str(fast_state.get("state_hash") or "")
                    result.full_hash = str(full_state.get("state_hash") or "")
                    return result

            chosen = _recorded_or_policy(fast_supported, remainder)
            if chosen is None:
                result.stage = "no_action"
                result.error = "the reconstructed environment exposed no decision-bearing action"
                result.status = "unsupported"
                return result

            try:
                full_action = _consume_to_key(full_client, full_actions, chosen)
            except DifferentialError as error:
                return _fail(result, "semantic_identity", str(error), fast_state, full_state)
            if full_action is None:
                result.stage = "wrapper"
                result.error = f"the shipped application never exposed the semantic action {chosen.key}"
                result.status = "error"
                return result

            result.decision_kinds.append(chosen.kind)
            if chosen.kind in COMBAT_DECISION_KINDS:
                result.combat_steps += 1
            fast_state = fast_worker.step(chosen.local_id)
            step_result = full_client.step(full_action.local_id)
            full_state = step_result.get("observation") or {}

        result.stage = "budget"
        wanted = FIRST_COMBAT_ROOT_BOUNDARY if stop == "root" else "the unified first-combat endpoint"
        result.error = f"the entry did not reach {wanted} within {budget} boundaries"
        result.status = "error"
        return result
    finally:
        try:
            full_client.close()
        except Exception:  # noqa: BLE001 - best-effort worker cleanup
            pass


def _recorded_or_policy(supported: Sequence[SemanticAction], remainder: list[str]) -> SemanticAction | None:
    if remainder:
        recorded = next((action for action in supported if action.local_id == remainder[0]), None)
        if recorded is not None:
            remainder.pop(0)
            return recorded
        return None
    return smallest_key_policy(list(supported))


class _WrapperSink:
    """Adapts an EntryResult to the wrapper-audit interface BranchComparison uses."""

    def __init__(self, result: EntryResult) -> None:
        self.result = result

    fast_wrappers = property(lambda self: self.result.fast_wrappers)
    full_wrappers = property(lambda self: self.result.full_wrappers)


def _wrapper_sink(result: EntryResult) -> Any:
    return _WrapperSink(result)


def _fail(result: EntryResult, stage: str, error: str, fast_state: dict[str, Any], full_state: dict[str, Any]) -> EntryResult:
    result.stage = stage
    result.error = error
    result.status = "error"
    result.fast_hash = str(fast_state.get("state_hash") or "")
    result.full_hash = str(full_state.get("state_hash") or "")
    return result


def aggregate(results: Sequence[EntryResult]) -> dict[str, Any]:
    """Error/cap/unsupported accounting, per-cell coverage and what each entry actually executed."""
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    cells: dict[str, dict[str, int]] = {}
    for result in results:
        cell = cells.setdefault(f"{result.character}|A{result.ascension}", {})
        cell[result.status] = cell.get(result.status, 0) + 1
    unsupported = sorted({kind for result in results for kind in result.unsupported})
    decision_kinds: dict[str, int] = {}
    for result in results:
        for kind in result.decision_kinds:
            decision_kinds[kind] = decision_kinds.get(kind, 0) + 1
    stops: dict[str, int] = {}
    for result in results:
        stops[result.stop or "unspecified"] = stops.get(result.stop or "unspecified", 0) + 1
    compared_roots = sum(1 for result in results if result.root_status == "match")
    return {
        "entries": len(results),
        "status_counts": dict(sorted(counts.items())),
        "stops": dict(sorted(stops.items())),
        "compared_roots": compared_roots,
        "character_ascension_cells": {cell: dict(sorted(value.items())) for cell, value in sorted(cells.items())},
        "unsupported_kinds": unsupported,
        "compared_boundaries": sum(result.boundaries for result in results),
        "compared_combat_steps": sum(result.combat_steps for result in results),
        "decision_kind_counts": dict(sorted(decision_kinds.items())),
        "decision_policy": ROOT_SCHEMA["decision_policy"],
        "endpoints": dict(sorted({endpoint: sum(1 for r in results if r.endpoint == endpoint) for endpoint in {r.endpoint for r in results if r.endpoint}}.items())),
        "global_certification": False,
        "scope": (
            "Only the manifest entries listed in this report were compared. A pass covers the Neow -> "
            "first-combat prefix and the first combat of those entries on the pinned build; it is not a "
            "simulator certification and says nothing about policy quality. `stops`, `compared_roots` and "
            "`decision_kind_counts` state where each entry settled and which action kinds it actually took."
        ),
    }



def compare_branch(
    fast_worker: Any,
    full_client: Any,
    *,
    seed: str,
    character: str,
    ascension: int,
    run_start: dict[str, Any],
    trace: Sequence[str],
    branch_id: str,
    plan: Callable[[list[SemanticAction]], SemanticAction | None] | None = None,
) -> BranchComparison:
    """Replay one recorded fast-path branch on both environments and compare every boundary.

    `plan` chooses which of the fast path's decision-bearing actions to take; it defaults to the
    action the branch recorded. Coordinator wrappers are consumed on whichever side exposes them and
    are reported, so a caller can see exactly what was normalized away.
    """
    comparison = BranchComparison(seed=seed, character=character, ascension=ascension, branch_id=branch_id, trace=list(trace), status="error")
    started = full_client.start_run(seed=seed, character=character, ascension=ascension)
    full_state_hash = str((started.get("observation") or {}).get("state_hash") or "")
    fast_state = fast_worker.neow_run_reset(run_start)
    remainder = list(trace)
    budget = len(trace) + 4 * MaxWrapperSteps + 4

    try:
        for _ in range(budget):
            fast_state = _consume_fast_wrappers(fast_worker, fast_state, remainder, comparison)
            fast_actions = semantic_action_keys(FAST, fast_state["observation"], fast_state.get("legal_actions") or [])
            comparison.fast_actions = decision_keys_json(fast_actions)
            comparison.boundaries_compared += 1

            full_observation, full_actions, full_state_hash = _consume_full_wrappers(
                full_client, comparison, full_state_hash
            )
            comparison.full_actions = decision_keys_json(full_actions)

            if comparison.fast_actions != comparison.full_actions:
                comparison.stage = "legal_actions"
                comparison.difference = _action_set_difference(comparison.fast_actions, comparison.full_actions)
                comparison.status = "mismatch"
                return comparison

            if not remainder:
                return _compare_roots(
                    comparison,
                    fast_state["observation"],
                    full_observation,
                    character,
                    str(fast_state.get("state_hash") or ""),
                    full_state_hash,
                )

            chosen = _choose_action(fast_actions, remainder[0], plan)
            if chosen is None:
                comparison.stage = "trace"
                comparison.error = f"recorded action {remainder[0]!r} is not in the legal action set"
                return comparison
            remainder.pop(0)

            full_action = _consume_to_key(full_client, full_actions, chosen)
            if full_action is None:
                comparison.stage = "wrapper"
                comparison.error = f"the shipped application never exposed the semantic action {chosen.key}"
                return comparison

            fast_state = fast_worker.step(chosen.local_id)
            full_result = full_client.step(full_action.local_id)
            full_observation = full_result.get("observation") or {}
            full_state_hash = str(full_observation.get("state_hash") or full_state_hash)
    except DifferentialError as error:
        comparison.stage = comparison.stage or "semantic_identity"
        comparison.error = str(error)
        return comparison

    comparison.stage = "trace"
    comparison.error = f"the branch did not settle within {budget} boundaries"
    return comparison


def _consume_fast_wrappers(fast_worker: Any, fast_state: dict[str, Any], remainder: list[str], comparison: BranchComparison) -> dict[str, Any]:
    """Step the reconstructed environment through wrapper-only boundaries."""
    for _ in range(MaxWrapperSteps):
        actions = semantic_action_keys(FAST, fast_state["observation"], fast_state.get("legal_actions") or [])
        if any(not action.wrapper for action in actions):
            return fast_state
        if not actions:
            raise DifferentialError("the reconstructed environment reached a boundary with no legal action")
        wrapper = next((action for action in actions if remainder and action.local_id == remainder[0]), actions[0])
        if remainder and remainder[0] == wrapper.local_id:
            remainder.pop(0)
        comparison.fast_wrappers.append(wrapper.local_id)
        fast_state = fast_worker.step(wrapper.local_id)
    raise DifferentialError(f"the reconstructed environment exposed more than {MaxWrapperSteps} chained wrapper boundaries")


def _consume_full_wrappers(full_client: Any, comparison: BranchComparison, full_state_hash: str) -> tuple[dict[str, Any], list[SemanticAction], str]:
    """Step the shipped application through wrapper-only boundaries."""
    observation = full_client.observe()
    for _ in range(MaxWrapperSteps):
        actions = semantic_action_keys(FULL, observation, full_client.legal_actions())
        if any(not action.wrapper for action in actions):
            return observation, actions, full_state_hash
        wrappers = [action for action in actions if action.wrapper]
        if not wrappers:
            raise DifferentialError("the shipped application reached a boundary with no legal action")
        comparison.full_wrappers.append(wrappers[0].local_id)
        result = full_client.step(wrappers[0].local_id)
        observation = result.get("observation") or {}
        full_state_hash = str(observation.get("state_hash") or full_state_hash)
    raise DifferentialError(f"the shipped application exposed more than {MaxWrapperSteps} chained wrapper boundaries")


def _choose_action(actions: Sequence[SemanticAction], local_id: str, plan: Callable[[list[SemanticAction]], SemanticAction | None] | None) -> SemanticAction | None:
    recorded = next((action for action in actions if action.local_id == local_id), None)
    if recorded is not None:
        return recorded
    if plan is None:
        return None
    return plan([action for action in actions if not action.wrapper])


def _consume_to_key(full_client: Any, full_actions: Sequence[SemanticAction], chosen: SemanticAction) -> SemanticAction | None:
    """Return the shipped action matching `chosen`, stepping coordinator wrappers if needed."""
    actions = list(full_actions)
    for _ in range(MaxWrapperSteps):
        matches = [action for action in actions if action.key == chosen.key and not action.wrapper]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise DifferentialError(f"the shipped application exposes {len(matches)} ambiguous actions for {chosen.key}")
        wrappers = [action for action in actions if action.wrapper]
        if not wrappers:
            return None
        full_client.step(wrappers[0].local_id)
        observation = full_client.observe()
        actions = semantic_action_keys(FULL, observation, full_client.legal_actions())
    return None


def _compare_roots(
    comparison: BranchComparison,
    fast_observation: dict[str, Any],
    full_observation: dict[str, Any],
    character: str,
    fast_state_hash: str,
    full_state_hash: str,
) -> BranchComparison:
    comparison.stage = "root"
    try:
        assert_root_boundary(fast_observation, FAST, f"{comparison.seed}|{comparison.character}|A{comparison.ascension}")
        assert_root_boundary(full_observation, FULL, f"{comparison.seed}|{comparison.character}|A{comparison.ascension}")
    except DifferentialError as error:
        comparison.error = str(error)
        comparison.status = "error"
        return comparison
    comparison.root_hash = fast_state_hash
    comparison.full_state_hash = full_state_hash
    fast_root = normalize_root(FAST, fast_observation, character)
    full_root = normalize_root(FULL, full_observation, character)
    difference = first_difference(fast_root, full_root)
    comparison.status = "match" if difference is None else "mismatch"
    if difference:
        comparison.difference = difference.as_record()
    return comparison


def _action_set_difference(fast_keys: Sequence[str], full_keys: Sequence[str]) -> dict[str, Any]:
    missing = [key for key in fast_keys if key not in full_keys]
    extra = [key for key in full_keys if key not in fast_keys]
    return {
        "path": "$.legal_actions",
        "expected": list(fast_keys),
        "actual": list(full_keys),
        "detail": canonical_json({"only_reconstructed": missing, "only_shipped": extra}),
    }
