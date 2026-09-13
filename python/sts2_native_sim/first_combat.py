"""First-combat root enumeration over the shipped Neow -> Act 1 lifecycle.

`docs/first-combat-scene-generation-plan.md` (E4) fixes the exportable training root at
`combat.turn == 1 && combat.phase == Play` and asks for a reusable library that enumerates the
legal Neow branches and first-combat routes and emits structured root records at exactly that
boundary. This module is that library.

Enumeration contract
--------------------

* **Only protocol legal actions are enumerated.** Every expanded node asks the worker for its
  legal actions and follows exactly those; a generated outcome that offers the player no choice
  contributes no extra branch, because there is no legal action to take.
* **Branches are identified by their action trace.** Two routes that produce the same deck,
  relics, encounter, or state hash stay separate records, because they are separate Neow
  decisions and separate map routes. Nothing is deduplicated on surface state.
* **Every node is re-driven from the run-start recipe.** A node at `trace` is produced by
  `neow_run_reset(run_start)` followed by `step(action)` for each recorded action, so no branch
  depends on a mid-tree restore, on a resident-prefix hit, or on state left behind by a sibling.
  Each root therefore carries the portable replay recipe the plan asks for: build-pinned reset
  provenance (`neow_run`), the native action history, and the expected root hash.
* **Caps are explicit and fail closed.** `EnumerationLimits` bounds actions per branch, recorded
  roots, and expanded nodes. Hitting any cap, reaching a terminal or unsupported decision, or
  finding no legal action records an `EnumerationFailure` and marks the whole seed
  `complete=False`; a truncated enumeration is never presented as a valid complete corpus.
* **Output is deterministically ordered.** Roots are sorted by action trace and failures by
  `(reason, trace, detail)`, so two enumerations of the same input produce identical branch
  identities, root hashes, action traces, and canonical uncompressed record bytes.

What this library does not claim
--------------------------------

The root record is a replay recipe, not a native memory snapshot: restoring it currently replays
the Neow prefix and cannot be described as a low-cost keyframe restore. Nothing here certifies
mechanical fidelity against `full_application_native` (E5's gate), and nothing here says anything
about policy quality. State handles are process-local and belong to the restore helpers, never to
a record.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:  # pragma: no cover - import cycle-free type hints only
    from .client import NativeWorkerPool

# Canonical record schema for one enumerated seed. Bump it when the record changes shape.
FIRST_COMBAT_RECORD_SCHEMA_VERSION = 1

# The plan's fixed root boundary. A state is a root only when both halves hold.
FIRST_COMBAT_ROOT_BOUNDARY = "combat.turn == 1 && combat.phase == Play"
ROOT_DECISION_KIND = "combat_action"

# Every run RNG stream whose counter must be observable in a root record.
COMBAT_RNG_STREAMS = (
    "Shuffle", "MonsterAi", "CombatCardGeneration", "CombatPotionGeneration",
    "CombatCardSelection", "CombatEnergyCosts", "CombatTargets", "CombatOrbs",
)

# Decision kinds the Neow -> first-combat corridor can present. `map_choice` is the post-Neow map
# decision; the choice kinds cover Neow's own options and both the nested choices it opens and the
# combat-start choices a granted relic can open (for example Gambling Chip's discard choice, which
# appears as `card_choice` while the combat is still in `Start`).
ENUMERABLE_DECISION_KINDS = frozenset({
    "event_choice", "card_choice", "option_choice", "custom_reward_choice", "neow_complete", "map_choice",
})

# Legal action kinds the corridor is allowed to follow. Anything else means the route left the
# supported Neow -> first-floor-combat corridor and must be reported, never silently traversed.
BRANCH_ACTION_KINDS = frozenset({
    "choose_event", "choose_cards", "choose_option", "choose_custom_reward", "skip_custom_rewards",
    "proceed_neow", "choose_map",
})

# Decision kinds that end the run or leave the corridor before the root.
TERMINAL_DECISION_KINDS = frozenset({
    "terminal", "map_terminal", "run_terminal", "act_transition", "event_complete", "victory", "run_won",
})

FAILURE_REASONS = frozenset({
    "action_cap", "root_cap", "expansion_cap", "no_legal_action",
    "not_at_root_boundary", "terminal_before_root", "unsupported_decision", "unsupported_action",
})

ROOT_BUILD_KEYS = ("version", "assembly_sha256", "pck_sha256")


class FirstCombatError(RuntimeError):
    """Raised when the enumeration contract itself is violated by the worker's answer."""


def canonical_json(value: Any) -> str:
    """Canonical uncompressed JSON used for record bytes and cross-worker comparison."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def run_start_request(seed: str, character: str, ascension: int, game_build: dict[str, Any] | None = None) -> dict[str, Any]:
    """The four-field run-start record `neow_run_reset` accepts; nothing else is expressible."""
    if not isinstance(seed, str) or not seed:
        raise FirstCombatError("a run start requires a non-empty seed")
    if not isinstance(character, str) or not character:
        raise FirstCombatError("a run start requires a character")
    if not isinstance(ascension, int) or isinstance(ascension, bool) or ascension < 0:
        raise FirstCombatError("a run start requires a non-negative integer ascension")
    return {"game_build": dict(game_build or {}), "seed": seed, "character": character, "ascension": ascension}


def branch_identity(seed: str, character: str, ascension: int, trace: Sequence[str]) -> str:
    """Stable branch identity derived from the run start and the ordered action trace.

    Deliberately content-free: two branches that end in the same deck, relics, encounter, or state
    hash keep distinct identities because their traces differ.
    """
    payload = canonical_json({"seed": seed, "character": character, "ascension": ascension, "trace": list(trace)})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_first_combat_root(observation: dict[str, Any]) -> bool:
    """True only for the plan's exact boundary, read from the native combat state."""
    decision = observation.get("decision") or {}
    combat = observation.get("combat") or {}
    return (
        decision.get("kind") == ROOT_DECISION_KIND
        and combat.get("turn") == 1
        and combat.get("phase") == "Play"
    )


def assert_first_combat_root(state: dict[str, Any], label: str = "first-combat root") -> dict[str, Any]:
    """Fail loudly unless `state` is the boundary with the provenance a root record must carry."""
    observation = state.get("observation") or {}
    decision = observation.get("decision") or {}
    combat = observation.get("combat") or {}
    if decision.get("kind") != ROOT_DECISION_KIND:
        raise FirstCombatError(f"{label} is a '{decision.get('kind')}' decision, not a combat decision")
    if combat.get("turn") != 1 or combat.get("phase") != "Play":
        raise FirstCombatError(
            f"{label} is not at {FIRST_COMBAT_ROOT_BOUNDARY}: turn={combat.get('turn')!r} phase={combat.get('phase')!r}"
        )
    actions = state.get("legal_actions") or []
    kinds = {action.get("kind") for action in actions}
    missing = {"play_card", "end_turn"} - kinds
    if missing:
        raise FirstCombatError(f"{label} is missing the combat legal actions {sorted(missing)}")
    run = observation.get("run") or {}
    counters = run.get("rng_counters")
    if not isinstance(counters, dict) or not counters:
        raise FirstCombatError(f"{label} lost the complete run RNG counter map")
    build = observation.get("game_build") or {}
    absent = [key for key in ROOT_BUILD_KEYS if not build.get(key)]
    if absent:
        raise FirstCombatError(f"{label} lost the build identity fields {absent}")
    return observation


def root_enemies(observation: dict[str, Any]) -> list[dict[str, Any]]:
    """The enemy side of the root combat state as a stable, canonical encounter identity."""
    combat = observation.get("combat") or {}
    enemies = [
        {"model_id": creature.get("model_id"), "hp": creature.get("hp"), "max_hp": creature.get("max_hp")}
        for creature in combat.get("creatures") or []
        if isinstance(creature, dict) and creature.get("side") == "Enemy"
    ]
    return sorted(enemies, key=lambda enemy: (str(enemy["model_id"]), -1 if enemy["hp"] is None else enemy["hp"]))


def assert_root_equivalent(record: "RootRecord", state: dict[str, Any], label: str = "restored root") -> None:
    """Fail loudly unless a replayed or restored state matches a record hash, observation, actions."""
    if state.get("state_hash") != record.root_hash:
        raise FirstCombatError(f"{label} hash {state.get('state_hash')} does not match the recorded root {record.root_hash}")
    if canonical_json(state.get("observation")) != canonical_json(record.observation):
        raise FirstCombatError(f"{label} observation does not match the recorded root observation")
    if canonical_json(state.get("legal_actions")) != canonical_json(record.legal_actions):
        raise FirstCombatError(f"{label} legal actions do not match the recorded root legal actions")


@dataclass(frozen=True)
class EnumerationLimits:
    """Explicit caps. Reaching one records a failure and marks the seed incomplete."""

    max_actions_per_branch: int = 16
    max_roots: int = 512
    max_expansions: int = 1024

    def __post_init__(self) -> None:
        for name in ("max_actions_per_branch", "max_roots", "max_expansions"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise FirstCombatError(f"EnumerationLimits.{name} must be a positive integer")

    def as_record(self) -> dict[str, int]:
        return {
            "max_actions_per_branch": self.max_actions_per_branch,
            "max_roots": self.max_roots,
            "max_expansions": self.max_expansions,
        }


DEFAULT_LIMITS = EnumerationLimits()


@dataclass(frozen=True)
class EnumerationFailure:
    """One path the enumeration could not carry to the root boundary."""

    reason: str
    trace: tuple[str, ...]
    detail: str

    def as_record(self) -> dict[str, Any]:
        return {"reason": self.reason, "trace": list(self.trace), "detail": self.detail}


@dataclass(frozen=True)
class RootRecord:
    """One structured first-combat root record at `combat.turn == 1 && combat.phase == Play`."""

    seed: str
    character: str
    ascension: int
    branch_id: str
    run_start: dict[str, Any]
    trace: tuple[str, ...]
    action_kinds: tuple[str, ...]
    route: dict[str, Any]
    root_hash: str
    game_build: dict[str, Any]
    run_rng_counters: dict[str, int]
    legal_actions: list[dict[str, Any]]
    observation: dict[str, Any]
    portable_branch: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "character": self.character,
            "ascension": self.ascension,
            "branch_id": self.branch_id,
            "run_start": dict(self.run_start),
            "trace": list(self.trace),
            "action_kinds": list(self.action_kinds),
            "route": dict(self.route),
            "root_hash": self.root_hash,
            "game_build": dict(self.game_build),
            "run_rng_counters": dict(self.run_rng_counters),
            "legal_actions": list(self.legal_actions),
            "observation": self.observation,
            "portable_branch": self.portable_branch,
        }


@dataclass(frozen=True)
class SeedEnumeration:
    """The complete enumeration of one `seed + character + ascension` run start."""

    seed: str
    character: str
    ascension: int
    run_start: dict[str, Any]
    game_build: dict[str, Any]
    limits: EnumerationLimits
    neow_decision: dict[str, Any]
    expansions: int
    roots: tuple[RootRecord, ...]
    failures: tuple[EnumerationFailure, ...]

    @property
    def complete(self) -> bool:
        """A seed is complete only when no path failed and no cap truncated the walk."""
        return not self.failures

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": FIRST_COMBAT_RECORD_SCHEMA_VERSION,
            "seed": self.seed,
            "character": self.character,
            "ascension": self.ascension,
            "run_start": dict(self.run_start),
            "game_build": dict(self.game_build),
            "limits": self.limits.as_record(),
            "neow_decision": self.neow_decision,
            "expansions": self.expansions,
            "complete": self.complete,
            "roots": [root.as_record() for root in self.roots],
            "failures": [failure.as_record() for failure in self.failures],
        }

    def canonical_json(self) -> str:
        return canonical_json(self.as_record())

    def canonical_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")

    def assert_complete(self) -> None:
        """Fail loudly when a caller requires complete coverage and the walk was truncated."""
        if not self.complete:
            reasons = sorted({failure.reason for failure in self.failures})
            raise FirstCombatError(
                f"{self.seed}|{self.character}|A{self.ascension} enumeration is incomplete: {reasons}"
            )


def _neow_decision_record(state: dict[str, Any]) -> dict[str, Any]:
    """The Neow decision's own provenance, kept alongside the roots for the corpus path record."""
    observation = state.get("observation") or {}
    event = observation.get("event") or {}
    return {
        "decision_kind": (observation.get("decision") or {}).get("kind"),
        "state_hash": state.get("state_hash"),
        "model_id": event.get("model_id"),
        "options": list(event.get("options") or []),
        "run_start": observation.get("run_start"),
    }


class FirstCombatEnumerator:
    """Enumerates every legal Neow branch and first-combat route for one run start.

    The worker is used through three calls only -- `neow_run_reset`, `step`, and `export_branch` --
    so any object with that protocol drives the walk. Each expanded node is re-driven from the
    run-start recipe rather than restored from a sibling's state, which keeps branches mutually
    independent and makes every root a genuine replay recipe.
    """

    def __init__(self, worker: Any, limits: EnumerationLimits | None = None):
        self.worker = worker
        self.limits = limits or DEFAULT_LIMITS

    def enumerate(
        self,
        seed: str,
        character: str,
        ascension: int,
        game_build: dict[str, Any] | None = None,
    ) -> SeedEnumeration:
        limits = self.limits
        run_start = run_start_request(seed, character, ascension, game_build)
        initial = self.worker.neow_run_reset(run_start)
        neow_decision = _neow_decision_record(initial)
        if neow_decision["model_id"] != "NEOW":
            raise FirstCombatError(
                f"{seed}|{character}|A{ascension} run start did not open the native NEOW event: {neow_decision['model_id']!r}"
            )
        roots: list[RootRecord] = []
        failures: list[EnumerationFailure] = []
        expansions = 0

        def redrive(trace: tuple[str, ...]) -> dict[str, Any]:
            current = self.worker.neow_run_reset(run_start)
            for action_id in trace:
                current = self.worker.step(action_id)
            return current

        def fail(reason: str, trace: tuple[str, ...], detail: str) -> None:
            if reason not in FAILURE_REASONS:
                raise FirstCombatError(f"unknown enumeration failure reason {reason!r}")
            failures.append(EnumerationFailure(reason=reason, trace=trace, detail=detail))

        def root_record(
            trace: tuple[str, ...],
            action_kinds: tuple[str, ...],
            state: dict[str, Any],
            map_action: dict[str, Any],
        ) -> RootRecord:
            observation = assert_first_combat_root(state, label=f"root {list(trace)}")
            branch = self.worker.export_branch()
            if branch.get("provenance") != "neow_run":
                raise FirstCombatError(f"exported root branch has provenance {branch.get('provenance')!r}, not 'neow_run'")
            if list(branch.get("history") or []) != list(trace):
                raise FirstCombatError("the exported root branch history does not match the enumerated action trace")
            if branch.get("expected_hash") != state["state_hash"]:
                raise FirstCombatError("the exported root branch expected hash does not match the root state hash")
            parameters = map_action.get("parameters") or {}
            run = observation.get("run") or {}
            return RootRecord(
                seed=seed,
                character=character,
                ascension=ascension,
                branch_id=branch_identity(seed, character, ascension, trace),
                run_start=dict(run_start),
                trace=trace,
                action_kinds=action_kinds,
                route={
                    "coord": {"col": parameters.get("col"), "row": parameters.get("row")},
                    "point_type": parameters.get("point_type"),
                    "enemies": root_enemies(observation),
                },
                root_hash=state["state_hash"],
                game_build=dict(observation.get("game_build") or {}),
                run_rng_counters=dict(run.get("rng_counters") or {}),
                legal_actions=list(state.get("legal_actions") or []),
                observation=observation,
                portable_branch=branch,
            )

        def expand(
            trace: tuple[str, ...],
            action_kinds: tuple[str, ...],
            current: dict[str, Any],
            map_action: dict[str, Any] | None,
        ) -> None:
            nonlocal expansions
            expansions += 1
            observation = current.get("observation") or {}
            decision = observation.get("decision") or {}
            kind = decision.get("kind")
            if kind == ROOT_DECISION_KIND:
                if is_first_combat_root(observation):
                    if map_action is None:
                        raise FirstCombatError(
                            f"the root reached by {list(trace)} did not pass through a first-floor map action; "
                            "the Neow -> first-combat corridor contract needs re-planning"
                        )
                    roots.append(root_record(trace, action_kinds, current, map_action))
                else:
                    combat = observation.get("combat") or {}
                    fail("not_at_root_boundary", trace, f"turn={combat.get('turn')!r} phase={combat.get('phase')!r}")
                return
            if kind in TERMINAL_DECISION_KINDS:
                fail("terminal_before_root", trace, str(kind))
                return
            if kind not in ENUMERABLE_DECISION_KINDS:
                fail("unsupported_decision", trace, repr(kind))
                return
            actions = current.get("legal_actions") or []
            if not actions:
                fail("no_legal_action", trace, str(kind))
                return
            unsupported = sorted({str(action.get("kind")) for action in actions if action.get("kind") not in BRANCH_ACTION_KINDS})
            if unsupported:
                fail("unsupported_action", trace, f"{kind} offered {unsupported}")
                return
            if len(trace) >= limits.max_actions_per_branch:
                fail("action_cap", trace, f"{len(trace)} actions without reaching {FIRST_COMBAT_ROOT_BOUNDARY}")
                return
            for index, action in enumerate(actions):
                if len(roots) >= limits.max_roots:
                    fail("root_cap", trace, f"{len(roots)} roots recorded; {len(actions) - index} legal action(s) left at this node")
                    return
                if expansions >= limits.max_expansions:
                    fail("expansion_cap", trace, f"{expansions} decision nodes expanded")
                    return
                if index:
                    current = redrive(trace)
                action_id = str(action["action_id"])
                action_kind = str(action.get("kind"))
                child_map_action = action if action_kind == "choose_map" else map_action
                child = self.worker.step(action_id)
                expand(trace + (action_id,), action_kinds + (action_kind,), child, child_map_action)

        expand((), (), initial, None)

        ordered_roots = tuple(sorted(roots, key=lambda root: root.trace))
        ordered_failures = tuple(sorted(failures, key=lambda failure: (failure.reason, failure.trace, failure.detail)))
        if len(ordered_roots) > limits.max_roots:
            raise FirstCombatError(f"enumeration recorded {len(ordered_roots)} roots beyond the cap {limits.max_roots}")
        game_build_record = ordered_roots[0].game_build if ordered_roots else (initial.get("observation") or {}).get("game_build") or {}
        return SeedEnumeration(
            seed=seed,
            character=character,
            ascension=ascension,
            run_start=run_start,
            game_build=dict(game_build_record),
            limits=limits,
            neow_decision=neow_decision,
            expansions=expansions,
            roots=ordered_roots,
            failures=ordered_failures,
        )


def enumerate_first_combat_roots(
    worker: Any,
    seed: str,
    character: str,
    ascension: int,
    limits: EnumerationLimits | None = None,
    game_build: dict[str, Any] | None = None,
) -> SeedEnumeration:
    """Convenience wrapper around `FirstCombatEnumerator.enumerate`."""
    return FirstCombatEnumerator(worker, limits).enumerate(seed, character, ascension, game_build)


def replay_first_combat_root(worker: Any, record: RootRecord) -> dict[str, Any]:
    """Rebuild one root from its recorded recipe on a worker and check the boundary.

    This is the honest reconstruction path the record describes: the same build-pinned run start,
    then the recorded native actions in order. It asserts the exact boundary and equivalence with
    the recorded hash, observation, and legal actions.
    """
    state = worker.neow_run_reset(record.run_start)
    for action_id in record.trace:
        state = worker.step(action_id)
    assert_first_combat_root(state, label=f"replayed root {record.branch_id}")
    assert_root_equivalent(record, state, label="replayed root")
    return state


def restore_first_combat_root(worker: Any, record: RootRecord, move_action: str | None = None) -> dict[str, Any]:
    """Move the worker off its resident root, then rebuild the root from its recorded handle.

    The move is required so the restore is a real reconstruction: a resident-prefix hit would prove
    nothing. The handle is taken from this worker's own replay of the recipe rather than from the
    record, because a handle is process-local and must never cross a worker boundary. The returned
    evidence carries the worker's own restore audit, so a caller can check the `replay` path and a
    positive replayed-action count instead of trusting the transition label.
    """
    if move_action is None:
        end_turn = next((action for action in record.legal_actions if action.get("kind") == "end_turn"), None)
        if end_turn is None:
            raise FirstCombatError(f"root {record.branch_id} exposes no end_turn action to move the worker away with")
        move_action = str(end_turn["action_id"])
    current = replay_first_combat_root(worker, record)
    handle = current.get("state_handle")
    if handle is None:
        raise FirstCombatError(f"worker returned no state handle for root {record.branch_id}")
    moved = worker.step(move_action)
    if moved.get("state_hash") == record.root_hash:
        raise FirstCombatError(f"the move action '{move_action}' did not change the root state; the restore is not evidence")
    restored = worker.restore(handle)
    assert_root_equivalent(record, restored, label="fork-restored root")
    audit = (worker.diagnostics() or {}).get("last_restore") or {}
    if audit.get("path") != "replay":
        raise FirstCombatError(f"fork-restored root took the '{audit.get('path')}' path instead of a real replay")
    if audit.get("replayed_actions") != len(record.trace):
        raise FirstCombatError(
            f"fork-restored root replayed {audit.get('replayed_actions')} actions, expected {len(record.trace)}"
        )
    if audit.get("synthetic_combat_installed") is not False:
        raise FirstCombatError("fork-restored root installed a synthetic combat")
    return {"state": restored, "audit": audit, "move_action": move_action}


def portable_restore_first_combat_root(pool: NativeWorkerPool, worker_index: int, record: RootRecord) -> dict[str, Any]:
    """Restore one root on another worker from its portable branch and verify the expected hash.

    `NativeWorkerPool.restore_portable` already fails closed on a build mismatch or a replay
    divergence; this adds the record-level equivalence check so the evidence covers the whole
    observation and legal-action set, not only the state hash.
    """
    restored = pool.restore_portable(worker_index, record.portable_branch)
    assert_root_equivalent(record, restored, label="portable-restored root")
    worker = pool.workers[worker_index]
    if getattr(worker, "reset_mode", None) != "neow_run":
        raise FirstCombatError(f"portable restore left the worker in provenance {getattr(worker, 'reset_mode', None)!r}")
    return restored
