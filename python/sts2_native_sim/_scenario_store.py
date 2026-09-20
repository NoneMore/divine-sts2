"""Internal corpus reader and atomic persistence implementation."""

from __future__ import annotations

import contextlib
import gzip
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ._scenario_codec import _in_declared_order
from ._scenario_model import (
    CORPUS_SCHEMA,
    REQUEST_KEY_ORDER,
    ROW_ENCODING,
    ROW_ESCAPE_NON_ASCII,
    ROW_TYPES,
    SHARD_GZIP_MTIME,
    SHARD_GZIP_NAME,
    SHARD_KEY_ORDER,
    SUMMARY_FILE,
    SUMMARY_KEY_ORDER,
    SUMMARY_SEPARATORS,
    CorpusConflictError,
    ScenarioRequest,
    _Resume,
    _ShardOutcome,
    canonicalize_seed,
)


def read_scenario_corpus(path: str | Path) -> Iterator[dict[str, Any]]:
    """Every row of a corpus, in shard order — the convention the repository's readers collect.

    ``python/compile_native_rollouts.py`` takes a directory of shards, collects its ``*.jsonl.gz``
    in name order and parses each line as one record. This is that convention, so a corpus written
    here is one those readers consume, and a caller can read one back without a second
    implementation of the walk. A single shard file is read too, which is how a caller looks at one
    worker's rows.
    """
    given = Path(path)
    shards = sorted(given.glob("*.jsonl.gz")) if given.is_dir() else [given]
    for shard in shards:
        with gzip.open(shard, "rt", encoding=ROW_ENCODING) as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def _request_identity(request: ScenarioRequest) -> dict[str, Any]:
    """The request as a corpus stores it and compares it: each dimension in its resolved form.

    Resolved rather than declared, because that is what the elements are: a corpus of ``anc1ent01``
    and a corpus of ``ANCIENT01`` are the same corpus, and resuming one into the other is the same
    batch run twice rather than two corpora in one root.
    """
    return {
        "characters": [character.upper() for character in request.characters],
        "ascensions": list(request.ascensions),
        "seeds": [canonicalize_seed(seed) for seed in request.seeds],
    }


def _describe(resolved: Any) -> str:
    """One resolved request, phrased for a message that has to name two of them."""
    if not isinstance(resolved, dict):
        return repr(resolved)
    return (
        f"characters {resolved.get('characters')}, Ascensions {resolved.get('ascensions')} "
        f"and seeds {resolved.get('seeds')}"
    )


def _read_summary(root: Path) -> dict[str, Any] | None:
    """The corpus summary an artifact root holds, or ``None`` when it holds no corpus yet.

    A ``summary.json`` this module did not write is refused rather than adopted or overwritten:
    the repository writes one for other corpora (``python/native_rollout_farm.py``), and a batch
    resumed into another tool's manifest would report one corpus while writing another.
    """
    path = root / SUMMARY_FILE
    if not path.is_file():
        return None
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CorpusConflictError(f"{path} is not a readable corpus summary: {error}") from error
    if not isinstance(summary, dict) or summary.get("schema") != CORPUS_SCHEMA:
        raise CorpusConflictError(f"{path} is not a {CORPUS_SCHEMA} summary; refusing to write a corpus beside it")
    return summary


def _resume(root: Path, request: ScenarioRequest, workers: int, compression: int) -> _Resume:
    """What a batch can keep from the corpus already in the root, refusing anything else.

    A shard counts as complete when the summary records it complete *and* its file is still there:
    one that landed after the last summary write is redone, which costs one shard and cannot change
    the corpus. A request, a worker count, a compression level or a game build that differs from the
    recorded one is an input error, because writing into it would put two corpora — or one corpus at
    two shard boundaries, or under two compression levels, or with rows from two builds — under one
    name without saying so.
    """
    summary = _read_summary(root)
    if summary is None:
        return _Resume({}, None)
    resolved = _request_identity(request)
    if summary.get("request") != resolved:
        raise CorpusConflictError(
            f"the corpus at {root} is of {_describe(summary.get('request'))}, not of {_describe(resolved)}"
        )
    if summary.get("workers") != workers:
        raise CorpusConflictError(
            f"the corpus at {root} was written by {summary.get('workers')} workers; resuming it with "
            f"{workers} would move the shard boundaries"
        )
    if summary.get("compression") != compression:
        raise CorpusConflictError(
            f"the corpus at {root} was written at gzip level {summary.get('compression')}; resuming "
            f"it at level {compression} would leave one corpus whose shards were not all written alike"
        )
    outcomes: dict[int, _ShardOutcome] = {}
    for recorded in summary.get("shards") or []:
        if not isinstance(recorded, dict) or not recorded.get("complete"):
            continue
        index = recorded.get("index")
        if not isinstance(index, int) or not (root / str(recorded.get("file"))).is_file():
            continue
        outcomes[index] = _ShardOutcome(
            _recorded_counts(recorded.get("rows")), int(recorded.get("worker_replacements", 0))
        )
    return _Resume(outcomes, summary.get("game_build"))


def _recorded_counts(counts: Any) -> dict[str, int]:
    """The row counts a summary entry recorded, with every declared type present."""
    recorded = counts if isinstance(counts, dict) else {}
    return {record_type: int(recorded.get(record_type, 0)) for record_type in ROW_TYPES}


def _write_summary(root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    """Put the summary where a reader finds it, and never half of one.

    The bytes go to a sibling temporary and are moved into place in one step, so a reader — and a
    resume, after a batch was killed mid-write — sees either the previous summary or this one. The
    temporary is not a shard name, so a reader collecting ``*.jsonl.gz`` never sees it. The document
    written is returned, in the declared key order it was written in, which is what a caller reports.
    """
    document = _summary_in_declared_order(summary)
    path = root / SUMMARY_FILE
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=ROW_ESCAPE_NON_ASCII, separators=SUMMARY_SEPARATORS, indent=2) + "\n",
        encoding=ROW_ENCODING,
    )
    os.replace(temporary, path)
    return document


def _summary_in_declared_order(summary: dict[str, Any]) -> dict[str, Any]:
    """A summary in its declared key order, its request and its shards in theirs.

    The summary is a corpus document like a row, so it is written the same way: by declaration
    rather than by the order the manifest happened to be assembled in, so that regenerating a corpus
    and diffing it compares the corpus rather than the code that wrote it.
    """
    declared = _in_declared_order(summary, SUMMARY_KEY_ORDER, "$")
    declared["request"] = _in_declared_order(summary["request"], REQUEST_KEY_ORDER, "$.request")
    declared["rows"] = _in_declared_order(summary["rows"], ROW_TYPES, "$.rows")
    declared["shards"] = [
        _in_declared_order(shard, SHARD_KEY_ORDER, f"$.shards[{index}]")
        for index, shard in enumerate(summary["shards"])
    ]
    return declared


@contextlib.contextmanager
def _shard_writer(path: Path, compression: int) -> Iterator[Callable[[str], None]]:
    """Open one shard for writing, with the gzip member's metadata pinned.

    A gzip member's header carries the file's modification time and, optionally, an embedded name.
    `gzip.open` — what this repository's other corpus writers use — stamps the clock and the file's
    name into both, so two runs of one request differ in their compressed bytes while every row
    agrees, and a diff of a regenerated corpus reports the clock. The member is written with neither,
    which is what makes a shard's bytes a function of its rows and of nothing else.
    """
    with (
        open(path, "wb") as raw,
        gzip.GzipFile(
            filename=SHARD_GZIP_NAME,
            mode="wb",
            compresslevel=compression,
            fileobj=raw,
            mtime=SHARD_GZIP_MTIME,
        ) as member,
    ):

        def write(line: str) -> None:
            member.write(line.encode(ROW_ENCODING))

        yield write


# Historical name retained for callers that adopted the original generic reader.
read_corpus = read_scenario_corpus
