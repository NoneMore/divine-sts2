"""Recording generated scenarios: the first fight of every run a request names.

A *generated scenario* is a run-start situation together with the choices that produced it,
such that the shipped game can reproduce it from the same run seed: paste the seed into the
custom run screen, take the recorded Ancient choice, and the same fight is there. This module
is that behaviour — a request in, rows out — and `divine-sts2 scenario` is a thin wrapper
over it, so the behaviour is importable and testable rather than a sibling script.

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
    A failure row's stage — the phase of the generation the run stopped in — and the error's
    kind and message.
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

import copy
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
from .client import NativeSimError

#: The versioned row tag, and the discriminators a row carries: one for an element that produced
#: a fight, one for an element that could not.
ROW_SCHEMA = "sts2-native-sim/scenario-record/1"
SCENARIO_RECORD = "scenario"
FAILURE_RECORD = "failure"

#: The row types a batch emits, in the order a summary counts them.
ROW_TYPES = (SCENARIO_RECORD, FAILURE_RECORD)

#: The error kind a failure row names for a run that did not reach its fight the way the
#: generation requires. The stage says where the run stopped; the kind says what sort of failure
#: it was, and a worker contributes its own error code to the same vocabulary.
ERROR_RUN = "run"

#: The decision the run reports when the row-1 node has resolved into a fight.
COMBAT_ACTION = "combat_action"

#: The stages a generation can stop at, named where the run stopped rather than where the
#: generation intended to go next. One of these becomes a failure row's `stage`.
STAGE_RUN_START = "run_start"
STAGE_ANCIENT_ROOM = "ancient_room"
STAGE_ANCIENT_CHOICE = "ancient_choice"
STAGE_LEAVE_ANCIENT = "leave_ancient"
STAGE_ROW_ONE_NODE = "row_one_node"
STAGE_FIRST_COMBAT = "first_combat"

#: The nested actions that select a reward rather than choice options, so they carry no
#: `option_ids`; every other nested action must name the option ids it selected.
_REWARD_ACTIONS = frozenset({"choose_custom_reward", "skip_custom_rewards"})


class ScenarioRequestError(ValueError):
    """A request cannot be expanded: it declares no run, or names one run twice.

    It is an input error rather than a run failure, so the whole request is refused before any
    run is driven and no row of it is recorded.
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


class RunWorker(RunStepWorker, Protocol):
    """The part of :class:`~sts2_native_sim.client.NativeWorker` a generation uses."""

    #: The shipped-game build the worker plays runs on, which every row it produces names.
    build: dict[str, Any]

    def run_reset(self, state: dict[str, Any]) -> dict[str, Any]: ...


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
    counts = {record_type: 0 for record_type in ROW_TYPES}
    for row in rows:
        record_type = row["record_type"]
        if record_type not in counts:
            raise ValueError(f"unknown row type {record_type!r}")
        counts[record_type] += 1
    return {
        "rows": counts,
        "succeeded": counts[SCENARIO_RECORD],
        "failed": counts[FAILURE_RECORD],
        "total": len(rows),
    }


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
    for character in request.characters:
        for ascension in request.ascensions:
            for seed in request.seeds:
                rows.extend(_rows_for_element(_Element.declared(character, ascension, seed), worker))
    return rows


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
        "recipe": _declared_recipe(recipe.element),
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


def _declared_recipe(element: _Element) -> dict[str, Any]:
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
