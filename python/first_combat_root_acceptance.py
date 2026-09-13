"""E4 root gate: enumerate every legal Neow branch and first-combat route on four workers.

For each fixture (`seed` + `character` + `ascension`) the library must enumerate every legal Neow
option, every nested native choice it opens, and every legal first-floor map action that natively
enters combat, and emit one structured root record per branch at exactly
`combat.turn == 1 && combat.phase == Play`. This script verifies the plan's E4 gate:

* the advertised protocol still carries the corridor and the run-start RPC;
* two enumerations of the same input -- on different workers and twice on the same worker --
  produce identical branch identities, root hashes, action traces, and canonical uncompressed
  record bytes;
* every recorded root is a real boundary state with combat legal actions, the complete run RNG
  counter map, build identity, a first-floor `Monster` route, its enemies, and a portable replay
  recipe (`neow_run` provenance, the recorded trace as history, the root hash as expected hash);
* same-worker replay, local fork restore, and cross-worker portable restore all reproduce the same
  hash, observation, and legal actions. The restore evidence is the worker's own audit: a `replay`
  path with a positive replayed-action count, not a resident-prefix no-op;
* branches that share a state hash stay separate records, so nothing is deduplicated on surface
  state;
* explicit caps fail closed: a truncated enumeration is marked incomplete and never presented as a
  complete corpus, and a root emitted under a cap is still a real boundary state;
* a tampered portable branch fails closed on its expected hash, poisoning only the worker that
  attempted it; the pool replaces that worker and the untampered recipe restores on it, so the
  tamper is the only cause.

Claim boundary: this is the root gate only. It does not certify `full_application_native`
(F5/E5's differential), does not prove keyframe or low-cost restore, and says nothing about policy
quality. The fixtures are single Act 1 samples, so they cannot distinguish `MapTravel` from plain
child enumeration at the starting Ancient point.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sts2_native_sim import (
    BRANCH_ACTION_KINDS,
    FIRST_COMBAT_ROOT_BOUNDARY,
    COMBAT_RNG_STREAMS,
    EnumerationLimits,
    FirstCombatError,
    NativeSimError,
    NativeWorkerPool,
    assert_first_combat_root,
    branch_identity,
    enumerate_first_combat_roots,
    is_first_combat_root,
    portable_restore_first_combat_root,
    replay_first_combat_root,
    restore_first_combat_root,
    run_start_request,
)

# The plan's E4 fixtures: the seven high-risk blessings plus A10. The seeds are the E3 fixtures,
# so the named blessing each one offers is already build-pinned; this script re-asserts it, so a
# build whose Neow roll changes fails loudly instead of silently testing another blessing.
FIXTURES = (
    ("NEOWSWEEP0000", "IRONCLAD", 0, "LARGE_CAPSULE"),
    ("NEOWSWEEP0001", "IRONCLAD", 0, "PHIAL_HOLSTER"),
    ("NEOWSWEEP0019", "IRONCLAD", 0, "SMALL_CAPSULE"),
    ("NEOWSWEEP0015", "IRONCLAD", 0, "NEW_LEAF"),
    ("NEOWSWEEP0006", "IRONCLAD", 0, "LEAFY_POULTICE"),
    ("NEOWSWEEP0007", "IRONCLAD", 0, "SCROLL_BOXES"),
    ("NEOWSWEEP0013", "IRONCLAD", 0, "NEOWS_BONES"),
    ("NEOWSWEEP0007", "IRONCLAD", 10, "SCROLL_BOXES"),
)
# One non-Ironclad run start, enumerated once, as engine-level breadth for a character-agnostic
# library. It is not one of the plan's named fixtures and carries no extra claim.
BREADTH_FIXTURES = (("NEOWSWEEP0006", "DEFECT", 0, "WINGED_BOOTS"),)

LIMITS = EnumerationLimits(max_actions_per_branch=16, max_roots=512, max_expansions=1024)
VERIFY_SAMPLE = 4


def fixture_key(fixture: tuple[str, str, int, str]) -> str:
    seed, character, ascension, blessing = fixture
    return f"{seed}|{character}|A{ascension}|{blessing}"


def digest(enumeration) -> str:
    return hashlib.sha256(enumeration.canonical_bytes()).hexdigest()


def verify_advertised_contract(pool: NativeWorkerPool) -> dict:
    hello = pool.workers[0].hello()
    assert "neow_run_reset" in hello["methods"], hello["methods"]
    assert hello["run_start"]["method"] == "neow_run_reset", hello["run_start"]
    assert hello["run_start"]["unlock_profile"] == "unlock_state_all", hello["run_start"]
    supported = set(hello["supported_subset"]["actions"])
    missing = sorted(BRANCH_ACTION_KINDS - supported)
    assert not missing, f"the enumeration corridor uses action kinds the protocol does not advertise: {missing}"
    return hello


def enumerate_fixture(worker, fixture: tuple[str, str, int, str], limits: EnumerationLimits = LIMITS):
    seed, character, ascension, _ = fixture
    return enumerate_first_combat_roots(worker, seed, character, ascension, limits)


def enumerate_in_parallel(pool: NativeWorkerPool, fixtures, offset: int, limits: EnumerationLimits = LIMITS) -> dict:
    """Enumerate each fixture once, spreading the batch across workers with a rotation offset.

    Fixture `start + i` goes to worker `(start + i + offset) % n`, so running the same fixture list
    with two different offsets makes every fixture compared across two different workers even when
    the last batch is smaller than the worker count.
    """
    workers = len(pool.workers)
    results: dict[str, tuple[int, object]] = {}
    for start in range(0, len(fixtures), workers):
        chunk = fixtures[start:start + workers]
        values: list = [None] * workers
        for index, fixture in enumerate(chunk):
            values[(start + index + offset) % workers] = fixture
        enumerated = pool.map(
            lambda worker, fixture: enumerate_fixture(worker, fixture, limits) if fixture else None,
            values,
        )
        for index, fixture in enumerate(chunk):
            worker_index = (start + index + offset) % workers
            results[fixture_key(fixture)] = (worker_index, enumerated[worker_index])
    return results


def check_root_gate(fixture: tuple[str, str, int, str], enumeration) -> dict:
    """Every recorded root must be a real boundary state with complete provenance."""
    seed, character, ascension, blessing = fixture
    key = fixture_key(fixture)
    assert enumeration.complete, (key, [failure.as_record() for failure in enumeration.failures])
    enumeration.assert_complete()
    assert enumeration.roots, f"{key} produced no first-combat root"

    offered = {option["text_key"].rsplit(".", 1)[-1] for option in enumeration.neow_decision["options"]}
    assert blessing in offered, f"{key} did not offer {blessing}; offered {sorted(offered)}"
    run_start = enumeration.neow_decision["run_start"]
    assert run_start["unlock_profile"] == "unlock_state_all", run_start
    assert run_start["started_with_neow"] is True, run_start
    assert run_start["starting_point_type"] == "Ancient", run_start
    assert set(run_start["first_floor_types"]) == {"Monster"}, run_start

    traces, identities = set(), set()
    for root in enumeration.roots:
        label = f"{key} {root.branch_id[:12]}"
        assert root.trace not in traces, f"{label} repeats an action trace"
        traces.add(root.trace)
        assert root.branch_id == branch_identity(seed, character, ascension, root.trace), label
        assert root.branch_id not in identities, label
        identities.add(root.branch_id)

        observation = assert_first_combat_root(
            {"observation": root.observation, "legal_actions": root.legal_actions}, label
        )
        assert is_first_combat_root(observation), label
        assert observation["combat"]["turn"] == 1 and observation["combat"]["phase"] == "Play", label
        kinds = {action["kind"] for action in root.legal_actions}
        assert {"play_card", "end_turn"} <= kinds, (label, sorted(kinds))

        missing_counters = sorted(set(COMBAT_RNG_STREAMS) - set(root.run_rng_counters))
        assert not missing_counters, f"{label} lost run RNG streams {missing_counters}"
        assert root.game_build == enumeration.game_build, label
        assert root.game_build["assembly_sha256"], label

        assert root.route["point_type"] == "Monster", (label, root.route)
        assert root.route["coord"]["row"] == 1, (label, root.route)
        assert isinstance(root.route["coord"]["col"], int), (label, root.route)
        assert root.route["enemies"] and all(enemy["model_id"] for enemy in root.route["enemies"]), (label, root.route)

        assert root.run_start == enumeration.run_start, label
        branch = root.portable_branch
        assert branch["schema_version"] == 1, label
        assert branch["provenance"] == "neow_run", (label, branch["provenance"])
        assert branch["history"] == list(root.trace), label
        assert branch["expected_hash"] == root.root_hash, label
        assert branch["reset_request"]["method"] == "neow_run_reset", label
        assert set(branch["reset_request"]["params"]) == {"game_build", "seed", "character", "ascension"}, label
        assert branch["game_build"] == enumeration.game_build, label

    return {
        "roots": len(enumeration.roots),
        "expansions": enumeration.expansions,
        "distinct_root_hashes": len({root.root_hash for root in enumeration.roots}),
        "distinct_branch_ids": len(identities),
        "branch_lengths": sorted({len(root.trace) for root in enumeration.roots}),
        "action_kind_paths": sorted({root.action_kinds for root in enumeration.roots}),
        "canonical_sha256": digest(enumeration),
        "sample_traces": [list(root.trace) for root in enumeration.roots[:2]],
    }


def sample_roots(roots, limit: int = VERIFY_SAMPLE):
    """A deterministic spread of roots, so the three reconstruction paths are not all on one edge."""
    if len(roots) <= limit:
        return list(roots)
    stride = max(1, len(roots) // limit)
    return list(roots[::stride])[:limit]


def verify_reconstruction_paths(pool: NativeWorkerPool, fixture, worker_index: int, enumeration) -> dict:
    """Same-worker replay, local fork restore, and cross-worker portable restore on sampled roots."""
    key = fixture_key(fixture)
    worker = pool.workers[worker_index]
    portable_index = (worker_index + 1) % len(pool.workers)
    audit: dict | None = None
    verified = 0
    for root in sample_roots(enumeration.roots):
        replayed = replay_first_combat_root(worker, root)
        assert replayed["state_hash"] == root.root_hash, key
        restored = restore_first_combat_root(worker, root)
        audit = restored["audit"]
        assert audit["path"] == "replay", (key, audit)
        assert audit["replayed_actions"] == len(root.trace) > 0, (key, audit, root.trace)
        assert audit["synthetic_combat_installed"] is False, (key, audit)
        ported = portable_restore_first_combat_root(pool, portable_index, root)
        assert ported["state_hash"] == root.root_hash, key
        verified += 1
    return {"sampled_roots": verified, "restore_audit": audit, "portable_worker": portable_index}


def verify_caps(worker, fixture) -> dict:
    """A capped enumeration must fail closed and must not present truncated results as complete."""
    seed, character, ascension, _ = fixture
    key = fixture_key(fixture)
    full = enumerate_fixture(worker, fixture)
    assert full.complete, key

    depth_capped = enumerate_first_combat_roots(
        worker, seed, character, ascension, EnumerationLimits(max_actions_per_branch=1, max_roots=512, max_expansions=1024)
    )
    assert depth_capped.complete is False, key
    assert "action_cap" in {failure.reason for failure in depth_capped.failures}, key
    try:
        depth_capped.assert_complete()
    except FirstCombatError:
        pass
    else:
        raise AssertionError(f"{key} accepted a depth-capped enumeration as complete")

    root_capped = enumerate_first_combat_roots(
        worker, seed, character, ascension, EnumerationLimits(max_actions_per_branch=16, max_roots=2, max_expansions=1024)
    )
    assert root_capped.complete is False, key
    assert "root_cap" in {failure.reason for failure in root_capped.failures}, key
    assert len(root_capped.roots) == 2 < len(full.roots), (key, len(root_capped.roots), len(full.roots))
    for root in root_capped.roots:
        # A capped walk may stop early, but every root it does emit must still be a real boundary.
        assert_first_combat_root({"observation": root.observation, "legal_actions": root.legal_actions}, key)

    return {
        "full_roots": len(full.roots),
        "depth_capped": [failure.as_record() for failure in depth_capped.failures][:2],
        "root_capped": [failure.as_record() for failure in root_capped.failures][:2],
        "root_capped_roots": len(root_capped.roots),
    }


def verify_boundary_discrimination(worker, fixture) -> dict:
    """The root gate must reject the Neow decision state it is not supposed to export."""
    seed, character, ascension, _ = fixture
    key = fixture_key(fixture)
    state = worker.neow_run_reset(run_start_request(seed, character, ascension))
    assert is_first_combat_root(state["observation"]) is False, key
    try:
        assert_first_combat_root(state, key)
    except FirstCombatError as error:
        reason = str(error)
    else:
        raise AssertionError(f"{key} accepted the Neow decision state as a first-combat root")
    return {"rejected": reason, "neow_decision_hash": state["state_hash"]}


def verify_tampered_branch(pool: NativeWorkerPool, fixture, worker_index: int, enumeration) -> dict:
    """A tampered replay recipe must fail closed on its hash before the record can be trusted."""
    root = enumeration.roots[0]
    target = (worker_index + 1) % len(pool.workers)
    tampered = copy.deepcopy(root.portable_branch)
    tampered["expected_hash"] = "0" * 64
    try:
        pool.restore_portable(target, tampered)
    except NativeSimError as error:
        assert error.code == "replay_divergence", (error.code, error)
    else:
        raise AssertionError(f"{fixture_key(fixture)} accepted a tampered expected hash")
    # The rejected replay poisons its worker, exactly as the protocol says; the pool must replace it
    # and the untampered recipe must still restore, which also proves the tamper was the only cause.
    recovered = portable_restore_first_combat_root(pool, target, root)
    return {"rejected_code": "replay_divergence", "recovered_hash": recovered["state_hash"]}


def main() -> None:
    with NativeWorkerPool(4) as pool:
        hello = verify_advertised_contract(pool)
        fixtures = FIXTURES + BREADTH_FIXTURES

        first = enumerate_in_parallel(pool, fixtures, offset=0)
        second = enumerate_in_parallel(pool, fixtures, offset=1)

        gate_evidence: dict[str, dict] = {}
        for fixture in fixtures:
            key = fixture_key(fixture)
            gate_evidence[key] = check_root_gate(fixture, first[key][1])

        # Same input, same result: identical bytes across two different workers...
        determinism = {}
        for fixture in fixtures:
            key = fixture_key(fixture)
            first_worker, first_enumeration = first[key]
            second_worker, second_enumeration = second[key]
            assert first_worker != second_worker, (key, first_worker)
            assert first_enumeration.canonical_bytes() == second_enumeration.canonical_bytes(), key
            assert [root.branch_id for root in first_enumeration.roots] == [root.branch_id for root in second_enumeration.roots], key
            assert [root.root_hash for root in first_enumeration.roots] == [root.root_hash for root in second_enumeration.roots], key
            assert [root.trace for root in first_enumeration.roots] == [root.trace for root in second_enumeration.roots], key
            determinism[key] = {
                "workers": [first_worker, second_worker],
                "canonical_sha256": digest(first_enumeration),
            }

        # ...and twice on the same worker.
        repeat_fixture = FIXTURES[0]
        repeat_worker = first[fixture_key(repeat_fixture)][0]
        repeat_first = enumerate_fixture(pool.workers[repeat_worker], repeat_fixture)
        repeat_second = enumerate_fixture(pool.workers[repeat_worker], repeat_fixture)
        assert repeat_first.canonical_bytes() == repeat_second.canonical_bytes(), repeat_fixture
        assert repeat_first.canonical_bytes() == first[fixture_key(repeat_fixture)][1].canonical_bytes(), repeat_fixture

        # Branches sharing a state hash must survive as separate records somewhere in the fixture set.
        content_duplicates = {
            key: {"roots": evidence["roots"], "distinct_root_hashes": evidence["distinct_root_hashes"]}
            for key, evidence in gate_evidence.items()
            if evidence["distinct_root_hashes"] < evidence["roots"]
        }
        assert content_duplicates, "no fixture produced branches sharing a state hash; the no-dedupe check proved nothing"

        paths = {
            fixture_key(fixture): verify_reconstruction_paths(pool, fixture, first[fixture_key(fixture)][0], first[fixture_key(fixture)][1])
            for fixture in fixtures
        }
        caps = verify_caps(pool.workers[0], FIXTURES[1])
        discrimination = verify_boundary_discrimination(pool.workers[0], FIXTURES[1])
        tamper = verify_tampered_branch(pool, FIXTURES[1], first[fixture_key(FIXTURES[1])][0], first[fixture_key(FIXTURES[1])][1])

        print(json.dumps({
            "success": True,
            "workers": len(pool.workers),
            "game_build": pool.workers[0].build,
            "unlock_profile": hello["run_start"]["unlock_profile"],
            "fixtures": len(FIXTURES),
            "breadth_fixtures": len(BREADTH_FIXTURES),
            "limits": LIMITS.as_record(),
            "roots": {key: evidence["roots"] for key, evidence in gate_evidence.items()},
            "gate": gate_evidence,
            "determinism": determinism,
            "same_worker_repeat": fixture_key(repeat_fixture),
            "content_duplicates_kept": content_duplicates,
            "reconstruction_paths": paths,
            "caps": caps,
            "boundary_discrimination": discrimination,
            "tampered_branch": tamper,
            "claims": {
                "root_boundary": FIRST_COMBAT_ROOT_BOUNDARY,
                "keyframe_restore": False,
                "full_application_differential": "not evaluated here (E5)",
            },
        }, indent=2))


if __name__ == "__main__":
    main()
