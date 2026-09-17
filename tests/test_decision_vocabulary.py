"""Offline checks that the two encoders' decision words are reconciled in exactly one place.

The full-app bridge words the situation it is standing in with a `phase` on the observation, and
the simulator words the same situations with a `decision.kind` from its own vocabulary. Parity
compares the two word sets, so the reconciliation has to be one explicit table rather than a guess
at each comparison site. These tests pin it to what the repository can check offline: the phase
words the bridge can emit, the decision kinds the simulator's own source declares, and the captures
recorded from the shipped-game-backed worker that show the two meeting.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sts2_native_sim import decision_vocabulary as vocabulary
from sts2_native_sim import paths

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "canonical-observations.json"
CAPTURES: dict[str, dict[str, object]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

BRIDGE_DIR = paths.REPOSITORY_ROOT / "src" / "Sts2.NativeSim.FullAppBridge"
STATE_TRACKER = BRIDGE_DIR / "FullAppStateTracker.cs"
ENVIRONMENT = paths.REPOSITORY_ROOT / "src" / "Sts2.NativeSim.Core" / "PersistentNativeCombatEnvironment.cs"

#: The `PlayerTurnPhase` word both drivers offer player actions in, and the one the shipped enum
#: documents as "combat is not in progress and during the enemy's turn".
ACTION_PHASE = "Play"
NO_ACTION_PHASE = "None"


def bridge_emitted_phase_words() -> set[str]:
    """The phase words the bridge hands the snapshot builder, read from every site that emits one.

    The emission sites are the bridge's own sources rather than one file: a handler in the mod names
    the stage it is standing in, and a prompt the game's own flow opened names its own from the
    server. Reading one file would let an emission in the other pass the coverage check silently.
    """
    emitted: set[str] = set()
    for source in sorted(BRIDGE_DIR.glob("*.cs")):
        emitted |= set(
            re.findall(r'WaitForCoordinatorActionAsync\(\s*"([a-z_]+)"', source.read_text(encoding="utf-8"))
        )
    return emitted


def bridge_dispatched_phase_words() -> set[str]:
    """The phase words the snapshot builder describes a stage block for, read from its own dispatch."""
    return set(re.findall(r'phase == "([a-z_]+)"', STATE_TRACKER.read_text(encoding="utf-8")))


def bridge_phase_words() -> set[str]:
    """The phase words the bridge can put on an observation.

    A handler reaches the snapshot builder by handing it the stage it is standing in, and the
    builder dispatches on that same word for the stage blocks it describes. Both sites have to
    agree, so the vocabulary is the union of what each names.
    """
    return bridge_emitted_phase_words() | bridge_dispatched_phase_words()


def test_the_phase_words_this_test_reads_are_the_ones_the_bridge_emits() -> None:
    # A guard on the reading itself: if either site is restructured so these patterns stop
    # matching, the coverage test below would pass vacuously.
    words = bridge_phase_words()
    assert {"combat", "map", "event", "shop", "treasure", "simple_card_select", "victory"} <= words


def test_the_simulator_reports_every_decision_kind_the_module_declares() -> None:
    source = ENVIRONMENT.read_text(encoding="utf-8")
    for kind in sorted(vocabulary.SIMULATOR_DECISION_KINDS):
        assert f'"{kind}"' in source, f"the simulator's source does not report {kind!r} anywhere"


def test_the_mapping_covers_every_phase_word_the_bridge_can_emit() -> None:
    words = bridge_phase_words()
    unmapped = words - set(vocabulary.BRIDGE_PHASE_TO_DECISION_KINDS)
    stale = set(vocabulary.BRIDGE_PHASE_TO_DECISION_KINDS) - words
    assert not unmapped, f"the bridge can report {sorted(unmapped)} and the mapping does not name it"
    assert not stale, f"the mapping names {sorted(stale)}, which the bridge cannot report"


def test_every_phase_word_the_bridge_waits_under_describes_a_stage() -> None:
    """A word the bridge waits under with no branch is a decision it reports nothing about.

    A caller that reaches such a stage is handed an observation with no room and no legal action, so
    it cannot advance the run — which is a gap in the bridge, not a state of the game. The two sites
    are compared here because only their agreement makes a stage observable at all.
    """
    undescribed = bridge_emitted_phase_words() - bridge_dispatched_phase_words()
    assert not undescribed, (
        f"the bridge waits for a decision in {sorted(undescribed)} and the snapshot describes no stage for it"
    )


def test_the_mapping_maps_onto_decision_kinds_the_module_declares() -> None:
    mapped = {kind for kinds in vocabulary.BRIDGE_PHASE_TO_DECISION_KINDS.values() for kind in kinds}
    invented = mapped - vocabulary.SIMULATOR_DECISION_KINDS
    assert not invented, f"the mapping names decision kinds the simulator does not report: {sorted(invented)}"


def test_the_declared_simulator_vocabulary_carries_the_kinds_a_comparison_needs() -> None:
    assert {"combat_action", "terminal", "map_choice", "card_choice", "option_choice"} <= (
        vocabulary.SIMULATOR_DECISION_KINDS
    )


def test_every_mapped_bridge_phase_has_its_evidence_named() -> None:
    assert set(vocabulary.BRIDGE_PHASE_EVIDENCE) == set(vocabulary.BRIDGE_PHASE_TO_DECISION_KINDS)


@pytest.mark.parametrize("phase", sorted(vocabulary.BRIDGE_PHASE_TO_DECISION_KINDS))
def test_a_capture_pinning_a_pairing_reports_a_kind_the_pairing_allows(phase: str) -> None:
    """The recorded captures are the runtime evidence behind the mapping, so it has to hold for them."""
    for capture in vocabulary.BRIDGE_PHASE_EVIDENCE[phase]:
        assert capture in CAPTURES, f"{phase} names {capture}, which is not in the recorded fixture"
        kind = CAPTURES[capture]["decision"]["kind"]  # type: ignore[index]
        assert kind in vocabulary.BRIDGE_PHASE_TO_DECISION_KINDS[phase], (
            f"{capture} reports {kind!r}, which {phase!r} does not allow"
        )


def test_a_capture_pins_at_most_one_bridge_phase() -> None:
    cited = [capture for captures in vocabulary.BRIDGE_PHASE_EVIDENCE.values() for capture in captures]
    assert len(cited) == len(set(cited)), f"a capture pins more than one bridge phase: {sorted(cited)}"


def test_every_turn_phase_word_the_shipped_enum_declares_is_mapped() -> None:
    # The six words are `PlayerTurnPhase`'s (None, Start, AutoPrePlay, Play, AutoPostPlay, End),
    # read from the decompiled build; the enum itself is the shipped game's, so what this test can
    # check offline is that the table carries exactly those and nothing invented. The words a
    # worker actually emits are pinned against the recorded captures below.
    assert set(vocabulary.COMBAT_TURN_PHASE_TO_DECISION_KINDS) == {
        "None",
        "Start",
        "AutoPrePlay",
        "Play",
        "AutoPostPlay",
        "End",
    }


def test_every_turn_phase_word_a_recorded_capture_reports_is_mapped() -> None:
    emitted = {
        capture["combat"]["phase"]  # type: ignore[index]
        for capture in CAPTURES.values()
        if isinstance(capture.get("combat"), dict)  # type: ignore[union-attr]
    }
    assert emitted, "no recorded capture carries a combat block, so this test reads nothing"
    unmapped = emitted - set(vocabulary.COMBAT_TURN_PHASE_TO_DECISION_KINDS)
    assert not unmapped, f"a capture reports turn phase {sorted(unmapped)}, which the table does not map"


def test_a_turn_phase_the_drivers_offer_actions_in_maps_onto_the_combat_action_kind() -> None:
    assert CAPTURES["run_combat_action"]["combat"]["phase"] == ACTION_PHASE  # type: ignore[index]
    assert vocabulary.COMBAT_TURN_PHASE_TO_DECISION_KINDS[ACTION_PHASE] == frozenset({"combat_action"})


def test_the_phase_a_terminal_capture_is_observed_in_maps_onto_the_terminal_kind() -> None:
    # The simulator's own capture of a lost fight reports phase `None` and decision kind `terminal`,
    # which is the pairing this row exists for; `None` is also the shipped word for "the enemy's
    # turn", where neither driver presents a decision.
    terminal = CAPTURES["run_combat_terminal"]
    assert terminal["combat"]["phase"] == NO_ACTION_PHASE  # type: ignore[index]
    assert terminal["decision"]["kind"] == "terminal"  # type: ignore[index]
    assert vocabulary.COMBAT_TURN_PHASE_TO_DECISION_KINDS[NO_ACTION_PHASE] == frozenset({"terminal"})


def test_the_automatic_turn_phases_map_onto_no_decision_at_all() -> None:
    """Both drivers offer actions in one phase only, and the simulator steps through the rest."""
    for phase, kinds in vocabulary.COMBAT_TURN_PHASE_TO_DECISION_KINDS.items():
        if phase in (ACTION_PHASE, NO_ACTION_PHASE):
            continue
        assert kinds == frozenset(), f"{phase} is not a phase either driver presents a decision in"


def test_the_turn_phase_word_comes_from_the_shipped_enum_rather_than_a_local_copy() -> None:
    source = STATE_TRACKER.read_text(encoding="utf-8")
    assert "PlayerCombatState?.Phase.ToString()" in source, (
        "the combat block must name the shipped PlayerTurnPhase word rather than a word of its own"
    )


def test_an_unknown_phase_word_is_a_failure_rather_than_a_silent_default() -> None:
    with pytest.raises(ValueError):
        vocabulary.decision_kinds_for_bridge_phase("not_a_stage")
    with pytest.raises(ValueError):
        vocabulary.decision_kinds_for_combat_phase("not_a_turn_phase")
