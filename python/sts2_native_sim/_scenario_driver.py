"""Internal live-run driver and Generated scenario materialization."""

from __future__ import annotations

import copy
from typing import Any

from ._scenario_codec import _refuse_floats, error_kind
from ._scenario_model import (
    _REWARD_ACTIONS,
    ANCIENT_CHOICE_KEY_ORDER,
    COMBAT_ACTION,
    FAILURE_RECORD,
    NESTED_CHOICE_KEY_ORDER,
    NODE_KEY_ORDER,
    RECIPE_KEY_ORDER,
    ROW_KEY_ORDER,
    ROW_SCHEMA,
    SCENARIO_RECORD,
    STAGE_ANCIENT_CHOICE,
    STAGE_ANCIENT_ROOM,
    STAGE_FIRST_COMBAT,
    STAGE_LEAVE_ANCIENT,
    STAGE_ROW_ONE_NODE,
    STAGE_RUN_START,
    RunWorker,
    ScenarioGenerationError,
    ScenarioMaterializationError,
    _DrivenRun,
    _Element,
    _Recipe,
    _Stopped,
    canonicalize_seed,
)
from .ancient import (
    LEAVE_EVENT_ACTION,
    MAP_CHOICE,
    NestedDecision,
    ancient_action,
    choice_actions,
    drive_choice,
    map_actions,
)
from .client import RESET_MODE_RUN
from .schema import validate_observation


class CombatEpisode:
    """A live first combat reached by replaying a Generated scenario."""

    def __init__(self, worker: RunWorker, state: dict[str, Any]) -> None:
        self._worker = worker
        self._state = state
        initial_hp = self._reported_player_hp(state)
        if initial_hp is None:
            raise ScenarioMaterializationError("combat result does not report the player's HP")
        self._initial_hp = initial_hp
        self._latest_hp = self._initial_hp

    @property
    def observation(self) -> dict[str, Any]:
        """The combat's current canonical observation."""
        return self._state["observation"]

    @property
    def legal_actions(self) -> list[dict[str, Any]]:
        """Actions available while the combat is still live."""
        return [] if self.complete else list(self._state.get("legal_actions") or [])

    @property
    def complete(self) -> bool:
        """Whether control has left the combat, by victory or defeat."""
        return bool(self.observation.get("terminal")) or "combat" not in self.observation

    @property
    def outcome(self) -> str | None:
        """``victory`` or ``defeat`` once complete; otherwise ``None``."""
        if not self.complete:
            return None
        if self.observation.get("terminal") and not self.observation.get("victory"):
            return "defeat"
        return "victory"

    @property
    def hp_loss(self) -> int:
        """Net player HP lost since the recorded combat initial state."""
        return max(0, self._initial_hp - self._latest_hp)

    def step(self, action_id: str) -> dict[str, Any]:
        """Apply one legal action and return the resulting canonical observation."""
        if self.complete:
            raise RuntimeError("the combat episode is complete")
        self._state = self._worker.run_step(action_id)
        reported_hp = self._reported_player_hp(self._state)
        if reported_hp is not None:
            self._latest_hp = reported_hp
        return self.observation

    @staticmethod
    def _reported_player_hp(state: dict[str, Any]) -> int | None:
        scoring_hp = (state.get("scoring_features") or {}).get("current_hp")
        if isinstance(scoring_hp, int):
            return scoring_hp
        observation = state["observation"]
        creatures = (observation.get("combat") or {}).get("creatures") or []
        player = next((creature for creature in creatures if creature.get("side") == "Player"), None)
        return player.get("hp") if player is not None and isinstance(player.get("hp"), int) else None


def _first_mismatch(expected: Any, actual: Any, path: str = "$") -> str | None:
    """Return the first deterministic JSON path at which two values differ."""
    if type(expected) is not type(actual):
        return path
    if isinstance(expected, dict):
        for key in expected:
            child_path = f"{path}.{key}"
            if key not in actual:
                return child_path
            mismatch = _first_mismatch(expected[key], actual[key], child_path)
            if mismatch is not None:
                return mismatch
        for key in actual:
            if key not in expected:
                return f"{path}.{key}"
        return None
    if isinstance(expected, list):
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            mismatch = _first_mismatch(expected_item, actual_item, f"{path}[{index}]")
            if mismatch is not None:
                return mismatch
        return None if len(expected) == len(actual) else f"{path}[{min(len(expected), len(actual))}]"
    return None if expected == actual else path


def _require_record_keys(
    value: Any,
    required: set[str],
    optional: set[str],
    path: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioMaterializationError(f"invalid scenario row: {path} must be an object")
    missing = required - value.keys()
    if missing:
        key = next(key for key in required if key in missing)
        raise ScenarioMaterializationError(f"invalid scenario row: {path}.{key} is required")
    extra = value.keys() - required - optional
    if extra:
        key = next(iter(extra))
        raise ScenarioMaterializationError(f"invalid scenario row: {path}.{key} is not declared by {ROW_SCHEMA}")
    return value


def _require_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScenarioMaterializationError(f"invalid scenario row: {path} must be a non-empty string")
    return value


def _require_integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or minimum is not None and value < minimum:
        qualifier = f" at least {minimum}" if minimum is not None else ""
        raise ScenarioMaterializationError(f"invalid scenario row: {path} must be an integer{qualifier}")
    return value


def _validate_ancient_identity(value: Any, path: str) -> dict[str, Any]:
    identity = _require_record_keys(value, set(ANCIENT_CHOICE_KEY_ORDER), set(), path)
    _require_integer(identity["option_index"], f"{path}.option_index", minimum=0)
    _require_text(identity["relic_model_id"], f"{path}.relic_model_id")
    return identity


def _validated_scenario(
    scenario: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str, _Element]:
    row = _require_record_keys(scenario, set(ROW_KEY_ORDER[SCENARIO_RECORD]), set(), "$")
    game_build = _require_record_keys(
        row["game_build"], {"version", "assembly_sha256", "pck_sha256"}, set(), "$.game_build"
    )
    for key, value in game_build.items():
        _require_text(value, f"$.game_build.{key}")

    required_recipe_keys = set(RECIPE_KEY_ORDER) - {"raw_seed"}
    recipe = _require_record_keys(row["recipe"], required_recipe_keys, {"raw_seed"}, "$.recipe")
    character = _require_text(recipe["character"], "$.recipe.character")
    ascension = _require_integer(recipe["ascension"], "$.recipe.ascension", minimum=0)
    seed = _require_text(recipe["seed"], "$.recipe.seed")
    _require_text(recipe["act_variant"], "$.recipe.act_variant")
    _require_text(recipe["encounter"], "$.recipe.encounter")
    if canonicalize_seed(seed) != seed:
        raise ScenarioMaterializationError("invalid scenario row: $.recipe.seed is not canonical")
    if "raw_seed" in recipe:
        raw_seed = _require_text(recipe["raw_seed"], "$.recipe.raw_seed")
        if raw_seed == seed or canonicalize_seed(raw_seed) != seed:
            raise ScenarioMaterializationError("invalid scenario row: $.recipe.raw_seed does not resolve to the seed")

    options = recipe["ancient_options"]
    if not isinstance(options, list) or not options:
        raise ScenarioMaterializationError("invalid scenario row: $.recipe.ancient_options must be a non-empty array")
    for index, option in enumerate(options):
        _validate_ancient_identity(option, f"$.recipe.ancient_options[{index}]")
    ancient_choice = _validate_ancient_identity(recipe["ancient_choice"], "$.recipe.ancient_choice")
    if ancient_choice not in options:
        raise ScenarioMaterializationError("invalid scenario row: $.recipe.ancient_choice is not in ancient_options")

    nested_choices = recipe["nested_choices"]
    if not isinstance(nested_choices, list):
        raise ScenarioMaterializationError("invalid scenario row: $.recipe.nested_choices must be an array")
    for index, value in enumerate(nested_choices):
        path = f"$.recipe.nested_choices[{index}]"
        nested = _require_record_keys(value, set(NESTED_CHOICE_KEY_ORDER), set(), path)
        _require_text(nested["kind"], f"{path}.kind")
        _require_integer(nested["selected_index"], f"{path}.selected_index", minimum=0)
        option_ids = nested["selected_option_ids"]
        if not isinstance(option_ids, list) or any(not isinstance(option_id, str) for option_id in option_ids):
            raise ScenarioMaterializationError(
                f"invalid scenario row: {path}.selected_option_ids must be a string array"
            )

    node = _require_record_keys(recipe["node"], set(NODE_KEY_ORDER), set(), "$.recipe.node")
    _require_integer(node["col"], "$.recipe.node.col", minimum=0)
    _require_integer(node["row"], "$.recipe.node.row", minimum=0)
    _require_text(node["point_type"], "$.recipe.node.point_type")

    recorded_observation = row["combat_initial_state"]
    try:
        validate_observation(recorded_observation)
    except ValueError as error:
        raise ScenarioMaterializationError(f"invalid scenario row: $.combat_initial_state: {error}") from error
    recorded_hash = _require_text(row["state_hash"], "$.state_hash")
    if recorded_observation["game_build"] != game_build:
        raise ScenarioMaterializationError("invalid scenario row: $.game_build differs from combat_initial_state")
    recorded_run = recorded_observation["run"]
    for key in ("seed", "ascension", "act_variant"):
        if recorded_run.get(key) != recipe[key]:
            raise ScenarioMaterializationError(
                f"invalid scenario row: $.recipe.{key} differs from combat_initial_state.run.{key}"
            )
    if (recorded_observation.get("combat") or {}).get("encounter") != recipe["encounter"]:
        raise ScenarioMaterializationError(
            "invalid scenario row: $.recipe.encounter differs from combat_initial_state.combat.encounter"
        )
    if recorded_observation["decision"]["kind"] != COMBAT_ACTION:
        raise ScenarioMaterializationError("invalid scenario row: $.combat_initial_state is not a live combat")

    player = next(
        (creature for creature in recorded_observation["combat"]["creatures"] if creature.get("side") == "Player"),
        None,
    )
    if player is None or player.get("model_id") != character:
        raise ScenarioMaterializationError("invalid scenario row: $.recipe.character differs from the combat's player")
    return recipe, recorded_observation, recorded_hash, _Element(character, ascension, seed, seed)


def materialize_scenario(scenario: dict[str, Any], worker: RunWorker) -> CombatEpisode:
    """Replay one Generated scenario into ``worker`` and return its live first combat."""
    if scenario.get("schema") != ROW_SCHEMA:
        raise ScenarioMaterializationError(f"unsupported scenario schema {scenario.get('schema')!r}")
    if scenario.get("record_type") != SCENARIO_RECORD:
        raise ScenarioMaterializationError("materialization requires a scenario row")
    recipe, recorded_observation, recorded_hash, element = _validated_scenario(scenario)

    state = worker.run_reset(_reset_state(element))
    actual_variant = state["observation"]["run"].get("act_variant")
    if actual_variant != recipe["act_variant"]:
        raise ScenarioMaterializationError(
            f"act_variant mismatch: expected {recipe['act_variant']!r}, got {actual_variant!r}"
        )
    ancient = ancient_action(state)
    if ancient is None:
        raise ScenarioMaterializationError("recipe mismatch: the run does not start at its Ancient")
    state = worker.run_step(ancient["action_id"])

    recorded_ancient = recipe["ancient_choice"]
    offered = _offered_choices(state)
    actual_offer = [identity for identity, _ in offered]
    if actual_offer != recipe["ancient_options"]:
        raise ScenarioMaterializationError(
            f"Ancient options mismatch: expected {recipe['ancient_options']!r}, got {actual_offer!r}"
        )
    choice = next((action for identity, action in offered if identity == recorded_ancient), None)
    if choice is None:
        raise ScenarioMaterializationError(f"recipe mismatch: Ancient choice {recorded_ancient!r} is not offered")

    nested_choices = recipe["nested_choices"]
    nested_index = 0

    def choose_nested(prompt: dict[str, Any]) -> str:
        nonlocal nested_index
        if nested_index >= len(nested_choices):
            raise ScenarioMaterializationError("recipe mismatch: the Ancient opened an unrecorded nested choice")
        recorded = nested_choices[nested_index]
        actual_kind = prompt["observation"]["decision"]["kind"]
        if recorded.get("kind") != actual_kind:
            raise ScenarioMaterializationError(
                f"recipe mismatch: nested choice {nested_index} is {actual_kind!r}, not {recorded.get('kind')!r}"
            )
        actions = prompt.get("legal_actions") or []
        selected_index = recorded.get("selected_index")
        if not isinstance(selected_index, int) or not 0 <= selected_index < len(actions):
            raise ScenarioMaterializationError(
                f"recipe mismatch: nested choice {nested_index} has unavailable selected index {selected_index!r}"
            )
        action = actions[selected_index]
        selected_option_ids = (action.get("parameters") or {}).get("option_ids") or []
        if recorded.get("selected_option_ids") != selected_option_ids:
            raise ScenarioMaterializationError(
                f"recipe mismatch: nested choice {nested_index} option ids are {selected_option_ids!r}, "
                f"not {recorded.get('selected_option_ids')!r}"
            )
        nested_index += 1
        return action["action_id"]

    try:
        drive_choice(worker, choice, choose=choose_nested)
    except ValueError as error:
        raise ScenarioMaterializationError(f"recipe mismatch: {error}") from error
    if nested_index != len(nested_choices):
        raise ScenarioMaterializationError(
            f"recipe mismatch: {len(nested_choices) - nested_index} recorded nested choice(s) were not opened"
        )

    state = worker.run_step(LEAVE_EVENT_ACTION)
    recorded_node = recipe["node"]
    node = next(
        (
            action
            for action in map_actions(state)
            if all((action.get("parameters") or {}).get(key) == recorded_node.get(key) for key in NODE_KEY_ORDER)
        ),
        None,
    )
    if node is None:
        raise ScenarioMaterializationError(f"recipe mismatch: map node {recorded_node!r} is not reachable")
    combat = worker.run_step(node["action_id"])

    actual_observation = combat["observation"]
    actual_encounter = (actual_observation.get("combat") or {}).get("encounter")
    if actual_encounter != recipe["encounter"]:
        raise ScenarioMaterializationError(
            f"encounter mismatch: expected {recipe['encounter']!r}, got {actual_encounter!r}"
        )
    mismatch = _first_mismatch(recorded_observation, actual_observation)
    if mismatch is not None:
        raise ScenarioMaterializationError(f"combat_initial_state mismatch at {mismatch}")
    if combat.get("state_hash") != recorded_hash:
        raise ScenarioMaterializationError(
            f"state_hash mismatch: expected {recorded_hash!r}, got {combat.get('state_hash')!r}"
        )
    return CombatEpisode(worker, combat)


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
            f"leaving the Ancient room returned {state['observation']['decision']['kind']!r} instead of the run's map",
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

    ``reset_mode`` is ``run`` because this is a run reset: the run stands on its map and no combat
    is built, so the fight the generation goes on to record is the fight the run really plays. The
    environment stands up the reset a caller asks for by name when the request declares nothing, and
    refuses a request that declares the other mode, so this is the generator stating which of the two
    it is asking for — and it is what the branch a record is replayed from carries.
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
        "reset_mode": RESET_MODE_RUN,
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
    row["recipe"].update(
        {
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
        }
    )
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
