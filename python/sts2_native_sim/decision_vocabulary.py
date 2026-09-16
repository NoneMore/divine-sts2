"""One explicit mapping between the two encoders' decision words.

The full-app bridge words the situation it is standing in with a `phase` on the observation. The
handler that reached the boundary names that word (`FullAppBridgeMod`'s patched room and screen
handlers) and `FullAppStateTracker.CreateStateSnapshot` dispatches the stage blocks on the same
word. The simulator words the same situations with `decision.kind`, built by
`PersistentNativeCombatEnvironment` from the run stage and from any native prompt the stage opened.
The two encoders are compared field by field, so their words are reconciled here, once, instead of
being guessed at every comparison site. The field-by-field parity projection is the intended caller;
the bridge acceptance also checks every stage word it is handed against this table, so the bridge
growing a stage nobody mapped fails there rather than in a comparison.

Two tables, because the two encoders word two different things:

* :data:`BRIDGE_PHASE_TO_DECISION_KINDS` maps a bridge observation phase word onto every decision
  kind the simulator reports while the bridge is in that stage. One bridge stage covers several
  simulator kinds because the simulator distinguishes a room *asking* from a room being *finished*
  (`event_choice` / `event_complete`) while the bridge reports the same stage word either way.
* :data:`COMBAT_TURN_PHASE_TO_DECISION_KINDS` maps the granular `combat.phase` word onto the
  decision kinds the simulator reports in that phase. Those words are the shipped `PlayerTurnPhase`
  enum's own words, which both encoders put on `combat.phase` verbatim, so a comparison reads them
  directly and only the mapping onto decision kinds is needed.

Every pairing cites the recorded captures that pin it in :data:`BRIDGE_PHASE_EVIDENCE`. An entry
with no capture is read from the two encoders' own structure rather than observed at the seam, and
says so; a capture that contradicts its pairing fails `tests/test_decision_vocabulary.py`, and a
pairing that is wrong in the unobserved part shows up as a parity mismatch in the field-by-field run.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Final

#: Every decision kind the simulator can report, read from `PersistentNativeCombatEnvironment`'s
#: capture sites. The mapping below maps onto this vocabulary and nothing else.
SIMULATOR_DECISION_KINDS: Final[frozenset[str]] = frozenset(
    {
        "combat_action",
        "terminal",
        "card_choice",
        "option_choice",
        "map_choice",
        "map_terminal",
        "reward_choice",
        "reward_complete",
        "room_reward_choice",
        "custom_reward_choice",
        "custom_reward_complete",
        "rest_choice",
        "rest_complete",
        "event_choice",
        "event_complete",
        "treasure_open",
        "treasure_relic_choice",
        "treasure_complete",
        "shop_choice",
        "act_transition",
        "run_terminal",
    }
)

#: Bridge observation phase word → the simulator decision kinds reported while the bridge is there.
BRIDGE_PHASE_TO_DECISION_KINDS: Final[Mapping[str, frozenset[str]]] = {
    # A fight, including the native prompts a fight can open (a card select from a card effect, a
    # bundle pick). The simulator reports the prompt's own kind while the bridge still says
    # `combat`; the bridge has no branch for one of those prompts yet (ticket 14).
    "combat": frozenset({"combat_action", "card_choice", "option_choice"}),
    "map": frozenset({"map_choice", "map_terminal"}),
    # The card reward draft. The simulator expresses a card reward selection as `reward_choice`
    # (recorded as `standalone_card_reward`); a draft that opens a native card prompt keeps that
    # prompt's own kind.
    "card_reward": frozenset({"reward_choice", "card_choice"}),
    # A room's rewards screen, which may open a nested reward set.
    "rewards": frozenset({"room_reward_choice", "reward_choice", "custom_reward_choice", "custom_reward_complete"}),
    "rest_site": frozenset({"rest_choice", "rest_complete"}),
    # The smith screen and the two deck card select prompts all ask for a card from a set, which
    # the simulator words `card_choice`; a prompt that asks for options is `option_choice`.
    "deck_upgrade": frozenset({"card_choice", "option_choice"}),
    "deck_card_select": frozenset({"card_choice"}),
    "simple_card_select": frozenset({"card_choice", "option_choice"}),
    "shop": frozenset({"shop_choice"}),
    "event": frozenset({"event_choice", "event_complete"}),
    "treasure": frozenset({"treasure_open", "treasure_relic_choice", "treasure_complete"}),
    # The boss victory room is the run's act transition; the game-over screen is a run that ended.
    "victory": frozenset({"act_transition"}),
    "game_over": frozenset({"terminal", "run_terminal"}),
}

#: The recorded captures behind each pairing. Empty means read from structure, not observed.
BRIDGE_PHASE_EVIDENCE: Final[Mapping[str, tuple[str, ...]]] = {
    "combat": ("run_combat_action", "standalone_combat"),
    "map": ("run_map_choice", "run_map_after_ancient"),
    "card_reward": ("standalone_card_reward",),
    "rewards": ("run_room_reward_choice",),
    "rest_site": ("run_rest_choice", "run_rest_complete"),
    "deck_upgrade": (),
    "deck_card_select": ("standalone_card_select",),
    "simple_card_select": (),
    "shop": ("run_shop_choice",),
    "event": ("run_event_choice", "run_event_complete"),
    "treasure": ("run_treasure_open", "run_treasure_relic_choice", "run_treasure_complete"),
    "victory": ("run_act_transition",),
    "game_over": ("run_combat_terminal",),
}

#: The granular `combat.phase` word → the decision kinds the simulator reports in that phase.
#: `Play` is the phase both drivers offer player actions in, so it is the one word a combat-action
#: decision is presented under. `None` is the shipped enum's word for "combat is not in progress and
#: during the enemy's turn": the terminal capture is observed there (and the bridge offers nothing
#: during an enemy's turn), so `terminal` is the kind that phase can stand for. The remaining four —
#: `Start`, `AutoPrePlay`, `AutoPostPlay` and `End` — are no decision boundary at all: the simulator
#: runs through them inside a single step, so no decision kind is ever reported in them.
COMBAT_TURN_PHASE_TO_DECISION_KINDS: Final[Mapping[str, frozenset[str]]] = {
    "None": frozenset({"terminal"}),
    "Start": frozenset(),
    "AutoPrePlay": frozenset(),
    "Play": frozenset({"combat_action"}),
    "AutoPostPlay": frozenset(),
    "End": frozenset(),
}


def decision_kinds_for_bridge_phase(phase: str) -> frozenset[str]:
    """The simulator decision kinds the bridge's `phase` word can stand for.

    An unknown word is an error rather than an empty set: a bridge phase the mapping has not seen
    is a vocabulary the comparison cannot honestly map, and silently treating it as "no decision"
    would report parity for a situation nobody described.
    """
    return _lookup(BRIDGE_PHASE_TO_DECISION_KINDS, phase, "bridge observation phase")


def decision_kinds_for_combat_phase(phase: str) -> frozenset[str]:
    """The simulator decision kinds a granular `combat.phase` word is a boundary for."""
    return _lookup(COMBAT_TURN_PHASE_TO_DECISION_KINDS, phase, "PlayerTurnPhase word")


def _lookup(table: Mapping[str, frozenset[str]], word: str, vocabulary: str) -> frozenset[str]:
    try:
        return table[word]
    except KeyError as error:
        raise ValueError(f"{word!r} is not a {vocabulary}; known: {sorted(table)}") from error
