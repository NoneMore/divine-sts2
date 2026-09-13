"""Four-worker acceptance for the `neow_run_reset` native vertical slice.

For one real run start (`game_build` + `seed` + `character` + `ascension`) the worker must reach
the shipped starting Ancient event room, resolve Neow through shipped option/nested-choice
machinery, return to the same run's map decision, and let the first combat start natively at
`combat.turn == 1` / `phase == Play`. This script verifies:

* the RPC is advertised and takes only real start parameters, so a forged post-Neow state cannot
  be expressed on the wire;
* four workers agree on the Neow decision (options, metadata, hash) and on the whole slice;
* the same `Player`/`RunState`/`Creature` survive from the Neow decision to the first combat;
* a Neow-decision handle forks into independent branches: restoring it reproduces the decision
  exactly, and one branch's exploration leaves no trace on another;
* run-start branches replay locally and across workers through the `neow_run` provenance;
* the plan's high-risk blessings (Phial Holster, New Leaf, Leafy Poultice, Neow's Bones, Scroll
  Boxes, Small Capsule, Large Capsule, A10) all reach the root, plus `Lost Coffer`, `Precise
  Scissors`, and `Winged Boots`;
* rejected run starts fail loudly as named protocol errors.

The Neow-decision handle exists only for branch isolation and replay inside this script. It is
never exported as a corpus root and never handed to a combat rollout: the only exportable training
root is the Turn 1 / Play combat state, and the exported branch in `verify_replay` is that root.

It does not claim keyframe restore, cross-worker determinism of anything beyond the listed
fixtures, or any authority over `full_application_native`; that differential is E5's gate. It also
records one boundary it cannot discriminate: on this pinned Act 1 sample the starting Ancient
point connects to every row-1 node, so the shipped `MapTravel` seam and plain children enumeration
return the same set, and Winged Boots' free travel is not observable at the starting Ancient point.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sts2_native_sim import NativeSimError, NativeWorkerPool

# Every run RNG stream that only combat construction may consume. Neow generation is event-local
# RNG, so reaching the Neow decision must leave all of them at zero.
COMBAT_RNG_STREAMS = (
    "Shuffle", "MonsterAi", "CombatCardGeneration", "CombatPotionGeneration",
    "CombatCardSelection", "CombatEnergyCosts", "CombatTargets", "CombatOrbs",
)

# The character starting deck sizes the pinned build constructs before any ascension effect.
STARTING_DECK_SIZE = {"IRONCLAD": 10, "SILENT": 12, "DEFECT": 10, "NECROBINDER": 10, "REGENT": 10}

# seed, character, ascension, the blessing the branch must take. The seeds were chosen so the
# pinned shipped event offers the named blessing; the script asserts that, so a build whose Neow
# roll changes fails loudly instead of silently testing something else.
FIXTURES = (
    ("NEOWSWEEP0000", "IRONCLAD", 0, "LARGE_CAPSULE"),
    ("NEOWSWEEP0001", "IRONCLAD", 0, "PHIAL_HOLSTER"),
    ("NEOWSWEEP0019", "IRONCLAD", 0, "SMALL_CAPSULE"),
    ("NEOWSWEEP0015", "IRONCLAD", 0, "NEW_LEAF"),
    ("NEOWSWEEP0006", "IRONCLAD", 0, "LEAFY_POULTICE"),
    ("NEOWSWEEP0020", "IRONCLAD", 0, "PRECISE_SCISSORS"),
    ("NEOWSWEEP0007", "IRONCLAD", 0, "SCROLL_BOXES"),
    ("NEOWSWEEP0013", "IRONCLAD", 0, "NEOWS_BONES"),
    ("NEOWSWEEP0008", "IRONCLAD", 0, "LOST_COFFER"),
    ("NEOWSWEEP0006", "DEFECT", 0, "WINGED_BOOTS"),
    ("NEOWSWEEP0008", "SILENT", 0, "LOST_COFFER"),
    ("NEOWSWEEP0007", "IRONCLAD", 10, "SCROLL_BOXES"),
)
ASCENSION_FIXTURE = FIXTURES[-1]
FORGERY_FIXTURE = FIXTURES[6]
# Preferred decision order while walking a branch. Each stage exposes exactly one action kind, so
# this only pins the order in which the walker looks for the next legal action.
ACTION_ORDER = ("choose_event", "choose_option", "choose_cards", "choose_custom_reward", "proceed_neow", "choose_map")


def run_start(seed: str, character: str, ascension: int) -> dict:
    return {"game_build": {}, "seed": seed, "character": character, "ascension": ascension}


def next_action(state: dict, blessing: str | None = None) -> dict | None:
    actions = state["legal_actions"]
    if blessing is not None:
        named = [a for a in actions if a["kind"] == "choose_event" and a["action_id"].endswith(blessing)]
        if named:
            return named[0]
    for kind in ACTION_ORDER:
        candidates = [a for a in actions if a["kind"] == kind]
        if candidates:
            return candidates[0]
    return None


def walk(worker, reset: dict, blessing: str, limit: int = 24) -> tuple[dict, list[str], str, str]:
    """Walk one run-start branch from the Neow decision to the first combat root.

    Returns the root state, the ordered decision trace, and the native identity snapshot taken at
    the Neow decision and at the root, both from this one construction.
    """
    state = worker.neow_run_reset(reset)
    decision_identity = canonical(worker.diagnostics()["run_identity"])
    trace: list[str] = []
    try:
        while state["observation"]["decision"]["kind"] != "combat_action":
            action = next_action(state, blessing if not trace else None)
            assert action is not None, f"{reset['seed']} produced no legal action at {state['observation']['decision']['kind']}"
            assert len(trace) < limit, f"{reset['seed']} did not reach the first combat within {limit} decisions: {trace}"
            trace.append(action["action_id"])
            state = worker.step(action["action_id"])
    except Exception as error:
        raise AssertionError(f"{reset['seed']}|{reset['character']}|A{reset['ascension']}|{blessing} failed after {trace}: {error}") from error
    return state, trace, decision_identity, canonical(worker.diagnostics()["run_identity"])


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def combat_root_checks(state: dict, label: str) -> None:
    observation = state["observation"]
    assert observation["decision"]["kind"] == "combat_action", observation["decision"]["kind"]
    assert observation["combat"]["turn"] == 1, observation["combat"]["turn"]
    assert observation["combat"]["phase"] == "Play", observation["combat"]["phase"]
    assert any(a["kind"] == "play_card" for a in state["legal_actions"]), state["legal_actions"]
    assert any(a["kind"] == "end_turn" for a in state["legal_actions"]), state["legal_actions"]
    assert observation["run"]["rng_counters"], f"{label} lost the run RNG counter map"
    assert observation["game_build"]["assembly_sha256"], f"{label} lost the build identity"


def neow_decision_checks(state: dict, worker, reset: dict, blessing: str) -> None:
    observation = state["observation"]
    assert observation["decision"]["kind"] == "event_choice", observation["decision"]
    assert observation["event"]["model_id"] == "NEOW", observation["event"]["model_id"]
    assert observation["event"]["finished"] is False
    options = observation["event"]["options"]
    assert len(options) > 0, "the native NEOW event exposed no options"
    text_keys = {option["text_key"].rsplit(".", 1)[-1] for option in options}
    assert blessing in text_keys, f"{reset['seed']} did not offer {blessing}; offered {sorted(text_keys)}"
    assert all(a["kind"] == "choose_event" for a in state["legal_actions"]), state["legal_actions"]
    for action in state["legal_actions"]:
        assert action["parameters"]["text_key"] in {o["text_key"] for o in options}

    run_start_block = observation["run_start"]
    assert run_start_block["unlock_profile"] == "unlock_state_all", run_start_block
    assert run_start_block["started_with_neow"] is True, run_start_block
    assert run_start_block["starting_point_type"] == "Ancient", run_start_block
    assert run_start_block["act_floor"] == 1, run_start_block
    assert run_start_block["should_allow_ancient"] is True, run_start_block
    assert set(run_start_block["first_floor_types"]) == {"Monster"}, run_start_block

    run = observation["run"]
    assert run["seed"] == reset["seed"], run["seed"]
    assert run["ascension"] == reset["ascension"], run["ascension"]
    expected_deck = STARTING_DECK_SIZE[reset["character"]] + (1 if reset["ascension"] >= 10 else 0)
    assert len(run["deck"]) == expected_deck, (len(run["deck"]), expected_deck)
    banes = sum(1 for card in run["deck"] if card["model_id"] == "ASCENDERS_BANE")
    assert banes == (1 if reset["ascension"] >= 10 else 0), f"A{reset['ascension']} deck has {banes} ASCENDERS_BANE"
    consumed = {s: run["rng_counters"].get(s, 0) for s in COMBAT_RNG_STREAMS if run["rng_counters"].get(s, 0) != 0}
    assert not consumed, f"{reset['seed']} consumed combat RNG before the Neow decision: {consumed}"

    diagnostics = worker.diagnostics()
    assert diagnostics["reset_mode"] == "neow_run", diagnostics["reset_mode"]
    audit = diagnostics["last_construction"]
    assert audit["mode"] == "neow_run" and audit["combat_phase_constructed"] is False, audit
    assert audit["run_phase_created_combat_state"] is False, audit
    assert audit["run_phase_player_has_combat_state"] is False, audit
    audit_consumed = {s: audit["run_phase_rng_counters"].get(s, 0) for s in COMBAT_RNG_STREAMS if audit["run_phase_rng_counters"].get(s, 0) != 0}
    assert not audit_consumed, f"run-start construction consumed combat RNG: {audit_consumed}"
    assert diagnostics["run_identity"]["unlock_profile"] == "unlock_state_all", diagnostics["run_identity"]


def verify_advertised_contract(pool: NativeWorkerPool) -> dict:
    hello = pool.workers[0].hello()
    assert "neow_run_reset" in hello["methods"], hello["methods"]
    assert hello["run_start"]["method"] == "neow_run_reset", hello["run_start"]
    assert hello["run_start"]["unlock_profile"] == "unlock_state_all", hello["run_start"]
    assert "proceed_neow" in hello["supported_subset"]["actions"], hello["supported_subset"]["actions"]
    return hello


def verify_decision_determinism(pool: NativeWorkerPool) -> dict:
    """Four workers must agree on the Neow decision for every fixture."""
    evidence = {}
    for seed, character, ascension, blessing in FIXTURES:
        reset = run_start(seed, character, ascension)
        states = pool.map(lambda worker, reset: worker.neow_run_reset(reset), [reset] * len(pool.workers))
        for state, worker in zip(states, pool.workers):
            neow_decision_checks(state, worker, reset, blessing)
        assert len({state["state_hash"] for state in states}) == 1, (seed, [s["state_hash"] for s in states])
        assert len({canonical(state["legal_actions"]) for state in states}) == 1, seed
        assert len({canonical(state["observation"]["event"]) for state in states}) == 1, seed
        assert len({canonical(state["observation"]["run_start"]) for state in states}) == 1, seed
        assert len({canonical(state["observation"]["run"]) for state in states}) == 1, seed
        evidence[f"{seed}|{character}|A{ascension}"] = states[0]["state_hash"]
    return evidence


def verify_slice(pool: NativeWorkerPool) -> dict:
    """Every fixture must reach the first-combat root identically on all four workers."""
    evidence = {}
    for seed, character, ascension, blessing in FIXTURES:
        reset = run_start(seed, character, ascension)
        roots, traces, identities = [], [], []
        for worker in pool.workers:
            state, trace, decision_identity, root_identity = walk(worker, reset, blessing)
            identities.append((decision_identity, root_identity))
            combat_root_checks(state, f"{seed}|{blessing}")
            roots.append(state)
            traces.append(trace)
        assert len({state["state_hash"] for state in roots}) == 1, (seed, [s["state_hash"] for s in roots])
        assert len({canonical(state["legal_actions"]) for state in roots}) == 1, seed
        assert len({canonical(state["observation"]) for state in roots}) == 1, seed
        assert len(set(map(tuple, traces))) == 1, (seed, traces)
        # The Neow decision and the first combat must be the same native objects in one worker; the
        # identity hashes are per-process, so this is a within-worker comparison and the cross-worker
        # agreement above is hash agreement, not identity agreement.
        for decision_identity, root_identity in identities:
            assert decision_identity == root_identity, (seed, decision_identity, root_identity)
        evidence[f"{seed}|{character}|A{ascension}|{blessing}"] = {
            "root_hash": roots[0]["state_hash"], "decisions": len(traces[0]), "trace": traces[0],
        }
    return evidence


def verify_fork_isolation(pool: NativeWorkerPool) -> dict:
    """A Neow-decision handle must fork cleanly, and branches must not contaminate each other.

    Object continuity is a within-construction property and is verified by `verify_slice`; a
    restore rebuilds the run by design, so nothing here compares identity across a reconstruction.
    """
    seed, character, ascension, blessing = FORGERY_FIXTURE
    reset = run_start(seed, character, ascension)
    worker = pool.workers[0]
    decision = worker.neow_run_reset(reset)
    handle = decision["state_handle"]
    options = [a["action_id"] for a in decision["legal_actions"]]
    assert len(options) >= 3, options
    counters = canonical(decision["observation"]["run"]["rng_counters"])

    # Branch A: resolve the blessing and the native nested choice it opens.
    branch_a = worker.step(options[0])
    while branch_a["observation"]["decision"]["kind"] in {"card_choice", "option_choice", "custom_reward_choice"}:
        branch_a = worker.step(branch_a["legal_actions"][0]["action_id"])
    assert branch_a["state_hash"] != decision["state_hash"]

    # Restoring the decision handle must reproduce it exactly, not approximate it, and must be a
    # real reconstruction rather than a resident-prefix no-op.
    restored = worker.restore(handle)
    assert restored["state_hash"] == decision["state_hash"], (restored["state_hash"], decision["state_hash"])
    assert canonical(restored["legal_actions"]) == canonical(decision["legal_actions"])
    assert canonical(restored["observation"]) == canonical(decision["observation"])
    audit = worker.diagnostics()["last_restore"]
    assert audit["path"] == "replay", audit
    assert audit["synthetic_combat_installed"] is False, audit
    assert audit["player_has_combat_state"] is False, audit
    restored_consumed = {s: audit["rng_counters"].get(s, 0) for s in COMBAT_RNG_STREAMS if audit["rng_counters"].get(s, 0) != 0}
    assert not restored_consumed, f"run-start reconstruction consumed combat RNG: {restored_consumed}"
    assert worker.diagnostics()["run_identity"]["unlock_profile"] == "unlock_state_all"

    # Branch B on the same worker after A's exploration, and on a worker that never saw A.
    branch_b = worker.step(options[1])
    assert branch_b["state_hash"] != branch_a["state_hash"]
    clean = pool.workers[1]
    fresh_decision = clean.neow_run_reset(reset)
    assert [a["action_id"] for a in fresh_decision["legal_actions"]] == options
    fresh_b = clean.step(options[1])
    assert branch_b["state_hash"] == fresh_b["state_hash"], (branch_b["state_hash"], fresh_b["state_hash"])
    assert canonical(branch_b["observation"]) == canonical(fresh_b["observation"])
    assert canonical(branch_b["observation"]["run"]["rng_counters"]) == counters

    return {
        "handle": handle,
        "options": options,
        "decision_hash": decision["state_hash"],
        "branch_a_hash": branch_a["state_hash"],
        "branch_b_hash": branch_b["state_hash"],
        "restore_audit": audit,
        "rng_counters": json.loads(counters),
    }


def verify_replay(pool: NativeWorkerPool) -> dict:
    """A run-start branch must rebuild through the `neow_run` provenance, locally and portably."""
    seed, character, ascension, blessing = FORGERY_FIXTURE
    reset = run_start(seed, character, ascension)
    worker = pool.workers[0]
    root, trace, _, _ = walk(worker, reset, blessing)
    root_hash = root["state_hash"]
    root_observation = canonical(root["observation"])
    root_actions = canonical(root["legal_actions"])
    root_handle = root["state_handle"]

    # Move the resident state away from the root so a restore cannot be a resident-prefix no-op.
    stepped = worker.step(next(a for a in root["legal_actions"] if a["kind"] == "end_turn")["action_id"])
    assert stepped["state_hash"] != root_hash
    local = worker.restore(root_handle)
    assert local["state_hash"] == root_hash, (local["state_hash"], root_hash)
    assert canonical(local["observation"]) == root_observation
    assert canonical(local["legal_actions"]) == root_actions
    local_audit = worker.diagnostics()["last_restore"]
    assert local_audit["path"] == "replay", local_audit
    assert local_audit["replayed_actions"] == len(trace) > 0, (local_audit, trace)

    branch = worker.export_branch()
    assert branch["provenance"] == "neow_run", branch["provenance"]
    assert branch["reset_request"]["method"] == "neow_run_reset", branch["reset_request"]
    assert set(branch["reset_request"]["params"]) == {"game_build", "seed", "character", "ascension"}, branch["reset_request"]
    assert branch["expected_hash"] == root_hash
    assert branch["history"] == trace

    target = pool.workers[2]
    # Deliberately put the target on a different run-start branch so the portable restore rebuilds.
    target.neow_run_reset(run_start("NEOWSWEEP0001", "IRONCLAD", 0))
    ported = pool.restore_portable(2, branch)
    assert ported["state_hash"] == root_hash, (ported["state_hash"], root_hash)
    assert canonical(ported["observation"]) == root_observation
    assert canonical(ported["legal_actions"]) == root_actions
    assert target.diagnostics()["reset_mode"] == "neow_run", target.diagnostics()["reset_mode"]

    return {"root_hash": root_hash, "decisions": len(trace), "trace": trace, "exported_branch_bytes": len(canonical(branch))}


def verify_fail_closed(pool: NativeWorkerPool) -> dict:
    """Unsupported input and an inexpressible forgery must fail loudly and stay quarantined."""
    seed, character, ascension, blessing = FORGERY_FIXTURE
    reset = run_start(seed, character, ascension)
    worker = pool.workers[3]
    resident = worker.neow_run_reset(reset)
    resident_hash = resident["state_hash"]
    observed: dict[str, str] = {}

    def expect(code: str, request: dict) -> None:
        try:
            worker.neow_run_reset(request)
        except NativeSimError as error:
            observed[code] = error.code
            assert error.code == code, (code, error.code, error)
            return
        raise AssertionError(f"{code}: a rejected run start was accepted")

    # Rejections the reset validates first must not disturb the resident run.
    expect("build_mismatch", {**reset, "game_build": {"assembly_sha256": "0" * 64}})
    expect("build_mismatch", {**reset, "game_build": {"version": "0.0.0-not-the-pin"}})
    expect("invalid_reset", {**reset, "ascension": 11})
    expect("invalid_reset", {**reset, "seed": ""})
    assert worker.diagnostics()["current_state_hash"] == resident_hash
    assert worker.diagnostics()["reset_mode"] == "neow_run"

    # A forged post-Neow state is not expressible: the extra fields are not part of the DTO, so the
    # run must still be the fresh character starting run and the decision must be byte-identical.
    forged = {
        **reset,
        "deck": [{"instance_id": "forged-0", "model_id": "STRIKE_IRONCLAD", "upgrades": 5}],
        "relics": [{"model_id": "WINGED_BOOTS"}],
        "potions": [{"model_id": "FIRE_POTION", "slot": 0}],
        "current_hp": 1, "max_hp": 1, "gold": 999, "rng_counters": {"Shuffle": 7},
        "initial_hand": ["forged-0"], "enemies": [{"model_id": "NIBBIT", "current_hp": 1, "max_hp": 1}],
        "use_character_starting_loadout": False,
    }
    after = worker.neow_run_reset(forged)
    assert after["state_hash"] == resident_hash, (after["state_hash"], resident_hash)
    assert canonical(after["observation"]) == canonical(resident["observation"])
    assert not any(card["model_id"] == "STRIKE_IRONCLAD" and card["upgrades"] == 5 for card in after["observation"]["run"]["deck"])
    assert after["observation"]["run"]["relics"] == resident["observation"]["run"]["relics"]
    assert after["observation"]["run"]["gold"] == resident["observation"]["run"]["gold"]

    # An unknown native model is rejected during construction rather than by validation, so it is
    # checked last; the worker must recover on the next valid run start.
    expect("unknown_model", {**reset, "character": "NOT_A_REAL_CHARACTER"})
    recovered = worker.neow_run_reset(reset)
    assert recovered["state_hash"] == resident_hash, (recovered["state_hash"], resident_hash)
    assert worker.diagnostics()["reset_mode"] == "neow_run"
    return {"rejections": observed, "forged_state_hash": after["state_hash"], "recovered_hash": recovered["state_hash"]}


def main() -> None:
    with NativeWorkerPool(4) as pool:
        hello = verify_advertised_contract(pool)
        decisions = verify_decision_determinism(pool)
        slices = verify_slice(pool)
        isolation = verify_fork_isolation(pool)
        replay = verify_replay(pool)
        fail_closed = verify_fail_closed(pool)
        print(json.dumps({
            "success": True,
            "workers": len(pool.workers),
            "game_build": pool.workers[0].build,
            "neow_run_reset_advertised": True,
            "unlock_profile": hello["run_start"]["unlock_profile"],
            "fixtures": len(FIXTURES),
            "ascension_fixture": ASCENSION_FIXTURE[0],
            "decision_hashes": decisions,
            "roots": slices,
            "fork_isolation": isolation,
            "replay": replay,
            "fail_closed": fail_closed,
            "claims": {
                "root_boundary": "combat.turn == 1 && combat.phase == Play",
                "keyframe_restore": False,
                "full_application_differential": "not evaluated here (E5)",
            },
        }, indent=2))


if __name__ == "__main__":
    main()
