from .client import NativeSimError, NativeWorker, NativeWorkerPool
from .first_combat import (
    BRANCH_ACTION_KINDS,
    COMBAT_RNG_STREAMS,
    DEFAULT_LIMITS,
    ENUMERABLE_DECISION_KINDS,
    FAILURE_REASONS,
    FIRST_COMBAT_RECORD_SCHEMA_VERSION,
    FIRST_COMBAT_ROOT_BOUNDARY,
    EnumerationFailure,
    EnumerationLimits,
    FirstCombatEnumerator,
    FirstCombatError,
    RootRecord,
    SeedEnumeration,
    assert_first_combat_root,
    assert_root_equivalent,
    branch_identity,
    enumerate_first_combat_roots,
    is_first_combat_root,
    portable_restore_first_combat_root,
    replay_first_combat_root,
    restore_first_combat_root,
    run_start_request,
)
from .search import NativeSearchCoordinator
from .scoring import FEATURE_NAMES, NativeObservedMaterialScorer, NativeTorchValueScorer, encode_scoring_features
from .paths import DiscoveryError, find_game_assembly, find_game_root, find_godot
from .observations import extract_agent_observation, to_agent_observation
try:
    from .gym import Sts2NativeVectorEnv
except ImportError:
    Sts2NativeVectorEnv = None  # type: ignore

__all__ = [
    "NativeSimError",
    "NativeWorker",
    "NativeWorkerPool",
    "NativeSearchCoordinator",
    "FEATURE_NAMES",
    "NativeObservedMaterialScorer",
    "NativeTorchValueScorer",
    "encode_scoring_features",
    "DiscoveryError",
    "find_game_assembly",
    "find_game_root",
    "find_godot",
    "extract_agent_observation",
    "project_player_visible_card_state",
    "to_agent_observation",
    "Sts2NativeVectorEnv",
    "BRANCH_ACTION_KINDS",
    "COMBAT_RNG_STREAMS",
    "DEFAULT_LIMITS",
    "ENUMERABLE_DECISION_KINDS",
    "FAILURE_REASONS",
    "FIRST_COMBAT_RECORD_SCHEMA_VERSION",
    "FIRST_COMBAT_ROOT_BOUNDARY",
    "EnumerationFailure",
    "EnumerationLimits",
    "FirstCombatEnumerator",
    "FirstCombatError",
    "RootRecord",
    "SeedEnumeration",
    "assert_first_combat_root",
    "assert_root_equivalent",
    "branch_identity",
    "enumerate_first_combat_roots",
    "is_first_combat_root",
    "portable_restore_first_combat_root",
    "replay_first_combat_root",
    "restore_first_combat_root",
    "run_start_request",
]
