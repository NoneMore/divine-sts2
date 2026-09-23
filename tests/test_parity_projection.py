"""The parity contract's field list and its projection, checked offline.

The field-by-field parity run needs the shipped game, so what the offline suite can hold still is
everything about the comparison that is not the game: the shape both encoders are projected into, the
contract's field list, the normalisations that stop a vocabulary or a base difference being reported
as a mismatch, the fields the contract deliberately does not compare, and the oracle's own report of
that list. All of it is asserted against the *same* declaration the oracle reads, so a field the oracle
compares but this list does not name — or the other way round — fails here.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sts2_native_sim import parity
from sts2_native_sim import parity_projection as projection

from tests.acceptance.parity_run_acceptance import SAMPLE, report

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "canonical-observations.json"
#: A recorded fight from the shipped-game-backed worker: the shape a record's combat initial state
#: has, and the one the bridge's observation converged on.
CAPTURE: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["run_combat_action"]


def _record_state() -> dict[str, Any]:
    """One fully populated combat initial state, in the simulator's own shape.

    "Fully populated" is the point: it carries a creature with a next move and an attack intent, a
    creature with a power, a card with an enchantment, a relic that shows a counter, a relic that does
    not, an occupied potion slot and an empty one — every member the contract declares, so the field
    list the projection emits can be compared with the declared list without a gap that only a gap in
    the data explains.
    """
    return {
        "schema_version": 3,
        "game_build": {"version": "0.1.0+abc", "assembly_sha256": "AA", "pck_sha256": "BB"},
        "run": {
            "seed": "PARITY01",
            "ascension": 2,
            "gold": 99,
            "act_variant": "UNDERDOCKS",
            "act_index": 0,
            "act_floor": 2,
            "total_floor": 2,
            "rng_counters": {"Niche": 4, "Shuffle": 9, "UpFront": 404},
        },
        "combat": {
            "encounter": "SLIMES_WEAK",
            "turn": 1,
            "phase": "Play",
            "energy": 3,
            "max_energy": 3,
            "stars": 0,
            "creatures": [
                {
                    "combat_id": 0, "model_id": "IRONCLAD", "side": "Player", "hp": 64, "max_hp": 80,
                    "block": 0, "alive": True, "powers": [{"model_id": "WEAK_POWER", "amount": 1}],
                },
                {
                    "combat_id": 1, "model_id": "TWIG_SLIME_M", "side": "Enemy", "hp": 28, "max_hp": 28,
                    "block": 5, "alive": True,
                    "next_move": {
                        "id": "STICKY_SHOT_MOVE",
                        "intents": [
                            {
                                "intent_type": "Attack", "implementation": "SingleAttackIntent",
                                "damage": 8, "repeats": 2,
                            },
                            {"intent_type": "StatusCard", "implementation": "StatusIntent"},
                        ],
                    },
                    "powers": [],
                },
            ],
            "piles": [
                {
                    "name": name, "type": kind,
                    "cards": [
                        {"instance_id": f"card-{kind}-0", "net_id": 0, "model_id": "STRIKE_IRONCLAD",
                         "card_type": "Attack", "target_type": "AnyEnemy", "energy_cost": 1, "costs_x": False,
                         "upgrades": 1, "enchantment": {"model_id": "SHARP", "amount": 2},
                         "native_state": {"CurrentBlock": 3}},
                    ],
                }
                for name, kind in (
                    ("Hand", "Hand"), ("DrawPile", "Draw"), ("DiscardPile", "Discard"),
                    ("ExhaustPile", "Exhaust"), ("PlayPile", "Play"),
                )
            ],
        },
        "inventory": {
            "relics": [
                {"model_id": "BURNING_BLOOD", "native_state": {"HasTriggered": False}},
                {"model_id": "BOOMING_CONCH", "counter": 2, "native_state": {}},
            ],
            "potions": [{"slot": 0, "model_id": "FIRE_POTION"}, None, None],
        },
        "decision": {"kind": "combat_action", "legal_actions": []},
    }


def _bridge_observation(state: dict[str, Any]) -> dict[str, Any]:
    """The same fight as the bridge words it: the stage on the observation, no decision kind.

    The instance ids are re-minted and a state hash is added, which is what the two encoders really
    do: a comparison that read either would report a difference for a state the two agree about.
    """
    bridge = {key: copy.deepcopy(value) for key, value in state.items() if key != "decision"}
    bridge["phase"] = "combat"
    bridge["state_hash"] = "0F1E2D3C4B5A69788796A5B4C3D2E1F00F1E2D3C4B5A69788796A5B4C3D2E1F0"
    for pile in bridge["combat"]["piles"]:
        for index, card in enumerate(pile["cards"]):
            card["instance_id"] = f"dynamic-{index}-{card['model_id']}"
    return bridge


def test_the_contracts_field_list_is_the_one_the_projections_emit() -> None:
    """The declared list and a fully populated projection are the same set of field paths.

    This is the seam the ticket names: the oracle compares the fields the projection emits and reports
    the fields :data:`CONTRACT_FIELDS` declares, and both are this one list, so the two cannot drift.
    The optional members are declared separately, and they have to be fields of the contract.
    """
    state = _record_state()
    for side, shape in (
        ("record", projection.project_record(state)),
        ("bridge", projection.project_bridge(_bridge_observation(state))),
    ):
        # The paths come back in the order the shape carries them, which is the comparison's own
        # order; what has to be the same *set* is which fields the contract covers.
        assert set(projection.shape_paths(shape)) == set(projection.CONTRACT_FIELDS), f"the {side} projection moved"
    assert projection.OPTIONAL_FIELDS <= set(projection.CONTRACT_FIELDS)


def test_the_two_projections_are_one_shape_for_one_state() -> None:
    """A record and a bridge observation of the same fight project to the same values.

    The recorded capture is the simulator's own fight; the bridge's is that fight with the stage word
    the bridge reports instead of the simulator's decision kind. Nothing about the fight changed, so
    nothing about the projections may differ — which is the claim the whole comparison rests on.
    """
    state = CAPTURE
    assert projection.project_record(state) == projection.project_bridge(_bridge_observation(state))


def test_a_mismatch_names_the_field_path_that_differed() -> None:
    """Every differing field comes back with its path, and the first is the one a report names."""
    state = _record_state()
    bridge = _bridge_observation(state)
    bridge["combat"]["creatures"][1]["hp"] = 31
    difference = projection.compare_contract(state, bridge).first
    assert difference is not None
    assert difference.path == "$.creatures[1].hp"
    assert (difference.record, difference.shipped_game) == (28, 31)

    # The helper reports the fields in sorted-path order, so "first" is the alphabetically first one
    # that moved — and every field that moved is kept, which is what makes a root cause visible.
    bridge["combat"]["creatures"][0]["hp"] = 12
    bridge["run"]["gold"] = 0
    comparison = projection.compare_contract(state, bridge)
    assert [mismatch.path for mismatch in comparison.mismatches] == [
        "$.creatures[0].hp",
        "$.creatures[1].hp",
        "$.run.gold",
    ]
    assert comparison.first is not None and comparison.first.path == "$.creatures[0].hp"


def test_neither_encoders_state_hash_or_card_instance_id_is_ever_compared() -> None:
    """The fields the contract excludes, excluded for the reasons it gives.

    Both encoders hash different things, so a hash match would prove nothing; both mint their own card
    instance ids, so two encoders never agree on one; and an intent's implementing class is not state
    the contract names. A comparison that read any of them would report a difference here, where the
    fight is the same fight.
    """
    state = _record_state()
    bridge = _bridge_observation(state)
    bridge["state_hash"] = "F" * 64
    state["state_hash"] = "0" * 64
    assert projection.compare_contract(state, bridge).mismatches == ()

    compared = set(projection.CONTRACT_FIELDS)
    assert not [path for path in compared if "state_hash" in path or "instance_id" in path]
    excluded = {field.path for field in projection.EXCLUDED_FIELDS}
    assert any("instance_id" in path for path in excluded)
    assert any("state_hash" in path for path in excluded)
    assert any("implementation" in path for path in excluded)
    # An intent's implementing class travels on both encoders' rows and is dropped by the projection
    # rather than compared, so a fixture carrying it proves the exclusion is real.
    assert "implementation" in CAPTURE["combat"]["creatures"][1]["next_move"]["intents"][0]
    assert "implementation" not in projection.project_record(CAPTURE)["creatures"][1]["next_move"]["intents"][0]


def test_an_empty_potion_slot_is_a_slot_and_not_a_gap() -> None:
    """A slot index is part of the state, so the difference is reported against the slot it is in.

    A belt that dropped its empty slots — which is how the bridge read one before ticket 13 — moves
    every potion after the gap into a slot it is not in, and the comparison has to be able to say so.
    """
    state = _record_state()
    bridge = _bridge_observation(state)
    bridge["inventory"]["potions"][0] = {"slot": 0, "model_id": "BLOCK_POTION"}
    occupied = projection.compare_contract(state, bridge).first
    assert occupied is not None and occupied.path == "$.inventory.potions[0].model_id"
    assert (occupied.record, occupied.shipped_game) == ("FIRE_POTION", "BLOCK_POTION")

    dropped = _bridge_observation(state)
    del dropped["inventory"]["potions"][1]
    difference = projection.compare_contract(state, dropped).first
    assert difference is not None and difference.path == "$.inventory.potions[2]"
    # The helper compares paths rather than shapes, so a slot one side dropped is a mismatch whose two
    # values are both null; the presence flags are what says which side still carries it.
    assert (difference.record_present, difference.shipped_present) == (True, False)


def test_the_bridge_phase_words_are_mapped_onto_the_simulators_decision_kind() -> None:
    """The bridge words the decision twice; the projection resolves both into the simulator's word.

    The stage word and the granular turn phase have to agree with each other, and the turn phase has to
    stand for exactly one decision kind, so a bridge that grew a stage nobody mapped — or that reported
    a turn phase which is not a decision boundary — is a named error rather than a guess.
    """
    state = _record_state()
    bridge = _bridge_observation(state)
    assert projection.project_bridge(bridge)["combat"]["decision_kind"] == "combat_action"
    assert projection.project_record(state)["combat"]["decision_kind"] == state["decision"]["kind"]

    unmapped = _bridge_observation(state)
    unmapped["phase"] = "a stage nobody mapped"
    with pytest.raises(projection.ParityProjectionError, match="no decision kind is mapped to"):
        projection.project_bridge(unmapped)

    # `Start` is a shipped turn phase the simulator runs through inside one step, so no decision kind
    # is ever reported in it: there is nothing for a comparison to compare.
    boundaryless = _bridge_observation(state)
    boundaryless["combat"]["phase"] = "Start"
    with pytest.raises(projection.ParityProjectionError, match="rather than one decision kind"):
        projection.project_bridge(boundaryless)

    # The two words disagreeing about what kind of decision this is is a bridge bug, not a parity
    # mismatch: a card-select stage never reports a fight, and a fight never reports `Play` under it.
    disagreeing = _bridge_observation(state)
    disagreeing["phase"] = "map"
    with pytest.raises(projection.ParityProjectionError, match="does not stand for"):
        projection.project_bridge(disagreeing)


def test_the_act_index_base_is_declared_once_and_moved_into() -> None:
    """One base, declared for both encoders, and a value that moved base is still a difference."""
    state = _record_state()
    assert projection.ACT_INDEX_BASE == 0
    for shape in (projection.project_record(state), projection.project_bridge(_bridge_observation(state))):
        assert shape["run"]["act_index"] == state["run"]["act_index"] - projection.ACT_INDEX_BASE

    # A value below the declared base cannot be read as an index in it at all.
    below = _record_state()
    below["run"]["act_index"] = projection.ACT_INDEX_BASE - 1
    with pytest.raises(projection.ParityProjectionError, match="below the shared base"):
        projection.project_record(below)


def test_a_member_the_contract_needs_but_the_encoder_does_not_carry_is_named() -> None:
    """A projection is about whether there is something to compare, not about what it says."""
    state = _record_state()
    del state["run"]["total_floor"]
    with pytest.raises(projection.ParityProjectionError, match=r"run\.total_floor"):
        projection.project_record(state)

    bridge = _bridge_observation(_record_state())
    del bridge["run"]["total_floor"]
    with pytest.raises(projection.ParityProjectionError, match=r"run\.total_floor"):
        projection.project_bridge(bridge)


def test_the_comparison_is_the_repositorys_existing_per_path_helper() -> None:
    """The helper that had no caller has this one, rather than the repository growing a third.

    Behaviour first: the counts and the mismatch list a comparison reports are the helper's own, so a
    second comparison written inside the projection could not produce them. Identity second: the name
    the projection calls *is* :func:`sts2_native_sim.parity.compare_snapshots`, the per-path helper the
    architecture review found unreferenced, which is why a caller elsewhere in the repository cannot be
    what satisfies this.
    """
    assert projection.compare_snapshots is parity.compare_snapshots
    state = _record_state()
    bridge = _bridge_observation(state)
    bridge["run"]["gold"] = 0
    comparison = projection.compare_contract(state, bridge)
    expected = parity.compare_snapshots(projection.project_record(state), projection.project_bridge(bridge))
    assert comparison.compared_fields == expected["total_fields"]
    assert [mismatch.path for mismatch in comparison.mismatches] == [
        f"$.{mismatch['path']}" for mismatch in expected["mismatches"]
    ]


def test_the_oracle_reports_the_contract_it_compares() -> None:
    """The other half of "the two seams cannot drift apart", read off the oracle's own report.

    ``report`` is the document the oracle writes for every run, and the field list in it has to be this
    module's own declaration — not a list of the oracle's that happens to agree today. It is built here
    from no results, which is the same document a run produces with its samples removed.
    """
    document = report([], {"version": "test", "assembly_sha256": "AA", "pck_sha256": "BB"}, complete_sample=False)
    assert document["contract"]["fields_compared"] == list(projection.CONTRACT_FIELDS)
    assert document["contract"]["state_hashes_compared"] == 0
    assert document["contract"]["fields_not_compared"] == [
        {"path": field.path, "reason": field.reason} for field in projection.EXCLUDED_FIELDS
    ]
    assert document["contract"]["optional_fields"] == sorted(projection.OPTIONAL_FIELDS)


def test_complete_parity_report_requires_all_sixteen_comparisons() -> None:
    """A complete run succeeds only when every fixed scenario has a field comparison."""
    assert len(SAMPLE) == 16
    assert {
        sample.character for sample in SAMPLE if sample.seed == "ACTVAR1ANT07"
    } == {"IRONCLAD", "DEFECT"}
    results = [
        {
            "label": sample.label,
            "character": sample.character,
            "ascension": sample.ascension,
            "seed": sample.seed,
            "nested_kinds": ["card_choice"] if index == 0 else [],
            "matched": True,
            "compared_fields": 1,
        }
        for index, sample in enumerate(SAMPLE)
    ]
    build = {"version": "test", "assembly_sha256": "AA", "pck_sha256": "BB"}
    complete = report(results, build, complete_sample=True)
    assert complete["success"] is True
    assert complete["sample"]["size"] == complete["matched"] == 16
    assert complete["mismatched"] == 0
    assert len(complete["results"]) == 16
    assert "probes" not in complete

    incomplete = report(results[:-1], build, complete_sample=True)
    assert incomplete["success"] is False
    duplicated = report(results[:-1] + [results[0]], build, complete_sample=True)
    assert duplicated["success"] is False


def test_reuse_candidate_report_requires_one_process_and_complete_teardown_evidence() -> None:
    build = {"version": "test", "assembly_sha256": "AA", "pck_sha256": "BB"}
    results = [
        {
            "label": sample.label,
            "character": sample.character,
            "ascension": sample.ascension,
            "seed": sample.seed,
            "nested_kinds": ["card_choice"] if index == 0 else [],
            "matched": True,
            "pid": 123,
            "process_entry_ordinal": index + 1,
            "start_path": "menu" if index == 0 else "direct",
            "warm": index > 0,
            "process_mode": "reuse",
            "startup_seconds": 1.0 if index == 0 else 0.0,
            "entry_seconds": 2.0,
            "teardown_seconds": 0.5,
            "replacement_count": 0,
            "pck_fingerprint_bytes": 1234 if index == 0 else 0,
            "pck_fingerprint_count": 1 if index == 0 else 0,
            "teardown": {
                "final_state": "idle", "ended_generation": 2 * index + 1, "driver_result": "abandoned",
                "ending_phase": "combat", "parked_wait_released": True,
                "stale_continuation_refusals": 1,
                "reset_history_counts": {"actions": 2, "state_hashes": 3}, "duration_ms": 2,
            },
        }
        for index, sample in enumerate(SAMPLE)
    ]
    complete = report(results, build, complete_sample=True, process_mode="reuse-candidate", total_wall_seconds=42.0)
    assert complete["success"] is True
    assert complete["one_process_evidence"] is True
    assert complete["performance"] == {
        "shipped_game_processes_started": 1,
        "maximum_live_process_count": 1,
        "pck_bytes_hashed": 1234,
        "pck_fingerprints": 1,
        "total_wall_seconds": 42.0,
    }

    replacement = [dict(result) for result in results]
    replacement[-1]["pid"] = 456
    replacement[-1]["replacement_count"] = 1
    assert report(replacement, build, True, process_mode="reuse-candidate")["success"] is False

    missing_teardown = [dict(result) for result in results]
    missing_teardown[3]["teardown"] = None
    assert report(missing_teardown, build, True, process_mode="reuse-candidate")["success"] is False

    stale_generation = [dict(result) for result in results]
    stale_generation[3]["teardown"] = dict(results[3]["teardown"], ended_generation=3)
    assert report(stale_generation, build, True, process_mode="reuse-candidate")["success"] is False

    unrecorded = [
        {"label": sample.label, "character": sample.character, "ascension": sample.ascension,
         "nested_kinds": [], "matched": False, "failure": "scenario generation failed"}
        for sample in SAMPLE
    ]
    no_launch = report(unrecorded, build, True, process_mode="reuse-candidate")
    assert no_launch["success"] is False
    assert no_launch["performance"]["shipped_game_processes_started"] == 0
    assert no_launch["performance"]["maximum_live_process_count"] == 0
