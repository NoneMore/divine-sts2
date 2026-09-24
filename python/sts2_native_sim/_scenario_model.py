"""Internal data model for generated scenarios and corpora."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .ancient import DrivenChoice, RunStepWorker

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
    "character",
    "ascension",
    "seed",
    "raw_seed",
    "act_variant",
    "ancient_options",
    "ancient_choice",
    "nested_choices",
    "node",
    "encounter",
)
ANCIENT_CHOICE_KEY_ORDER = ("option_index", "relic_model_id")
NESTED_CHOICE_KEY_ORDER = ("kind", "selected_index", "selected_option_ids")
NODE_KEY_ORDER = ("col", "row", "point_type")
ERROR_KEY_ORDER = ("kind", "message")
SUMMARY_KEY_ORDER = (
    "schema",
    "request",
    "game_build",
    "workers",
    "compression",
    "elements",
    "shards",
    "rows",
    "succeeded",
    "failed",
    "total",
    "worker_replacements",
    "complete",
)
SHARD_KEY_ORDER = (
    "index",
    "file",
    "elements",
    "rows",
    "succeeded",
    "failed",
    "total",
    "worker_replacements",
    "complete",
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

    def fork(self) -> str: ...

    def restore(self, state_handle: str) -> dict[str, Any]: ...


class CorpusWorker(RunWorker, Protocol):
    """What a corpus needs of a worker beyond driving one element of a request.

    A corpus holds one worker per shard and closes it once the shard is written, so it also needs
    to ask whether that worker is still usable — the question that decides whether a crashed
    worker is replaced or the rest of the shard is lost with it.
    """

    def alive(self) -> bool: ...

    def close(self) -> None: ...


class ScenarioMaterializationError(ValueError):
    """A record cannot be replayed into the combat it claims to describe."""


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
