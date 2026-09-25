"""Internal live-run driver and Generated scenario materialization."""

from __future__ import annotations

import copy
from typing import Any

from ._scenario_codec import _refuse_floats, error_kind
from ._scenario_model import (
    _REWARD_ACTIONS,
    ANCIENT_CHOICE_KEY_ORDER,
    BRANCHING_PROMPT_KINDS,
    COMBAT_ACTION,
    FAILURE_RECORD,
    NESTED_CHOICE_KEY_ORDER,
    NODE_KEY_ORDER,
    RECIPE_KEY_ORDER,
    REWARD_CHOICE_KEY_ORDER,
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
    _OpenedPrompts,
    _Recipe,
    _Stopped,
    canonicalize_seed,
)
from .ancient import (
    LEAVE_EVENT_ACTION,
    MAP_CHOICE,
    ancient_action,
    choice_actions,
    drive_choice,
    map_actions,
)
from .client import RESET_MODE_RUN
from .schema import validate_observation

_UNSUPPORTED_INTERACTIVE_FIRST_COMBAT_RELICS = frozenset({"GAMBLING_CHIP"})


class UnsupportedInteractiveFirstCombatRelic(RuntimeError):
    """A held relic opens a first-combat decision the scenario recipe cannot record."""


class CombatEpisode:
    """A live first combat reached by replaying a Generated scenario."""

    def __init__(self, worker: RunWorker, state: dict[str, Any]) -> None:
        self._worker = worker
        validate_observation(state["observation"])
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
        next_state = self._worker.run_step(action_id)
        validate_observation(next_state["observation"])
        self._state = next_state
        reported_hp = self._reported_player_hp(next_state)
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


def _validated_reward_identity(value: Any, path: str) -> dict[str, Any]:
    """One recorded reward pick's identity, in the shape the environment reports a reward in.

    A reward set may nest a linked reward set, which is what `child_index` names — `-1` for a reward
    that is not a child — and a card reward names the option of its own card list; the model is the
    reward's subject and is absent for a reward that has none, such as gold.
    """
    identity = _require_record_keys(value, set(REWARD_CHOICE_KEY_ORDER), set(), path)
    _require_integer(identity["reward_index"], f"{path}.reward_index", minimum=0)
    _require_integer(identity["child_index"], f"{path}.child_index")
    _require_integer(identity["option_index"], f"{path}.option_index", minimum=0)
    _require_text(identity["reward_kind"], f"{path}.reward_kind")
    if identity["model_id"] is not None:
        _require_text(identity["model_id"], f"{path}.model_id")
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
        nested = _require_record_keys(
            value, set(NESTED_CHOICE_KEY_ORDER) - {"selected_reward"}, {"selected_reward"}, path
        )
        _require_text(nested["kind"], f"{path}.kind")
        _require_integer(nested["selected_index"], f"{path}.selected_index", minimum=0)
        option_ids = nested["selected_option_ids"]
        if not isinstance(option_ids, list) or any(not isinstance(option_id, str) for option_id in option_ids):
            raise ScenarioMaterializationError(
                f"invalid scenario row: {path}.selected_option_ids must be a string array"
            )
        if "selected_reward" in nested:
            _validated_reward_identity(nested["selected_reward"], f"{path}.selected_reward")

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
        recorded_reward = recorded.get("selected_reward")
        actual_reward = _reward_identity(action)
        if recorded_reward is not None and actual_reward != recorded_reward:
            raise ScenarioMaterializationError(
                f"recipe mismatch: nested choice {nested_index} is the reward {actual_reward!r}, "
                f"not the recorded {recorded_reward!r}"
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
    """Every row one element of the request produces: one per opening branch its run offers.

    The run starts once, then its Ancient offer's returned handle is kept before taking any
    choice. Each offered choice contributes the branches its own pick-up opens — the non-skip
    options of a reward or option prompt, or the single drive of a choice that opens none — and a
    branch that fails gets its own failure row while its siblings are still driven.
    """
    build = worker.build
    attempted = _Recipe(element, build)
    try:
        choices, checkpoint = _open_ancient(attempted, worker)
    except Exception as error:  # noqa: BLE001
        if attempted.offered is None:
            return [_failure_row(attempted, error)]
        return [
            _failure_row(
                _Recipe(element, build, stage=STAGE_ANCIENT_CHOICE,
                        act_variant=attempted.act_variant, ancient_choice=choice),
                error,
            )
            for choice in attempted.offered
        ]

    assert attempted.offered is not None
    rows: list[dict[str, Any]] = []
    for choice_index, choice in enumerate(choices):
        rows.extend(
            _element_row(recipe, outcome)
            for recipe, outcome in _choice_branches(
                attempted, choice, choice_index, worker, checkpoint
            )
        )
    return rows


def _choice_branches(
    attempted: _Recipe,
    choice: tuple[dict[str, Any], dict[str, Any]],
    choice_index: int,
    worker: RunWorker,
    checkpoint: str,
) -> list[tuple[_Recipe, _DrivenRun | _Stopped]]:
    """Every branch one offered Ancient choice produces, in the order its prompt offered them.

    The choice is driven once to find the prompt its pick-up opens. When that is a prompt this
    generation branches on — the drive met exactly one prompt, and it offers whole options — every
    non-skip option it offers is a branch of its own, each driven from the offered state the run
    was left in. The branch the finding drive itself took is that drive's row rather than a second
    run of the same option. Anything a branch opens after that first prompt is resolved by the
    fixed rule, until the chained-choice policy replaces it.

    A choice whose drive met no prompt, met a card select, or met a prompt and then another keeps
    the single row its own drive produced: those are the cardinalities later tickets own, and none
    of them is a branch this generation invents. The finding drive is what says how many prompts the
    choice opens, so a prompt that offers a skip first spends that drive on a branch no row records;
    the reward and option prompts an act-1 Ancient reaches offer their options first.
    """
    identity, action = choice
    offered = attempted.offered
    assert offered is not None, "a choice is branched only after its run's offer has been read"
    probe_recipe = _branch_recipe(attempted, identity)
    prompt = _OpenedPrompts()
    probe = _drive_safely(
        probe_recipe, action, offered, worker, checkpoint if choice_index else None, prompt=prompt
    )
    options = _options_to_branch_on(prompt)
    if options is None:
        return [(probe_recipe, probe)]

    branches: list[tuple[_Recipe, _DrivenRun | _Stopped]] = []
    for option in options:
        if option["action_id"] == prompt.selected_action:
            branches.append((probe_recipe, probe))
            continue
        recipe = _branch_recipe(attempted, identity)
        branches.append((
            recipe,
            _drive_safely(recipe, action, offered, worker, checkpoint, selection=option["action_id"]),
        ))
    return branches


def _branch_recipe(attempted: _Recipe, identity: dict[str, Any]) -> _Recipe:
    """One branch's recipe: the element as far as the Ancient offer resolved it.

    Every branch of one choice starts from what the element and the offer already resolved — the
    build, the Act variant the run reports, the choices it offered and the choice this branch is
    for — and records the nested choices the branch's own drive takes.
    """
    return _Recipe(
        attempted.element,
        attempted.build,
        act_variant=attempted.act_variant,
        offered=attempted.offered,
        ancient_choice=identity,
    )


def _options_to_branch_on(prompt: _OpenedPrompts) -> list[dict[str, Any]] | None:
    """The options one Ancient choice's pick-up is branched on, or ``None`` when it is not branched.

    A prompt is branched on when the drive met exactly one of them and it offers whole options;
    a skip is not an option, because declining a prompt is not an opening this generation records
    as a situation of its own. A prompt with no option to take leaves the choice its single drive,
    so an offered choice still contributes a row rather than silently contributing none.
    """
    if prompt.count != 1 or prompt.kind not in BRANCHING_PROMPT_KINDS:
        return None
    return [action for action in prompt.actions if not _is_skip(action)] or None


def _is_skip(action: dict[str, Any]) -> bool:
    """Whether one prompt action declines the prompt rather than taking an option from it.

    A reward set spells its skip as an action of its own (``skip_custom_rewards``), and an option
    pick whose minimum selection is zero spells it as a selection of nothing — the empty selection
    the environment emits first, which is what a relic pick's offered relics sit behind. Either way
    the fact is the same to a caller: the branch declines the prompt instead of taking an option
    from it, so it is not an opening this generation records a row for.
    """
    kind = action.get("kind") or ""
    if kind.startswith("skip"):
        return True
    return kind == "choose_option" and not (action.get("parameters") or {}).get("option_ids")


def _open_ancient(recipe: _Recipe, worker: RunWorker) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], str]:
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
    recipe.offered = [identity for identity, _ in choices]
    return choices, state["state_handle"]


def _drive_safely(
    recipe: _Recipe,
    choice: dict[str, Any],
    offered: list[dict[str, Any]],
    worker: RunWorker,
    checkpoint: str | None,
    *,
    prompt: _OpenedPrompts | None = None,
    selection: str | None = None,
) -> _DrivenRun | _Stopped:
    """Drive one run, handing back the failure instead of raising it.

    Whatever goes wrong is this branch's failure, not the batch's: it is recorded — stage, kind and
    message — rather than raised, so the caller keeps the rest of the offer and of the choice's own
    options. ``checkpoint`` is the state the Ancient offer was left in; a drive that is not the
    element's first continues from it, and a branch always starts there because the drive that found
    its prompt has already walked the run away from it. ``prompt`` is where a drive reports the
    prompts it meets, and a drive handed none still needs one, because which prompt is the first is
    what ``selection`` — the option a branch takes — is taken from.
    """
    try:
        recipe.stage = STAGE_ANCIENT_CHOICE
        if checkpoint is not None:
            worker.restore(checkpoint)
        return _drive_to_first_fight(
            recipe, choice, offered, worker, prompt if prompt is not None else _OpenedPrompts(), selection
        )
    except Exception as error:  # noqa: BLE001
        return _Stopped(error)


def _element_row(recipe: _Recipe, outcome: _DrivenRun | _Stopped) -> dict[str, Any]:
    """One branch's row: the scenario its drive reached, or the failure that stopped it.

    Recording the scenario can fail too — a nested selection the prompt does not report is a
    failure of that branch's record — and that is a failure row like any other.
    """
    if isinstance(outcome, _Stopped):
        return _failure_row(recipe, outcome.error)
    try:
        return _row(recipe, outcome)
    except Exception as error:  # noqa: BLE001
        return _failure_row(recipe, error)


def _drive_to_first_fight(
    recipe: _Recipe,
    choice: dict[str, Any],
    offered: list[dict[str, Any]],
    worker: RunWorker,
    prompt: _OpenedPrompts,
    selection: str | None,
) -> _DrivenRun:
    """Drive one Ancient choice from its offered state to the first fight.

    The recipe is stamped before every phase, so a failure that names no stage of its own — a
    worker's error, or a bug — is still attributed to the phase the drive was in, and every nested
    choice the drive takes is recorded into it as it is taken, so a drive that stops after a
    selection still says what it selected.
    """

    def choose(state: dict[str, Any]) -> str:
        pick = _selection_at(prompt, selection, state)
        recipe.nested.append(_nested_choice(state, pick))
        return pick

    recipe.stage = STAGE_ANCIENT_CHOICE
    try:
        drive_choice(worker, choice, choose=choose)
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
    # A map observation has no inventory; the worker's scoring features report the full
    # held set after the Ancient, including relics the selected option granted indirectly.
    held_relics = (state.get("scoring_features") or {}).get("relics")
    if not isinstance(held_relics, list) or any(not isinstance(relic, str) for relic in held_relics):
        raise ScenarioGenerationError(STAGE_FIRST_COMBAT, "the map result does not report the final relic set")
    unsupported = sorted(set(held_relics) & _UNSUPPORTED_INTERACTIVE_FIRST_COMBAT_RELICS)
    if unsupported:
        raise UnsupportedInteractiveFirstCombatRelic(
            f"unsupported interactive first-combat relics: {', '.join(unsupported)}"
        )
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
        node=node,
        observation=observation,
        state_hash=combat["state_hash"],
    )


def _selection_at(prompt: _OpenedPrompts, selection: str | None, state: dict[str, Any]) -> str:
    """The action this drive takes from the prompt it is standing at.

    The first prompt a drive meets is the one the branch was enumerated from, so that is where the
    branch's own option is forced — and where the prompt's kind and options are remembered, before
    the option is taken, so a drive that stops there still reports what it was standing at. Every
    prompt after the first is resolved by the fixed rule: the first legal action the run offers,
    which is what the generator records for a prompt kind it does not branch on.
    """
    first = prompt.count == 0
    prompt.meet(state)
    if first and selection is not None:
        offered = state.get("legal_actions") or []
        if not any(action.get("action_id") == selection for action in offered):
            raise ScenarioGenerationError(
                STAGE_ANCIENT_CHOICE,
                f"the prompt a branch was enumerated from no longer offers {selection!r}",
            )
        pick = selection
    else:
        pick = state["legal_actions"][0]["action_id"]
    if first:
        prompt.selected_action = pick
    return pick


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


def _is_proceed(parameters: dict[str, Any]) -> bool:
    """Whether one reported option or action ends the Ancient room instead of taking a blessing.

    The environment reports the flag on both views of an option. A run that takes it holds no new
    relic and stands in no new situation, so it is no choice of this generation's: not an offer a
    row enumerates, and — because the offer a row records is the choices it branches on — not part
    of the recorded offer either.
    """
    return parameters.get("is_proceed") is True


def _offered_choices(state: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """The Ancient's offered choices: each option the event reports, with the action that takes it.

    The options and the decision's legal actions are two views of one offer, so they are matched
    by option index and any disagreement is a staged failure rather than a quietly different
    corpus: an option no action can take would be recorded as offered while being impossible, and
    a legal choice the event does not report would leave the run opening unrecorded. That match is
    what makes "a seed records exactly the choices its run offers" a checked claim rather than a
    count taken from one list and an index taken from another. An option that takes no blessing —
    a proceed, which ends the room — is neither, so both views of it are dropped here.
    """
    event = state["observation"].get("event")
    if not isinstance(event, dict):
        raise ScenarioGenerationError(STAGE_ANCIENT_ROOM, "the Ancient node did not open the Ancient's event room")

    takers: dict[Any, tuple[dict[str, Any], dict[str, Any]]] = {}
    for action in choice_actions(state):
        if _is_proceed(action.get("parameters") or {}):
            continue
        identity = _choice_identity(action.get("parameters") or {})
        index = identity["option_index"]
        if index in takers:
            raise ScenarioGenerationError(STAGE_ANCIENT_CHOICE, f"the Ancient offers two choices at option {index}")
        takers[index] = (identity, action)

    offered: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for option in event.get("options") or []:
        if _is_proceed(option):
            continue
        reported = _choice_identity(option)
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
            "nested_choices": copy.deepcopy(recipe.nested),
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
    # quantity the record cannot carry is still this choice's failure instead of a dead batch.
    _refuse_floats(row)
    return row


def _failure_row(recipe: _Recipe, error: BaseException) -> dict[str, Any]:
    """One failure row: the stage, the error, and the recipe resolved so far.

    A failure row never carries a combat initial state, partial or otherwise: its whole claim is
    that no scenario was produced, so there is no state to carry and no simulator hash of one. Its
    recipe names what the element resolved — the declaration, the Act variant the run reports, the
    Ancient choice the element is for once the run has offered one, and every nested choice the
    branch took before it stopped — and never a field of the fight, because the row's stage already
    says how far the drive got. The nested choices are what tells one failed option of a choice
    from its sibling's failure, which would otherwise be the same row twice.
    """
    stage, message = _staged_failure(recipe, error)
    row = _envelope(recipe, FAILURE_RECORD)
    if recipe.act_variant is not None:
        row["recipe"]["act_variant"] = recipe.act_variant
    if recipe.ancient_choice is not None:
        row["recipe"]["ancient_choice"] = dict(recipe.ancient_choice)
    if recipe.nested:
        row["recipe"]["nested_choices"] = copy.deepcopy(recipe.nested)
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


def _nested_choice(state: dict[str, Any], action_id: str) -> dict[str, Any]:
    """One nested decision, and the action this drive took from it.

    The action is named by its position among the prompt's legal actions — which is what a replay
    takes from — and by what it selected: the option ids it names, for a prompt that offers options,
    or the reward's own identity for a reward pick, which names none. An action that says neither is
    a failure of this branch's record rather than a selection of nothing.
    """
    actions = state.get("legal_actions") or []
    picked = next(
        ((index, action) for index, action in enumerate(actions) if action.get("action_id") == action_id),
        None,
    )
    if picked is None:
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the nested choice took {action_id!r}, which the prompt did not offer",
        )
    index, action = picked
    parameters = action.get("parameters") or {}
    option_ids = parameters.get("option_ids")
    reward = _reward_identity(action)
    if reward is None and option_ids is None and action.get("kind") not in _REWARD_ACTIONS:
        # An action that selects options has to say which; a record that quietly stored an
        # empty selection would look like a choice of nothing rather than a missing fact.
        raise ScenarioGenerationError(
            STAGE_ANCIENT_CHOICE,
            f"the {action.get('kind')!r} action {action_id!r} names no option ids",
        )
    recorded = {
        "kind": state["observation"]["decision"]["kind"],
        "selected_index": index,
        "selected_option_ids": list(option_ids) if isinstance(option_ids, list) else [],
    }
    if reward is not None:
        recorded["selected_reward"] = reward
    return recorded


def _reward_identity(action: dict[str, Any]) -> dict[str, Any] | None:
    """The reward one action takes, as the identity a record carries, or ``None`` for any other action.

    A reward pick's own parameters are what identify it — which reward of its set, which child of a
    linked reward set if any, which option of a card reward, and the kind and model the reward is —
    and they are read in the record's declared order rather than the order the action happened to
    report them in, because a record's bytes are the record's.
    """
    if action.get("kind") != "choose_custom_reward":
        return None
    parameters = action.get("parameters") or {}
    return {key: parameters.get(key) for key in REWARD_CHOICE_KEY_ORDER}


# -- the corpus a batch writes -----------------------------------------------------------
