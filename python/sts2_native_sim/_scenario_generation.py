"""Internal request expansion and row-generation orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ._scenario_driver import _rows_for_element
from ._scenario_model import RunWorker, ScenarioRequest, ScenarioRequestError, _Element, canonicalize_seed


def generate_rows(request: ScenarioRequest, worker: RunWorker) -> list[dict[str, Any]]:
    """Record the first fight of every run the request names, one row per element.

    Rows come back in the request's declared order — character, then Ascension, then seed, then
    the Ancient choice the run offers — so a caller enumerates a corpus in one call instead of
    scripting the loop. The Ancient choices are the dimension the request does not declare: a
    seed contributes exactly as many rows as its run offers choices, and neither more nor fewer,
    so no opening is invented and none is skipped.

    An element that cannot produce a scenario contributes a failure row in its place — the same
    position in the same order, with the stage, the error and the recipe resolved so far — and
    the rest of the request is still driven, so one bad seed cannot end or bias a batch. Nothing
    is retried: see the module docstring for what a failure row carries.
    """
    _check_request(request)
    rows: list[dict[str, Any]] = []
    for element in _elements(request):
        rows.extend(_rows_for_element(element, worker))
    return rows


def _elements(request: ScenarioRequest) -> list[_Element]:
    """The request's elements in expansion order: character, then Ascension, then seed.

    This order is the whole of the request's ordering contract — a corpus assigns its shards by the
    index an element has here, and a row's position in its shard follows from it.
    """
    return [
        _Element.declared(character, ascension, seed)
        for character in request.characters
        for ascension in request.ascensions
        for seed in request.seeds
    ]


def _check_request(request: ScenarioRequest) -> None:
    """Refuse a request that cannot name distinct runs, before any run is driven.

    Distinct elements must stay distinct: two declared values that resolve alike — seeds that
    canonicalise alike, one character in two cases, one Ascension twice — would otherwise put
    two rows with one identity into a corpus, and a dimension that declares nothing would put
    none there at all while looking like it had worked.
    """
    for declared, missing in (
        (request.characters, "characters"),
        (request.ascensions, "Ascensions"),
        (request.seeds, "run seeds"),
    ):
        if not declared:
            raise ScenarioRequestError(f"the request declares no {missing}")
    _reject_collapsed(
        request.characters,
        str.upper,
        "the request names one character twice: {first!r} and {second!r} both resolve to {resolved!r}",
    )
    _reject_collapsed(
        request.ascensions,
        lambda ascension: ascension,
        "the request lists Ascension {resolved} twice",
    )
    _reject_collapsed(
        request.seeds,
        canonicalize_seed,
        "the request names one run seed twice: {first!r} and {second!r} both canonicalise to {resolved!r}",
    )


def _reject_collapsed(values: Sequence[Any], resolve: Callable[[Any], Any], complaint: str) -> None:
    """Raise when two declared values resolve alike, naming both of them."""
    declared: dict[Any, Any] = {}
    for value in values:
        resolved = resolve(value)
        if resolved in declared:
            raise ScenarioRequestError(complaint.format(first=declared[resolved], second=value, resolved=resolved))
        declared[resolved] = value
