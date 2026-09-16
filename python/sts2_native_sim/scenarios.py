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
    The versioned row tag and the row discriminator, so a corpus can hold more than one kind
    of row and a reader can tell which it has.
``game_build``
    The shipped-game build the run was played on.
``recipe``
    The portable part: the character, the Ascension, the canonical run seed (with the raw
    seed kept beside it as a diagnostic when the caller's form differed), the Act variant,
    the Ancient options the run offered *in offer order*, the Ancient choice taken, every
    nested choice resolved, the row-1 node's coordinate and point type, and the encounter id.
    This is what a caller needs to reach the same fight in the shipped game.
``combat_initial_state``
    The canonical observation of the fight at the moment it has begun and before the player
    has made any decision: the run's position and RNG counters, the encounter, turn, phase,
    energy and stars, the creatures with their generated HP and their next move, every
    ordered pile — the hand and the draw pile included, because a draw pile's order is what a
    policy learns from — and the inventory, relics in order with their counter and native
    state and potions by slot. It is a canonical observation verbatim, so it validates against
    ``schemas/canonical-state.schema.json`` and the parity comparison reads it in the shape it
    already knows.
``state_hash``
    The simulator's hash of that state, recorded so a corpus can be diffed. It is a simulator
    artifact with no shipped-game counterpart, so it is deliberately not part of the parity
    contract.

The record is a *recipe*, not a state snapshot: it stores no state handle and no portable
branch, both of which name a node in one worker's local history rather than anything the
shipped game can reproduce.

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

#: The versioned row tag, and the discriminator a success row carries.
ROW_SCHEMA = "sts2-native-sim/scenario-record/1"
SCENARIO_RECORD = "scenario"

#: The decision the run reports when the row-1 node has resolved into a fight.
COMBAT_ACTION = "combat_action"

#: The stages a generation can stop at, named where the run stopped rather than where the
#: generation intended to go next. Ticket 08 turns one of these into a failure row's `stage`.
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
    """A run could not be driven to its first fight. ``stage`` names where it stopped."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage


class RunWorker(RunStepWorker, Protocol):
    """The part of :class:`~sts2_native_sim.client.NativeWorker` a generation uses."""

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


@dataclass(frozen=True)
class _DrivenRun:
    """What one drive of the run reached: the choices it offered and the fight it arrived at."""

    offered: list[dict[str, Any]]
    choice: dict[str, Any]
    driven: DrivenChoice
    node: dict[str, Any]
    observation: dict[str, Any]
    state_hash: str


def canonicalize_seed(seed: str) -> str:
    """Port of the shipped ``SeedHelper.CanonicalizeSeed``.

    Upper-case, ``O`` → ``0``, ``I`` → ``1``, then trim — in that order, because the shipped
    method replaces before it trims and so an internal space survives. The canonical form is
    what the shipped game stores for a run and what a corpus must paste back into the custom
    run screen, so it is what the request carries and the record stores; the caller's own form
    is kept beside it as a diagnostic rather than rejected.
    """
    return seed.upper().replace("O", "0").replace("I", "1").strip()


def generate_rows(request: ScenarioRequest, worker: RunWorker) -> list[dict[str, Any]]:
    """Record the first fight of every run the request names, one row per element.

    Rows come back in the request's declared order — character, then Ascension, then seed, then
    the Ancient choice the run offers — so a caller enumerates a corpus in one call instead of
    scripting the loop. The Ancient choices are the dimension the request does not declare: a
    seed contributes exactly as many rows as its run offers choices, and neither more nor
    fewer, so no opening is invented and none is skipped.
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
    """
    driven = [_drive_to_first_fight(element, 0, worker)]
    for choice_index in range(1, len(driven[0].offered)):
        driven.append(_drive_to_first_fight(element, choice_index, worker))
    return [_row(element, walk) for walk in driven]


def _drive_to_first_fight(element: _Element, choice_index: int, worker: RunWorker) -> _DrivenRun:
    """Drive one run from its start to its first fight, taking the Ancient choice at `choice_index`."""
    state = worker.run_reset(_reset_state(element))

    ancient = ancient_action(state)
    if ancient is None:
        raise ScenarioGenerationError(STAGE_ANCIENT_ROOM, "the run does not start on the act's Ancient node")
    state = worker.run_step(ancient["action_id"])

    choices = _offered_choices(state)
    if not choices:
        raise ScenarioGenerationError(STAGE_ANCIENT_CHOICE, "the Ancient room offers no choice to take")
    if choice_index >= len(choices):
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the Ancient room offers {len(choices)} choices, so there is no choice {choice_index}",
        )
    choice = choices[choice_index][1]
    try:
        driven = drive_choice(worker, choice)
    except ValueError as error:
        raise ScenarioGenerationError(STAGE_ANCIENT_CHOICE, str(error)) from error

    state = worker.run_step(LEAVE_EVENT_ACTION)
    if state["observation"]["decision"]["kind"] != MAP_CHOICE:
        raise ScenarioGenerationError(
            STAGE_LEAVE_ANCIENT,
            f"leaving the Ancient room returned "
            f"{state['observation']['decision']['kind']!r} instead of the run's map",
        )

    nodes = map_actions(state)
    if not nodes:
        raise ScenarioGenerationError(STAGE_ROW_ONE_NODE, "the map after the Ancient room offers no node to travel to")
    node = nodes[0]
    combat = worker.run_step(node["action_id"])
    observation = combat["observation"]
    if observation["decision"]["kind"] != COMBAT_ACTION:
        raise ScenarioGenerationError(
            STAGE_FIRST_COMBAT,
            f"the row-1 node resolved to {observation['decision']['kind']!r}, not a fight",
        )
    return _DrivenRun(
        offered=[option for option, _ in choices],
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


def _row(element: _Element, walk: _DrivenRun) -> dict[str, Any]:
    """One scenario row, with its keys in the order the record declares them."""
    parameters = walk.choice.get("parameters") or {}
    node_parameters = walk.node["parameters"]
    recipe: dict[str, Any] = {
        "character": element.character_model_id,
        "ascension": element.ascension,
        "seed": element.seed,
    }
    if element.declared_seed != element.seed:
        recipe["raw_seed"] = element.declared_seed
    recipe.update({
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
    return {
        "schema": ROW_SCHEMA,
        "record_type": SCENARIO_RECORD,
        "game_build": copy.deepcopy(walk.observation["game_build"]),
        "recipe": recipe,
        "combat_initial_state": copy.deepcopy(walk.observation),
        "state_hash": walk.state_hash,
    }


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
