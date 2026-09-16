"""Recording generated scenarios: the first fight of every run a request names.

A *generated scenario* is a run-start situation together with the choices that produced it,
such that the shipped game can reproduce it from the same run seed: paste the seed into the
custom run screen, take the recorded Ancient choice, and the same fight is there. This module
is that behaviour: a request in, rows out (:func:`generate_rows`), or a request in, a corpus of
shards and their summary out (:func:`generate_corpus`). `divine-sts2 scenario` is a thin wrapper
over the two, so the behaviour is importable and testable rather than a sibling script.

The request
-----------

A request declares three sets — characters, Ascensions and run seeds — and the run itself
supplies a fourth dimension: the Ancient choices the seed's run offers. The request expands to
a deterministically ordered element list, character outermost, then Ascension, then seed, with
the Ancient choice index innermost, and one row is recorded per element. A record's identity is
its character, Ascension, canonical run seed, Act variant, Ancient choice index, the nested
choices it resolved and its node coordinate, so two records for one character, Ascension and
seed differ only in the Ancient choice they took.

Seeds are canonicalised exactly as the shipped game canonicalises one when a run begins, so a
seed read off a screenshot works, and the caller's own form is kept on the record as a
diagnostic. A declaration that collapses onto another — two seeds that canonicalise alike, a
character named twice in two cases, an Ascension listed twice, or a dimension that declares
nothing at all — fails the whole request with :class:`ScenarioRequestError` before any run is
driven. Silent deduplication is forbidden, because it would change the size and the balance of
a corpus without telling anyone.

What one row carries
--------------------

``schema`` / ``record_type``
    The versioned row tag and the row discriminator — ``scenario`` for a row that carries a
    fight, ``failure`` for one that records why an element produced none — so a corpus can hold
    both kinds and a reader can tell which it has.
``game_build``
    The shipped-game build the run was played on, as the worker reports it, so a failed element
    is attributable to a build exactly as a recorded one is.
``recipe``
    The portable part: the character, the Ascension, the canonical run seed (with the raw
    seed kept beside it as a diagnostic when the caller's form differed), the Act variant,
    the Ancient options the run offered *in offer order*, the Ancient choice taken, every
    nested choice resolved, the row-1 node's coordinate and point type, and the encounter id.
    This is what a caller needs to reach the same fight in the shipped game. A failure row
    carries the same recipe only as far as the element resolved it, never a field of the fight.
``stage`` / ``error``
    A failure row's stage — the phase of the generation the run stopped in, or ``record`` for a
    drive that reached its fight and could not record it — and the error's kind and message.
``combat_initial_state``
    The canonical observation of the fight at the moment it has begun and before the player
    has made any decision: the run's position and RNG counters, the encounter, turn, phase,
    energy and stars, the creatures with their generated HP and their next move, every
    ordered pile — the hand and the draw pile included, because a draw pile's order is what a
    policy learns from — and the inventory, relics in order with their counter and native
    state and potions by slot. It is a canonical observation verbatim, so it validates against
    ``schemas/canonical-state.schema.json`` and the parity comparison reads it in the shape it
    already knows. Only a scenario row carries it.
``state_hash``
    The simulator's hash of that state, recorded so a corpus can be diffed. It is a simulator
    artifact with no shipped-game counterpart, so it is deliberately not part of the parity
    contract, and only a scenario row carries it.

The record is a *recipe*, not a state snapshot: it stores no state handle and no portable
branch, both of which name a node in one worker's local history rather than anything the
shipped game can reproduce.

When an element fails
---------------------

An element that cannot produce a scenario is recorded as a failure row rather than dropped,
retried into silence, or allowed to end the batch: :func:`generate_rows` records what happened
and keeps going, and :func:`summarize_rows` counts what succeeded and what failed, so a corpus
that lost elements says so instead of looking complete. A failure row never carries a combat
initial state, partial or otherwise — there is no state to carry and no simulator hash of one —
and its recipe holds only what the element resolved: the character, the Ascension, the canonical
seed (with the raw form beside it when it differed), the Act variant the run reports, and the
Ancient choice the element is for once the run has offered one. Nothing of the fight is on it,
because the row's stage already says how far the drive got.

A drive that stops before the run's offer is known contributes exactly one failure row, because
how many Ancient choices the run offers is precisely what that failure prevented learning. Once
the offer is known, every choice still gets its own row, failed or not. The same element fails
again with the same error kind on a re-run, because a kind is the error's own stable identity —
see :func:`error_kind` — and never its text.

The corpus a batch writes
-------------------------

:func:`generate_corpus` writes a batch into an artifact root the way the repository's other
corpora are written — one gzip-compressed JSONL shard per worker, ``worker-00.jsonl.gz`` upward,
plus a ``summary.json`` beside them — so the readers that already consume a corpus consume this
one without being told about it.

* **A shard is a contiguous block of the expanded request.** Element *i* belongs to the shard that
  owns the block *i* falls in, and a shard's rows are written in element order, so neither the
  shard a row lands in nor its position within it depends on which worker finished first: a slow
  worker changes when a row appears and never where it lands. Reading the shards back in name
  order is the request in element order, whatever the worker count.
* **An element that fails costs its own rows and nothing else.** One seed cannot end the batch or
  move another seed's rows, and the summary says how much of the corpus is a fight rather than a
  failure: the counts :func:`summarize_rows` produces, plus the request, the game build, the
  worker count and the shards.
* **A shard is written beside its own name and moved into place**, so a shard file is always a
  whole shard, and a batch that stops in the middle leaves the shards that landed readable.
* **Two runs of one request are the same bytes.** For a fixed request, game build and worker count,
  the shards and the summary are byte-identical on a re-run — the compressed bytes included — so a
  corpus can be regenerated and diffed and a mismatch means a real change. Three things make that a
  property of the record rather than of the run: the gzip member a shard is written as carries no
  embedded name and a zero timestamp instead of the clock, the row's own keys are written in the
  order this module declares rather than in the order a dictionary happened to be filled, and every
  quantity a row carries is an integer or a string, so no float formatting can drift. Changing the
  worker count moves the shard boundaries and nothing else: the rows are the same rows, in the same
  relative order, whatever the worker count.
* **The summary is the corpus's manifest.** It is rewritten every time a shard lands, so a batch
  that was killed still says what it wrote, and a second run of the same request resumes it: a
  shard the summary records as complete and whose file is still there is neither driven again nor
  rewritten. A shard that landed after the last summary write is redone, which costs one shard and
  cannot change the corpus, because the generator is deterministic. Resuming into another request,
  another worker count or another game build is refused before anything is written, rather than
  mixed into one root.
* **A worker that dies, or that never comes up, is replaced rather than ending the batch.** The
  element a dying worker failed is recorded as a failure row like any other, a fresh worker takes
  over the rest of the shard, and the summary counts the replacement.

The fixed rules
---------------

Each rule is fixed so that two runs of one request cannot disagree about which situation they
mean, and each is recorded so it can be audited and later replaced:

* **Every Ancient choice the run offers is enumerated**, in the order the run offered it, one
  record each. Which choice a record took is part of its identity rather than a caller's
  opinion, so coverage over run openings is complete rather than sampled.
* **A nested prompt is answered with the first legal action the environment reports** for it —
  one rule for every nested kind, whether that is a card select, a bundle pick, a reward set,
  or a reward set opened inside one. A reward pick names a reward index rather than option
  ids, so such a choice records an empty ``selected_option_ids`` and its selected index is the
  identity of what it picked.
* **The row-1 node is the first legal map action** in the order the environment reports them,
  with the coordinate and point type it picked recorded on the row.
"""

from __future__ import annotations

import contextlib
import copy
import gzip
import json
import os
import re
import threading
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .ancient import (
    LEAVE_EVENT_ACTION,
    MAP_CHOICE,
    DrivenChoice,
    NestedDecision,
    RunStepWorker,
    ancient_action,
    choice_actions,
    drive_choice,
    map_actions,
)
from .client import NativeSimError, NativeWorker

#: The versioned row tag, and the discriminators a row carries: one for an element that produced
#: a fight, one for an element that could not.
ROW_SCHEMA = "sts2-native-sim/scenario-record/1"
SCENARIO_RECORD = "scenario"
FAILURE_RECORD = "failure"

#: The row types a batch emits, in the order a summary counts them.
ROW_TYPES = (SCENARIO_RECORD, FAILURE_RECORD)

#: How a row becomes bytes: UTF-8, the compact separators `,` and `:`, and non-ASCII escaped. Each
#: is declared rather than left to an encoder default or the host's locale, because a row's bytes are
#: part of what a corpus promises; escaping non-ASCII also keeps a failure row's message — which can
#: come from a tool that speaks another language — the same bytes whatever it says. The summary
#: beside a corpus is the same encoding and escaping, indented and with the space an indented
#: document is read with, so it is declared too rather than left to `indent`'s defaults.
ROW_ENCODING = "utf-8"
ROW_SEPARATORS = (",", ":")
ROW_ESCAPE_NON_ASCII = True
SUMMARY_SEPARATORS = (",", ": ")

#: The gzip metadata a shard is written as: no embedded name, and a zero modification time. A gzip
#: member's header carries both, and `gzip.open` — what this repository's other corpus writers use —
#: stamps the clock and the file's name into it, so two runs of one request differ in their
#: compressed bytes while every row agrees. Pinned here, so a shard's bytes are a function of its
#: rows.
SHARD_GZIP_NAME = ""
SHARD_GZIP_MTIME = 0

#: The key order each kind of document is written in. A corpus is diffed line by line, and the order
#: is declared rather than inherited from the order a dictionary happened to be filled in, so the
#: same record is the same bytes however it was built. A key none of these names is refused where a
#: row is written, because a field a record gained without its order being extended is a change to
#: the corpus format rather than a detail of the code that built one row.
ROW_KEY_ORDER: dict[str, tuple[str, ...]] = {
    SCENARIO_RECORD: ("schema", "record_type", "game_build", "recipe", "combat_initial_state", "state_hash"),
    FAILURE_RECORD: ("schema", "record_type", "game_build", "recipe", "stage", "error"),
}
RECIPE_KEY_ORDER = (
    "character", "ascension", "seed", "raw_seed", "act_variant", "ancient_options", "ancient_choice",
    "nested_choices", "node", "encounter",
)
ANCIENT_CHOICE_KEY_ORDER = ("option_index", "relic_model_id")
NESTED_CHOICE_KEY_ORDER = ("kind", "selected_index", "selected_option_ids")
NODE_KEY_ORDER = ("col", "row", "point_type")
ERROR_KEY_ORDER = ("kind", "message")
SUMMARY_KEY_ORDER = (
    "schema", "request", "game_build", "workers", "compression", "elements", "shards",
    "rows", "succeeded", "failed", "total", "worker_replacements", "complete",
)
SHARD_KEY_ORDER = (
    "index", "file", "elements", "rows", "succeeded", "failed", "total", "worker_replacements", "complete",
)
REQUEST_KEY_ORDER = ("characters", "ascensions", "seeds")

#: The versioned tag of the summary a batch writes beside its shards, and the name that summary is
#: written under. A shard's own name is :func:`_shard_name`, because its padding depends on the
#: batch's worker count; together they are the convention the repository's corpus readers already
#: collect, so a corpus this module writes needs no reader of its own.
CORPUS_SCHEMA = "sts2-native-sim/scenario-corpus/1"
SUMMARY_FILE = "summary.json"

#: The error kind a failure row names for a run that did not reach its fight the way the
#: generation requires. The stage says where the run stopped; the kind says what sort of failure
#: it was, and a worker contributes its own error code to the same vocabulary.
ERROR_RUN = "run"

#: The decision the run reports when the row-1 node has resolved into a fight.
COMBAT_ACTION = "combat_action"

#: The stages a generation can stop at, named where the run stopped rather than where the
#: generation intended to go next. One of these becomes a failure row's `stage`. The record's own
#: stage is the exception that proves the naming: a drive that reached its fight can still fail
#: while the fight is being *recorded* — a quantity the record cannot carry — and that is where the
#: generation stopped.
STAGE_RUN_START = "run_start"
STAGE_ANCIENT_ROOM = "ancient_room"
STAGE_ANCIENT_CHOICE = "ancient_choice"
STAGE_LEAVE_ANCIENT = "leave_ancient"
STAGE_ROW_ONE_NODE = "row_one_node"
STAGE_FIRST_COMBAT = "first_combat"
STAGE_RECORD = "record"

#: The nested actions that select a reward rather than choice options, so they carry no
#: `option_ids`; every other nested action must name the option ids it selected.
_REWARD_ACTIONS = frozenset({"choose_custom_reward", "skip_custom_rewards"})


class ScenarioRequestError(ValueError):
    """A request cannot be expanded: it declares no run, or names one run twice.

    It is an input error rather than a run failure, so the whole request is refused before any
    run is driven and no row of it is recorded.
    """


class CorpusConflictError(ScenarioRequestError):
    """An artifact root cannot be resumed into by this request.

    An input error like the ones above: it is raised before a run is driven and before a shard is
    written, so one root never holds half of one corpus and half of another — or the same corpus
    at two shard boundaries, or rows from two game builds.
    """


class ScenarioGenerationError(RuntimeError):
    """A run could not be driven to its first fight. ``stage`` names where it stopped.

    This is not an error a caller of :func:`generate_rows` sees: it is the internal signal that
    an element failed, and the row for that element is built from it. ``message`` is the detail
    without the stage, so a failure row can carry the two fields separately.
    """

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage, self.message = stage, message


class RowFormatError(RuntimeError):
    """A document does not match the record format this module declares.

    A bug rather than an input error or a run failure: a row or a summary carries a key no declared
    order names, so writing it would put a field into a corpus in a position no reader was told
    about. It is raised where the bytes are made, which is the last moment the format is still the
    generator's to keep.

    It stops the batch rather than becoming a row, and that is the difference between it and a
    quantity the record cannot hold: no capture can make a row carry an undeclared key — only this
    module can — while a capture can report a quantity that is not an integer or a string, which is
    data and so is that element's failure row (:func:`_refuse_floats`) rather than the batch's.
    """


class RunWorker(RunStepWorker, Protocol):
    """The part of :class:`~sts2_native_sim.client.NativeWorker` a generation uses."""

    #: The shipped-game build the worker plays runs on, which every row it produces names.
    build: dict[str, Any]

    def run_reset(self, state: dict[str, Any]) -> dict[str, Any]: ...


class CorpusWorker(RunWorker, Protocol):
    """What a corpus needs of a worker beyond driving one element of a request.

    A corpus holds one worker per shard and closes it once the shard is written, so it also needs
    to ask whether that worker is still usable — the question that decides whether a crashed
    worker is replaced or the rest of the shard is lost with it.
    """

    def alive(self) -> bool: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ScenarioRequest:
    """A batch to record: the product of the characters, Ascensions and run seeds declared.

    Each set is kept in the order the caller declared it, because that order is the order the
    request expands in and therefore the order rows come back in. The Ancient choices are the
    dimension the request does not declare; the run supplies them.
    """

    characters: Sequence[str]
    ascensions: Sequence[int]
    seeds: Sequence[str]

    def __post_init__(self) -> None:
        # A caller may declare the sets as lists; the request is a value, so it keeps tuples.
        object.__setattr__(self, "characters", tuple(self.characters))
        object.__setattr__(self, "ascensions", tuple(self.ascensions))
        object.__setattr__(self, "seeds", tuple(self.seeds))


@dataclass(frozen=True)
class _Element:
    """One element of an expanded request, in the forms a run and a record need.

    ``character_model_id``, ``ascension`` and ``seed`` are what the run is started with;
    ``declared_seed`` is the caller's own form, kept as the record's raw-seed diagnostic exactly
    when it differs from the canonical ``seed``.
    """

    character_model_id: str
    ascension: int
    declared_seed: str
    seed: str

    @classmethod
    def declared(cls, character: str, ascension: int, seed: str) -> _Element:
        """The element one caller declaration expands to."""
        return cls(
            character_model_id=character.upper(),
            ascension=ascension,
            declared_seed=seed,
            seed=canonicalize_seed(seed),
        )


@dataclass
class _Recipe:
    """One element's recipe, resolved as far as a drive got, on the build it was resolved on.

    A drive fills this in as it walks the run — the phase it is in, the Act variant the run
    reports, the choices the run offers, the choice this element is for — so a drive that stops
    early leaves the rest unset and the caller holds exactly the facts the run reached. That is
    what a failure row carries, and it is why the recipe is filled in rather than built at the end.
    ``build`` and ``stage`` ride along because a row carries both: they are the envelope's and the
    failure's, not the recipe's own fields.
    """

    element: _Element
    build: dict[str, Any]
    stage: str = STAGE_RUN_START
    act_variant: str | None = None
    offered: list[dict[str, Any]] | None = None
    ancient_choice: dict[str, Any] | None = None


@dataclass(frozen=True)
class _DrivenRun:
    """What one drive of the run reached: the choices it offered and the fight it arrived at."""

    offered: list[dict[str, Any]]
    choice: dict[str, Any]
    driven: DrivenChoice
    node: dict[str, Any]
    observation: dict[str, Any]
    state_hash: str


@dataclass(frozen=True)
class _Stopped:
    """A drive that did not reach a fight, and the error that stopped it.

    A drive hands its failure back rather than raising it, because what it resolved before
    stopping — at least the run's offer, once that has been read — is what says how many rows the
    element still owes.
    """

    error: BaseException


def canonicalize_seed(seed: str) -> str:
    """Port of the shipped ``SeedHelper.CanonicalizeSeed``.

    Upper-case, ``O`` → ``0``, ``I`` → ``1``, then trim — in that order, because the shipped
    method replaces before it trims and so an internal space survives. The canonical form is
    what the shipped game stores for a run and what a corpus must paste back into the custom
    run screen, so it is what the request carries and the record stores; the caller's own form
    is kept beside it as a diagnostic rather than rejected.
    """
    return seed.upper().replace("O", "0").replace("I", "1").strip()


def error_kind(error: BaseException) -> str:
    """The stable token a failure row names for one error.

    The kind is what a corpus can be counted by, so it is the error's own identity rather than
    its text: a run that did not reach its fight is :data:`ERROR_RUN` (the stage says where it
    stopped), a worker error contributes the worker's own code — ``worker_crashed``,
    ``protocol_desync`` — and anything else contributes its class name, ``key_error``. A message
    can name a path or a count that moves between builds; a kind cannot, which is what makes "the
    same element fails again with the same kind" a checkable claim about a re-run.
    """
    if isinstance(error, ScenarioGenerationError):
        return ERROR_RUN
    if isinstance(error, NativeSimError):
        return error.code
    return re.sub(r"(?<!^)(?=[A-Z])", "_", type(error).__name__).lower()


def summarize_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Count a batch's rows by type, so a corpus that lost elements says so.

    The counts are what makes a biased corpus visible: every row type this module declares is
    reported even at zero, so "nothing failed" is a stated fact rather than an absent key. A row
    of a type this summary does not know is refused instead of being counted as neither a success
    nor a failure, which would make the two counts stop adding up to the rows.
    """
    return _tally(_counts(rows))


def encode_row(row: dict[str, Any]) -> str:
    """One row as a corpus stores it: JSON on one line, in the declared key order.

    The bytes are the record's own: the row's structure is written in the order
    :data:`ROW_KEY_ORDER` and its siblings declare rather than in the order the dictionary happens
    to hold — so a row built by another call site, or by another version of one, is still the same
    line — and the encoding and separators are pinned rather than left to an encoder default.

    The two values the *worker* owns, the combat observation and the game build, are written as the
    capture reported them: their shape is the published canonical-state schema's, which is not a
    serialisation order, and their order is as fixed as their values are, because the byte guarantee
    is scoped to one game build.
    """
    return json.dumps(
        _row_in_declared_order(row), ensure_ascii=ROW_ESCAPE_NON_ASCII, separators=ROW_SEPARATORS
    ) + "\n"


def _in_declared_order(record: dict[str, Any], order: Sequence[str], path: str) -> dict[str, Any]:
    """One document in its declared key order, refusing a key the declaration does not name.

    This is the one place the record's key order is applied: everything below it says which
    declaration governs which of the record's own documents, so a row's bytes follow from the
    declarations and from nothing about how the row was assembled.
    """
    undeclared = [key for key in record if key not in order]
    if undeclared:
        raise RowFormatError(f"{path} carries keys {sorted(undeclared)}, which {order} does not declare")
    return {key: record[key] for key in order if key in record}


def _row_in_declared_order(row: dict[str, Any]) -> dict[str, Any]:
    """One row's own keys, in the order the record format declares them, and nothing else.

    The row's *structure* is ordered here and its *values* are not touched, so what a capture
    reported is what a reader gets and only the record's own keys are this module's to place.
    """
    order = ROW_KEY_ORDER.get(row.get("record_type", ""))
    if order is None:
        raise RowFormatError(f"a row of type {row.get('record_type')!r} is not one this format declares")
    declared = _in_declared_order(row, order, "$")
    declared["recipe"] = _recipe_in_declared_order(row["recipe"])
    if "error" in row:
        declared["error"] = _in_declared_order(row["error"], ERROR_KEY_ORDER, "$.error")
    return declared


def _recipe_in_declared_order(recipe: dict[str, Any]) -> dict[str, Any]:
    """One row's recipe in declared order, with the nested records it carries in theirs."""
    declared = _in_declared_order(recipe, RECIPE_KEY_ORDER, "$.recipe")
    if "ancient_options" in recipe:
        declared["ancient_options"] = [
            _in_declared_order(option, ANCIENT_CHOICE_KEY_ORDER, f"$.recipe.ancient_options[{index}]")
            for index, option in enumerate(recipe["ancient_options"])
        ]
    if "ancient_choice" in recipe:
        declared["ancient_choice"] = _in_declared_order(
            recipe["ancient_choice"], ANCIENT_CHOICE_KEY_ORDER, "$.recipe.ancient_choice"
        )
    if "nested_choices" in recipe:
        declared["nested_choices"] = [
            _in_declared_order(nested, NESTED_CHOICE_KEY_ORDER, f"$.recipe.nested_choices[{index}]")
            for index, nested in enumerate(recipe["nested_choices"])
        ]
    if "node" in recipe:
        declared["node"] = _in_declared_order(recipe["node"], NODE_KEY_ORDER, "$.recipe.node")
    return declared


def _refuse_floats(value: Any, path: str = "$") -> None:
    """Refuse a record that carries a floating-point quantity, naming where it is.

    Every quantity a record carries is an integer or a string, so that a corpus cannot drift with a
    float's formatting: `1.0` and `1` are one number and two byte strings, and which of them a build
    prints is not something a diff can tell from a real change. The published schema cannot catch
    one — `1.0` *is* an integer to JSON Schema's `integer` type — so the record refuses it itself,
    and a capture that reports a fractional quantity is an element that could not be recorded rather
    than a corpus written twice differently.
    """
    if isinstance(value, float):
        raise ScenarioGenerationError(STAGE_RECORD, f"{path} is {value!r}, a floating-point quantity")
    if isinstance(value, dict):
        for key, child in value.items():
            _refuse_floats(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _refuse_floats(child, f"{path}[{index}]")


def _counts(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """How many rows of each declared type `rows` holds, refusing a type nothing declares."""
    counts = _empty_counts()
    for row in rows:
        _add(counts, row["record_type"])
    return counts


def _tally(counts: dict[str, int]) -> dict[str, Any]:
    """The counts a batch reports: by row type, then the two totals that follow from them."""
    return {
        "rows": dict(counts),
        "succeeded": counts[SCENARIO_RECORD],
        "failed": counts[FAILURE_RECORD],
        "total": sum(counts.values()),
    }


def _empty_counts() -> dict[str, int]:
    return {record_type: 0 for record_type in ROW_TYPES}


def _add(counts: dict[str, int], record_type: str) -> None:
    if record_type not in counts:
        raise ValueError(f"unknown row type {record_type!r}")
    counts[record_type] += 1


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


def _rows_for_element(element: _Element, worker: RunWorker) -> list[dict[str, Any]]:
    """Every row one element of the request produces: one per Ancient choice its run offers.

    The first drive of the run both records its first Ancient choice and says how many choices
    the run offers; each remaining choice is then taken by driving the run again from its start,
    so a row is the record of the drive that made *its* choice rather than a projection of the
    first drive's state.

    A drive that stops is that element's failure row and is never retried — the element that
    failed is one row of the corpus, not a reason to try again — and the choices after it are still
    driven, because the offer they belong to was read before the drive stopped. Only a first drive
    that stops before reading the offer leaves nothing to enumerate: how many choices the run
    offers is exactly what that failure prevented learning, so the element owes one failure row.
    """
    build = worker.build
    attempted = _Recipe(element, build)
    first = _drive_safely(attempted, 0, worker)
    if attempted.offered is None:
        return [_element_row(attempted, first)]

    rows = [_element_row(attempted, first)]
    for choice_index in range(1, len(attempted.offered)):
        recipe = _Recipe(
            element,
            build,
            act_variant=attempted.act_variant,
            ancient_choice=attempted.offered[choice_index],
        )
        rows.append(_element_row(recipe, _drive_safely(recipe, choice_index, worker)))
    return rows


def _drive_safely(recipe: _Recipe, choice_index: int, worker: RunWorker) -> _DrivenRun | _Stopped:
    """Drive one run, handing back the failure instead of raising it.

    Whatever goes wrong is this element's failure, not the batch's: it is recorded — stage, kind
    and message — rather than raised, so a caller counts it instead of losing the request.
    """
    try:
        return _drive_to_first_fight(recipe, choice_index, worker)
    except Exception as error:  # noqa: BLE001
        return _Stopped(error)


def _element_row(recipe: _Recipe, outcome: _DrivenRun | _Stopped) -> dict[str, Any]:
    """One element's row: the scenario its drive reached, or the failure that stopped it.

    Recording the scenario can fail too — a nested selection the prompt does not report is a
    failure of that element's record — and that is a failure row like any other.
    """
    if isinstance(outcome, _Stopped):
        return _failure_row(recipe, outcome.error)
    try:
        return _row(recipe, outcome)
    except Exception as error:  # noqa: BLE001
        return _failure_row(recipe, error)


def _drive_to_first_fight(recipe: _Recipe, choice_index: int, worker: RunWorker) -> _DrivenRun:
    """Drive one run from its start to its first fight, taking the Ancient choice at `choice_index`.

    The recipe is stamped before every phase, so a failure that names no stage of its own — a
    worker's error, or a bug — is still attributed to the phase the drive was in.
    """
    recipe.stage = STAGE_RUN_START
    state = worker.run_reset(_reset_state(recipe.element))
    recipe.act_variant = state["observation"]["run"]["act_variant"]

    recipe.stage = STAGE_ANCIENT_ROOM
    ancient = ancient_action(state)
    if ancient is None:
        raise ScenarioGenerationError(STAGE_ANCIENT_ROOM, "the run does not start on the act's Ancient node")
    state = worker.run_step(ancient["action_id"])

    recipe.stage = STAGE_ANCIENT_CHOICE
    choices = _offered_choices(state)
    if not choices:
        raise ScenarioGenerationError(STAGE_ANCIENT_CHOICE, "the Ancient room offers no choice to take")
    offered = [option for option, _ in choices]
    recipe.offered = offered
    if choice_index >= len(choices):
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the Ancient room offers {len(choices)} choices, so there is no choice {choice_index}",
        )
    choice = choices[choice_index][1]
    recipe.ancient_choice = choices[choice_index][0]
    try:
        driven = drive_choice(worker, choice)
    except ValueError as error:
        raise ScenarioGenerationError(STAGE_ANCIENT_CHOICE, str(error)) from error

    recipe.stage = STAGE_LEAVE_ANCIENT
    state = worker.run_step(LEAVE_EVENT_ACTION)
    if state["observation"]["decision"]["kind"] != MAP_CHOICE:
        raise ScenarioGenerationError(
            STAGE_LEAVE_ANCIENT,
            f"leaving the Ancient room returned "
            f"{state['observation']['decision']['kind']!r} instead of the run's map",
        )

    recipe.stage = STAGE_ROW_ONE_NODE
    nodes = map_actions(state)
    if not nodes:
        raise ScenarioGenerationError(STAGE_ROW_ONE_NODE, "the map after the Ancient room offers no node to travel to")
    node = nodes[0]
    recipe.stage = STAGE_FIRST_COMBAT
    combat = worker.run_step(node["action_id"])
    observation = combat["observation"]
    if observation["decision"]["kind"] != COMBAT_ACTION:
        raise ScenarioGenerationError(
            STAGE_FIRST_COMBAT,
            f"the row-1 node resolved to {observation['decision']['kind']!r}, not a fight",
        )
    return _DrivenRun(
        offered=offered,
        choice=choice,
        driven=driven,
        node=node,
        observation=observation,
        state_hash=combat["state_hash"],
    )


def _reset_state(element: _Element) -> dict[str, Any]:
    """The run-start request for one scenario: the shipped starting loadout, fully unlocked.

    The character and Ascension come from the element and nothing else does, because a
    caller-supplied deck, relic set or potion list would produce a situation the shipped game
    cannot reach. The fields the starting-loadout path ignores are still sent, because the
    environment's reset request declares them.
    """
    return {
        "game_build": {},
        "seed": element.seed,
        "rng_counters": {},
        "character": element.character_model_id,
        "ascension": element.ascension,
        "encounter": "first",
        "current_hp": 80,
        "max_hp": 80,
        "deck": [],
        "gold": 99,
        "use_character_starting_loadout": True,
    }


def _choice_identity(parameters: dict[str, Any]) -> dict[str, Any]:
    """What identifies one offered Ancient choice: its offer index and the relic it grants.

    An event option reports the two at its top level and a `choose_event` action reports them
    under `parameters`, so one shape reads both.
    """
    return {"option_index": parameters.get("option_index"), "relic_model_id": parameters.get("relic_model_id")}


def _offered_choices(state: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The Ancient's offered choices: each option the event reports, with the action that takes it.

    The options and the decision's legal actions are two views of one offer, so they are matched
    by option index and any disagreement is a staged failure rather than a quietly different
    corpus: an option no action can take would be recorded as offered while being impossible, and
    a legal choice the event does not report would leave the run opening unrecorded. That match is
    what makes "a seed records exactly the choices its run offers" a checked claim rather than a
    count taken from one list and an index taken from another.
    """
    event = state["observation"].get("event")
    if not isinstance(event, dict):
        raise ScenarioGenerationError(STAGE_ANCIENT_ROOM, "the Ancient node did not open the Ancient's event room")

    takers: dict[Any, tuple[dict[str, Any], dict[str, Any]]] = {}
    for action in choice_actions(state):
        identity = _choice_identity(action.get("parameters") or {})
        index = identity["option_index"]
        if index in takers:
            raise ScenarioGenerationError(STAGE_ANCIENT_CHOICE, f"the Ancient offers two choices at option {index}")
        takers[index] = (identity, action)

    offered: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for reported in (_choice_identity(option) for option in event.get("options") or []):
        index = reported["option_index"]
        taker = takers.pop(index, None)
        if taker is None:
            raise ScenarioGenerationError(
                STAGE_ANCIENT_CHOICE, f"the Ancient reports option {index}, which no legal action can take"
            )
        identity, action = taker
        if identity != reported:
            raise ScenarioGenerationError(
                STAGE_ANCIENT_CHOICE,
                f"the Ancient's option {index} is {reported} in the event and {identity} in the choice",
            )
        offered.append((reported, action))
    if takers:
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the Ancient offers choices at options {sorted(takers)} the event does not report",
        )
    return offered


def _envelope(recipe: _Recipe, record_type: str) -> dict[str, Any]:
    """The part of a row every row type carries: its tag, its discriminator, the build, the recipe.

    This is the record's row envelope, and it is built in one place because both row types must
    agree about it: a reader tells the two apart by the discriminator, not by which keys are there.
    The recipe starts as what the element's declaration resolved; each caller adds what more it
    resolved, in the order the record declares.
    """
    return {
        "schema": ROW_SCHEMA,
        "record_type": record_type,
        "game_build": copy.deepcopy(recipe.build),
        "recipe": _element_recipe(recipe.element),
    }


def _row(recipe: _Recipe, walk: _DrivenRun) -> dict[str, Any]:
    """One scenario row, with its keys in the order the record declares them."""
    parameters = walk.choice.get("parameters") or {}
    node_parameters = walk.node["parameters"]
    row = _envelope(recipe, SCENARIO_RECORD)
    row["recipe"].update({
        # The Act variant and the encounter are the fight's own report of the run it belongs to.
        "act_variant": walk.observation["run"]["act_variant"],
        "ancient_options": walk.offered,
        "ancient_choice": _choice_identity(parameters),
        "nested_choices": [_nested_choice(decision) for decision in walk.driven.decisions],
        "node": {
            "col": node_parameters["col"],
            "row": node_parameters["row"],
            "point_type": node_parameters["point_type"],
        },
        "encounter": walk.observation["combat"]["encounter"],
    })
    row["combat_initial_state"] = copy.deepcopy(walk.observation)
    row["state_hash"] = walk.state_hash
    # A row is refused here rather than where it is written, because this is the last moment a
    # quantity the record cannot carry is still this element's failure instead of a dead batch.
    _refuse_floats(row)
    return row


def _failure_row(recipe: _Recipe, error: BaseException) -> dict[str, Any]:
    """One failure row: the stage, the error, and the recipe resolved so far.

    A failure row never carries a combat initial state, partial or otherwise: its whole claim is
    that no scenario was produced, so there is no state to carry and no simulator hash of one. Its
    recipe names what the element resolved — the declaration, the Act variant the run reports, and
    the Ancient choice the element is for once the run has offered one — and never a field of the
    fight, because the row's stage already says how far the drive got.
    """
    stage, message = _staged_failure(recipe, error)
    row = _envelope(recipe, FAILURE_RECORD)
    if recipe.act_variant is not None:
        row["recipe"]["act_variant"] = recipe.act_variant
    if recipe.ancient_choice is not None:
        row["recipe"]["ancient_choice"] = dict(recipe.ancient_choice)
    row["stage"] = stage
    row["error"] = {"kind": error_kind(error), "message": message}
    return row


def _staged_failure(recipe: _Recipe, error: BaseException) -> tuple[str, str]:
    """The stage and the message one failure row names for an error.

    A staged generation failure carries both itself, so its stage survives the phase the drive had
    moved on to by the time the row was built — a nested choice that cannot be recorded fails at
    the Ancient choice, not at the fight the drive reached. A worker's error carries a message but
    no stage of its own, so it is reported against the phase the drive was in. Anything else
    carries neither and is reported the same way, with its own text.
    """
    return getattr(error, "stage", None) or recipe.stage, getattr(error, "message", None) or str(error)


def _element_recipe(element: _Element) -> dict[str, Any]:
    """The recipe fields one declaration resolves before any run is driven.

    The caller's own seed form is kept as a diagnostic exactly when the canonical form differs
    from it, so a record says that canonicalisation happened and what it was applied to.
    """
    resolved: dict[str, Any] = {
        "character": element.character_model_id,
        "ascension": element.ascension,
        "seed": element.seed,
    }
    if element.declared_seed != element.seed:
        resolved["raw_seed"] = element.declared_seed
    return resolved


def _nested_choice(decision: NestedDecision) -> dict[str, Any]:
    """One nested decision, and the action the fixed rule took from it."""
    state = decision.state
    actions = state.get("legal_actions") or []
    picked = next(
        ((index, action) for index, action in enumerate(actions) if action.get("action_id") == decision.action_id),
        None,
    )
    if picked is None:
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the nested choice took {decision.action_id!r}, which the prompt did not offer",
        )
    index, action = picked
    option_ids = (action.get("parameters") or {}).get("option_ids")
    if option_ids is None and action.get("kind") not in _REWARD_ACTIONS:
        # An action that selects options has to say which; a record that quietly stored an
        # empty selection would look like a choice of nothing rather than a missing fact.
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the {action.get('kind')!r} action {decision.action_id!r} names no option ids",
        )
    return {
        "kind": state["observation"]["decision"]["kind"],
        "selected_index": index,
        "selected_option_ids": list(option_ids) if isinstance(option_ids, list) else [],
    }


# -- the corpus a batch writes -----------------------------------------------------------


@dataclass(frozen=True)
class _Shard:
    """One shard of a batch: the elements it owns and the file it is written to.

    Elements are indices into the expanded request, and the file name — which is fixed when the
    batch is planned, because how wide its index is padded depends on the worker count — is what a
    reader finds it under. A shard therefore names the same work however the batch is run.
    """

    index: int
    elements: tuple[int, ...]
    name: str

    def path(self, root: Path) -> Path:
        return root / self.name


@dataclass(frozen=True)
class _ShardOutcome:
    """What one shard recorded: its rows by type, and the workers it had to replace."""

    counts: dict[str, int]
    replacements: int


@dataclass(frozen=True)
class _Resume:
    """What an artifact root already holds: the shards it recorded, and the build they ran on."""

    outcomes: dict[int, _ShardOutcome]
    build: dict[str, Any] | None


def generate_corpus(
    request: ScenarioRequest,
    workers: int,
    output_dir: str | Path,
    *,
    worker_factory: Callable[[int], CorpusWorker] | None = None,
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
    """
    if workers < 1:
        raise ScenarioRequestError(f"a corpus needs at least one worker, not {workers}")
    _check_request(request)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    corpus = _Corpus(
        root, _elements(request), request, workers, compression, _resume(root, request, workers, compression)
    )
    factory = worker_factory or _native_worker
    pending = corpus.pending
    if pending:
        with ThreadPoolExecutor(max_workers=len(pending)) as executor:
            # One task per shard: workers are blocking processes, so shards run in threads, and a
            # hard failure — a batch that was killed — takes the batch down while what already
            # landed stays resumable.
            futures = [executor.submit(corpus.write, shard, factory) for shard in pending]
            for future in futures:
                future.result()
    return corpus.write_summary()


def _native_worker(_shard: int) -> CorpusWorker:
    """The default shard worker: one isolated native worker, which ignores its shard index."""
    return NativeWorker()


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


def read_corpus(path: str | Path) -> Iterator[dict[str, Any]]:
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
            shards.append({
                "index": shard.index,
                "file": shard.name,
                "elements": list(shard.elements),
                **_tally(outcome.counts if outcome is not None else _empty_counts()),
                "worker_replacements": outcome.replacements if outcome is not None else 0,
                "complete": outcome is not None,
            })
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
    with open(path, "wb") as raw, gzip.GzipFile(
        filename=SHARD_GZIP_NAME,
        mode="wb",
        compresslevel=compression,
        fileobj=raw,
        mtime=SHARD_GZIP_MTIME,
    ) as member:

        def write(line: str) -> None:
            member.write(line.encode(ROW_ENCODING))

        yield write


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

