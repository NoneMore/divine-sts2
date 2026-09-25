"""Internal deterministic corpus orchestration."""

from __future__ import annotations

import contextlib
import copy
import inspect
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ._scenario_codec import _add, _empty_counts, _tally, encode_row
from ._scenario_driver import _rows_for_element
from ._scenario_generation import _check_request, _elements
from ._scenario_model import (
    CORPUS_SCHEMA,
    CorpusConflictError,
    CorpusWorker,
    ScenarioRequest,
    ScenarioRequestError,
    _Element,
    _Resume,
    _Shard,
    _ShardOutcome,
)
from ._scenario_store import _request_identity, _resume, _shard_writer, _write_summary
from .client import NativeWorker
from .paths import find_game_assembly
from .pck_fingerprint import PckFingerprint


def generate_corpus(
    request: ScenarioRequest,
    workers: int,
    output_dir: str | Path,
    *,
    worker_factory: Callable[..., CorpusWorker] | None = None,
    native_worker: Callable[..., CorpusWorker] = NativeWorker,
    compression: int = 3,
) -> dict[str, Any]:
    """Record the batch into an artifact root: one shard per worker, plus the summary naming them.

    Rows come out exactly as :func:`generate_rows` produces them — one row per element, per Ancient
    choice the run offers, in the request's declared order — but they are written to *shards*
    rather than returned: shard *k* takes a contiguous block of the expanded request, so a batch
    read back in shard order is the request in element order for any worker count, and a slow
    worker changes when a row appears and never where it lands. The summary beside the shards is
    the corpus's manifest: it names the request, the game build, the worker count, the shards and
    the rows by type, and a second call with the same request resumes the corpus rather than
    redoing it — see the module docstring.

    A worker that dies, or that never comes up, is replaced, and the element a dying worker failed
    is a failure row like any other, so no single seed can end, bias or reorder a batch.
    ``worker_factory`` builds the worker for one shard index; the default builds a fresh native
    worker per shard, and a caller that supplies one can drive a batch without a game installed.
    A factory that declares a ``pck_fingerprint`` keyword receives the batch's shared fingerprint
    when multiple non-empty shards need workers. Existing one-argument factories keep their path.
    """
    if workers < 1:
        raise ScenarioRequestError(f"a corpus needs at least one worker, not {workers}")
    _check_request(request)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    corpus = _Corpus(
        root, _elements(request), request, workers, compression, _resume(root, request, workers, compression)
    )
    pending = corpus.pending
    if pending:
        if worker_factory is None:
            def factory(_shard: int, *, pck_fingerprint: PckFingerprint | None = None) -> CorpusWorker:
                return native_worker(pck_fingerprint=pck_fingerprint) if pck_fingerprint else native_worker()
        else:
            factory = worker_factory
        start_worker: Callable[[int], CorpusWorker] = factory
        if os.name == "nt" and sum(bool(shard.elements) for shard in pending) > 1 and _accepts_pck_fingerprint(factory):
            shared_pck = PckFingerprint.measure_for_assembly(find_game_assembly())
            start_worker = lambda shard: factory(shard, pck_fingerprint=shared_pck)
        with ThreadPoolExecutor(max_workers=len(pending)) as executor:
            # One task per shard: workers are blocking processes, so shards run in threads, and a
            # hard failure — a batch that was killed — takes the batch down while what already
            # landed stays resumable.
            futures = [executor.submit(corpus.write, shard, start_worker) for shard in pending]
            for future in futures:
                future.result()
    return corpus.write_summary()


def _accepts_pck_fingerprint(factory: Callable[..., CorpusWorker]) -> bool:
    """An explicit keyword opts a worker factory into the batch's shared PCK hint."""
    try:
        parameter = inspect.signature(factory).parameters.get("pck_fingerprint")
    except (TypeError, ValueError):
        return False
    return parameter is not None and parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY,
    )


def _shard_name(index: int, workers: int) -> str:
    """The file one shard of a ``workers``-worker batch is written under.

    Padded to the widest index the batch has, so that collecting a corpus's shards in name order —
    which is how the repository's readers collect one, and how a corpus reads back as the request
    in element order — is collecting them in shard order for any worker count.
    """
    return f"worker-{index:0{max(2, len(str(workers - 1)))}d}.jsonl.gz"


def _shards(elements: Sequence[_Element], workers: int) -> list[_Shard]:
    """Split the expanded request into one contiguous block of elements per worker.

    Blocks are contiguous so that the shards, read in name order, are the request in element order
    whatever the worker count. They differ in size by at most one, and the earlier shards take the
    longer ones, so the split is a function of the request and the worker count and of nothing
    else — in particular not of how fast any worker is.

    A shard is a block of *elements*, and an element is a character, an Ascension and a seed: the
    Ancient choices a seed's run offers are discovered by driving it, so they cannot index a shard.
    A batch with more workers than elements therefore leaves the shards after the last element
    empty — they are still written, so the worker count still names the corpus.
    """
    size, longer = divmod(len(elements), workers)
    shards: list[_Shard] = []
    start = 0
    for index in range(workers):
        length = size + (1 if index < longer else 0)
        shards.append(_Shard(index, tuple(range(start, start + length)), _shard_name(index, workers)))
        start += length
    return shards


class _Corpus:
    """One batch's artifact root while it is being written.

    The summary is the corpus's manifest, and it is rewritten — in one atomic move, so a reader
    never sees half of one — every time a shard lands. That is what makes a killed batch say what
    it wrote, the next run resume it, and a replacement visible instead of inferred.
    """

    def __init__(
        self,
        root: Path,
        elements: Sequence[_Element],
        request: ScenarioRequest,
        workers: int,
        compression: int,
        resume: _Resume,
    ) -> None:
        self.root = root
        self.elements = list(elements)
        self.workers = workers
        self.compression = compression
        self._request = _request_identity(request)
        self._shards = _shards(self.elements, workers)
        self._build = copy.deepcopy(resume.build)
        self._outcomes = dict(resume.outcomes)
        self._lock = threading.Lock()

    @property
    def pending(self) -> list[_Shard]:
        """The shards this batch still has to write, in request order."""
        return [shard for shard in self._shards if shard.index not in self._outcomes]

    def write(self, shard: _Shard, factory: Callable[[int], CorpusWorker]) -> None:
        """Write one shard: every row of every element it owns, in element order.

        The rows go to a temporary beside the shard's own name and are moved into place once the
        whole shard is written, so a shard file is always a whole shard: a batch that stops part-way
        leaves the shards that landed readable, and one temporary that the next run overwrites.

        A worker that dies is replaced rather than ending the batch. The element it died on is a
        failure row already, so the elements after it are still recorded — on the replacement — and
        the replacement is counted for the summary.
        """
        path = shard.path(self.root)
        temporary = path.with_name(path.name + ".part")
        counts = _empty_counts()
        replacements = 0
        worker: CorpusWorker | None = None
        try:
            with _shard_writer(temporary, self.compression) as write_shard:
                if shard.elements:
                    worker, retried = _start_worker(factory, shard.index)
                    self.observe(worker)
                    replacements += int(retried)
                    for element_index in shard.elements:
                        for row in _rows_for_element(self.elements[element_index], worker):
                            write_shard(encode_row(row))
                            _add(counts, row["record_type"])
                        if not worker.alive():
                            _close(worker)
                            worker, _ = _start_worker(factory, shard.index)
                            self.observe(worker)
                            replacements += 1
            os.replace(temporary, path)
        finally:
            _close(worker)
            temporary.unlink(missing_ok=True)
        self.record(shard.index, _ShardOutcome(counts, replacements))

    def observe(self, worker: CorpusWorker) -> None:
        """Hold every worker of the batch to the one game build the corpus is of.

        The first worker to start says which build that is; a worker that reports another one stops
        the batch, because rows from two builds are not one corpus and nothing downstream could
        tell.
        """
        with self._lock:
            if self._build is None:
                self._build = copy.deepcopy(worker.build)
            elif worker.build != self._build:
                raise CorpusConflictError(
                    f"the corpus at {self.root} is of game build {self._build}, this worker runs "
                    f"{worker.build}; refusing to mix two builds in one corpus"
                )

    def record(self, index: int, outcome: _ShardOutcome) -> None:
        """Record what one shard wrote, and rewrite the summary so the record survives a crash."""
        with self._lock:
            self._outcomes[index] = outcome
            if self._build is not None:
                _write_summary(self.root, self.summary())

    def summary(self) -> dict[str, Any]:
        """The corpus as a summary reports it: the request, the build, and every shard of it."""
        counts = _empty_counts()
        replacements = 0
        shards: list[dict[str, Any]] = []
        for shard in self._shards:
            outcome = self._outcomes.get(shard.index)
            if outcome is not None:
                for record_type, count in outcome.counts.items():
                    counts[record_type] += count
                replacements += outcome.replacements
            shards.append(
                {
                    "index": shard.index,
                    "file": shard.name,
                    "elements": list(shard.elements),
                    **_tally(outcome.counts if outcome is not None else _empty_counts()),
                    "worker_replacements": outcome.replacements if outcome is not None else 0,
                    "complete": outcome is not None,
                }
            )
        return {
            "schema": CORPUS_SCHEMA,
            "request": self._request,
            "game_build": copy.deepcopy(self._build),
            "workers": self.workers,
            "compression": self.compression,
            "elements": len(self.elements),
            "shards": shards,
            **_tally(counts),
            "worker_replacements": replacements,
            "complete": all(shard["complete"] for shard in shards),
        }

    def write_summary(self) -> dict[str, Any]:
        """Write the corpus's summary and return it, which is what a caller reports."""
        with self._lock:
            return _write_summary(self.root, self.summary())


def _start_worker(factory: Callable[[int], CorpusWorker], shard: int) -> tuple[CorpusWorker, bool]:
    """Start one shard's worker, giving a worker that cannot start a second attempt.

    A worker that dies before it answers anything is replaced exactly as one that dies mid-run, so a
    process that would not come up does not fail a batch that could have run without it; the second
    attempt is what the caller counts as a replacement. A second failure is the host rather than the
    batch — nothing else would work either — and is raised with the worker's own error.
    """
    try:
        return factory(shard), False
    except Exception:  # noqa: BLE001 — any failure to start is a worker that did not come up
        return factory(shard), True


def _close(worker: CorpusWorker | None) -> None:
    """Shut one worker down, best effort: a worker that will not exit cleanly has not damaged a
    corpus whose rows are already written, and its failure is not one this batch has to report."""
    if worker is not None:
        with contextlib.suppress(Exception):
            worker.close()
