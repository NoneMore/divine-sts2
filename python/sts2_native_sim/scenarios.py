"""Public Generated scenario, materialization, and corpus interfaces.

Implementation is split by responsibility across private scenario modules. This facade keeps the
established import surface stable while the mechanics remain implementation details.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._scenario_codec import encode_row, error_kind, summarize_rows
from ._scenario_corpus import generate_corpus as _generate_corpus
from ._scenario_driver import CombatEpisode, materialize_scenario
from ._scenario_generation import generate_rows
from ._scenario_model import (
    ANCIENT_CHOICE_KEY_ORDER,
    COMBAT_ACTION,
    CORPUS_SCHEMA,
    ERROR_KEY_ORDER,
    ERROR_RUN,
    FAILURE_RECORD,
    NESTED_CHOICE_KEY_ORDER,
    NODE_KEY_ORDER,
    RECIPE_KEY_ORDER,
    REQUEST_KEY_ORDER,
    ROW_ENCODING,
    ROW_ESCAPE_NON_ASCII,
    ROW_KEY_ORDER,
    ROW_SCHEMA,
    ROW_SEPARATORS,
    ROW_TYPES,
    SCENARIO_RECORD,
    SHARD_GZIP_MTIME,
    SHARD_GZIP_NAME,
    SHARD_KEY_ORDER,
    STAGE_ANCIENT_CHOICE,
    STAGE_ANCIENT_ROOM,
    STAGE_FIRST_COMBAT,
    STAGE_LEAVE_ANCIENT,
    STAGE_RECORD,
    STAGE_ROW_ONE_NODE,
    STAGE_RUN_START,
    SUMMARY_FILE,
    SUMMARY_KEY_ORDER,
    SUMMARY_SEPARATORS,
    CorpusConflictError,
    CorpusWorker,
    RowFormatError,
    RunWorker,
    ScenarioGenerationError,
    ScenarioMaterializationError,
    ScenarioRequest,
    ScenarioRequestError,
    canonicalize_seed,
)
from ._scenario_store import read_scenario_corpus
from .client import NativeWorker

# The original name is deliberately the same callable, not a wrapper with subtly different
# iterator or exception behaviour.
read_corpus = read_scenario_corpus


def generate_corpus(
    request: ScenarioRequest,
    workers: int,
    output_dir: str | Path,
    *,
    worker_factory: Callable[[int], CorpusWorker] | None = None,
    compression: int = 3,
) -> dict[str, Any]:
    """Write a deterministic Generated scenario corpus and return its summary.

    The default worker is selected here so existing callers that replace scenarios.NativeWorker
    at the public seam continue to work after the implementation split.
    """
    factory = worker_factory or (lambda _shard: NativeWorker())
    return _generate_corpus(request, workers, output_dir, worker_factory=factory, compression=compression)


__all__ = [
    "ANCIENT_CHOICE_KEY_ORDER",
    "COMBAT_ACTION",
    "CORPUS_SCHEMA",
    "ERROR_KEY_ORDER",
    "ERROR_RUN",
    "FAILURE_RECORD",
    "NESTED_CHOICE_KEY_ORDER",
    "NODE_KEY_ORDER",
    "RECIPE_KEY_ORDER",
    "REQUEST_KEY_ORDER",
    "ROW_ENCODING",
    "ROW_ESCAPE_NON_ASCII",
    "ROW_KEY_ORDER",
    "ROW_SCHEMA",
    "ROW_SEPARATORS",
    "ROW_TYPES",
    "SCENARIO_RECORD",
    "SHARD_GZIP_MTIME",
    "SHARD_GZIP_NAME",
    "SHARD_KEY_ORDER",
    "STAGE_ANCIENT_CHOICE",
    "STAGE_ANCIENT_ROOM",
    "STAGE_FIRST_COMBAT",
    "STAGE_LEAVE_ANCIENT",
    "STAGE_RECORD",
    "STAGE_ROW_ONE_NODE",
    "STAGE_RUN_START",
    "SUMMARY_FILE",
    "SUMMARY_KEY_ORDER",
    "SUMMARY_SEPARATORS",
    "CombatEpisode",
    "CorpusConflictError",
    "CorpusWorker",
    "RowFormatError",
    "RunWorker",
    "ScenarioGenerationError",
    "ScenarioMaterializationError",
    "ScenarioRequest",
    "ScenarioRequestError",
    "canonicalize_seed",
    "encode_row",
    "error_kind",
    "generate_corpus",
    "generate_rows",
    "materialize_scenario",
    "read_corpus",
    "read_scenario_corpus",
    "summarize_rows",
]
