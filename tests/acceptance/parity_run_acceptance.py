#!/usr/bin/env python3
"""Field-by-field parity run: a fixed sample of generated scenarios against the shipped game.

This is the acceptance gate for the act-1 combat-1 feature. For each sample the *record* — the
scenario the generator produces for one character, Ascension, canonical run seed and Ancient choice —
and the *shipped game* driven to the same situation are both fed through
``sts2_native_sim.parity_projection``, and the two projections are compared field by field with the
repository's own per-path helper, so a mismatch names the field path that differed rather than a hash
that disagrees.

What the run does, per sample:

* the record is produced by the generator's public interface (``generate_rows``) on a native worker,
  a row per offered Ancient choice and per option of a single reward or option prompt under it, so
  the sample takes the rows for the choices it names — and a sample whose element produced a failure
  row fails here naming the stage and the error rather than being read as a scenario. A choice whose
  pick-up opens such a prompt owns several rows and this sample declares no option, so it fails
  rather than comparing whichever row was recorded last: those branches are the nested-parity
  sample's to compare;
* a real headless ``SlayTheSpire2.exe`` is launched with the same character and driven from
  ``start_run`` with the record's canonical seed and Ascension, through the Ancient room, taking the
  recorded Ancient choice, answering every nested prompt the way the record's own nested choice
  answered it, travelling to the recorded row-1 node coordinate, and stopping at the first fight — the
  moment the record is a recording of;
* the fight's observation and the record's combat initial state are projected into the contract's one
  shape and compared, and the report names the first field that differed with both values, the number of
  fields that moved and the paths of all of them. The situation's givens — the coordinate the drive
  stands on, the relic the choice granted, the encounter — are checked and reported beside the
  comparison, because the map coordinate is not a contract field and a drive that reached a different
  node is not a parity result.

The sample, and what it covers
------------------------------

:data:`SAMPLE` is fixed: sixteen scenarios over two characters (IRONCLAD, DEFECT) and two Ascensions
(0 and 2), on twelve distinct runs, taking every Ancient choice of each run that this seam can drive.
Which nested-choice kinds that came to is *measured* and reported, and what the sample does **not**
cover is named in :data:`NESTED_KINDS_NOT_COVERED`: a bundle or relic *option* pick has no selector
branch in the shipped game, as ticket 14 measured, and a *reward set* is not driven by this sample at
all. So nothing here claims complete Ancient-choice coverage; it claims the choices it names and the
nested kinds it actually drove.

The default run requires certification and executes the complete fixed set through one serial reusable
worker and sandbox: the first entry uses the menu path, and subsequent entries use direct warm starts.
``--process-mode fresh`` starts one menu-path process per entry, including on uncertified builds.
Ordinary parity reads certification but never issues it.

Both Act variants are ordinary compared scenarios. The full-app sandbox materializes every Act as
discovered before it becomes ready, so ``ActModel.GetRandomList`` follows the run seed instead of the
first-discovery override; the shipped-game oracle and simulator therefore reach the same variant.

What is never compared
----------------------

No state hash, at any point, on either side. The two encoders hash different things (one hashes a
versioned observation plus a transition kernel, the other its own DTO with neither), so a hash match
would prove nothing; the projections never read one, and the report states the number of hashes
compared, which is zero.

Requires the shipped game (the repository's ``*_acceptance.py`` convention), a configured
``STS2_GAME_ROOT``, and a sandbox root on the install's own volume — the sandbox is hard-linked beside
the install, so a sandbox on another volume would copy 11 GB instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from sts2_native_sim import NativeWorkerPool
from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig
from sts2_native_sim.parity_projection import (
    CONTRACT_FIELDS,
    EXCLUDED_FIELDS,
    OPTIONAL_FIELDS,
    ContractComparison,
    compare_contract,
    project_bridge,
    project_record,
    shape_paths,
)
from sts2_native_sim.paths import REPOSITORY_ROOT
from sts2_native_sim.reusable_full_app_worker import ReusableFullAppWorker, RunEntry
from sts2_native_sim.reuse_certification import (
    CertificationError,
    current_certification_identity,
    require_certificate,
)
from sts2_native_sim.scenarios import SCENARIO_RECORD, ScenarioRequest, generate_rows

#: The stage word the bridge reports while a flat card-set prompt is open, the action type that
#: selects one of the cards it offers, and the action that leaves it with what has been chosen — which
#: is also how a prompt whose minimum is zero is skipped. Ticket 14 established this seam.
CARD_SELECT_STAGE = "simple_card_select"
CARD_SELECT_ACTION = "choose_card_select"
CARD_SELECT_FINISH = "finish_card_select"

#: The decision kind the record's own nested choices are described in. Only a card select can be
#: driven here; :data:`NESTED_KINDS_NOT_COVERED` says which kinds this sample does not drive.
CARD_SELECT_KIND = "card_choice"

#: How many decisions the drive to the first fight may take, so a stall names where it stalled.
MAX_STEPS = 40

#: The nested-choice kinds this run does *not* cover, each with the reason — stated so that no reader
#: mistakes this sample for complete Ancient-choice coverage.
NESTED_KINDS_NOT_COVERED: dict[str, str] = {
    "option_choice": (
        "a bundle or relic option pick has no selector branch in the shipped game, so its screen is answered by the "
        "shipped autoplay's own handler and no stage is reported for it — measured by "
        "`python/bridge_card_select_acceptance.py` on `GYMSCENAR10`'s second choice"
    ),
    "custom_reward_choice": (
        "a reward set a relic's pick-up opens is a stage the bridge reports in its own right, and this sample does not "
        "drive one: no sample here takes a choice whose pick-up offers a reward set"
    ),
}

#: The nested-choice kinds the sample is built to drive. What the run *measured* is reported beside
#: this declaration, and a full run whose measurement disagrees with it is not a success: a sample
#: that stopped opening the prompt it was chosen for would otherwise claim coverage it does not have.
NESTED_KINDS_COVERED = (CARD_SELECT_KIND,)


@dataclass(frozen=True)
class Run:
    """The run a record was recorded on: the dimension the generator is asked for."""

    character: str
    ascension: int
    seed: str


@dataclass(frozen=True)
class Sample:
    """One generated scenario to compare with the shipped game.

    The four fields are the identity a record's own recipe carries — the character, the Ascension, the
    canonical run seed and the Ancient choice's offer index — and ``relic`` is the relic the build
    below offered at that index, so a sample that stopped naming the same choice fails loudly instead
    of quietly comparing a different one.
    """

    character: str
    ascension: int
    seed: str
    option_index: int
    relic: str

    @property
    def run(self) -> Run:
        """The run this sample belongs to, so two samples of one run are recorded once."""
        return Run(self.character, self.ascension, self.seed)

    @property
    def label(self) -> str:
        return f"{self.character}@A{self.ascension}/{self.seed}#{self.option_index}"


@dataclass(frozen=True)
class _Record:
    """One recorded scenario: the recipe that reaches the fight, and the fight's initial state."""

    recipe: dict[str, Any]
    state: dict[str, Any]


@dataclass(frozen=True)
class _RecordedRun:
    """What the generator recorded for one run: the rows of each Ancient choice, and any failures.

    A choice whose pick-up opens a single reward or option prompt contributes one row per non-skip
    option of it, so the rows of one choice are a list — and a sample that names only the choice
    cannot say which of them it means.
    """

    rows: dict[int, list[_Record]]
    failures: list[dict[str, Any]]


#: The fixed sample: sixteen scenarios over two characters (IRONCLAD, DEFECT) and two Ascensions (0
#: and 2), on twelve distinct runs, taking every Ancient choice of each run that this seam can drive. The
#: relic named is the one the build this run reports offered at that index, so a sample that stopped
#: naming the same choice fails loudly rather than quietly comparing a different one. Both Act 1
#: variants are represented and compared under the shared progression-complete baseline.
SAMPLE: tuple[Sample, ...] = (
    Sample("IRONCLAD", 0, "ANC1ENT10", 0, "LEAD_PAPERWEIGHT"),
    Sample("IRONCLAD", 0, "ANC1ENT10", 1, "PRECISE_SCISSORS"),
    Sample("IRONCLAD", 0, "ANC1ENT10", 2, "LARGE_CAPSULE"),
    Sample("IRONCLAD", 0, "ANC1ENT17", 0, "FISHING_ROD"),
    Sample("IRONCLAD", 0, "ANC1ENT17", 2, "SILKEN_TRESS"),
    Sample("IRONCLAD", 0, "ANC1ENT18", 0, "ARCANE_SCROLL"),
    Sample("IRONCLAD", 0, "ANC1ENT18", 2, "CURSED_PEARL"),
    Sample("IRONCLAD", 0, "ACTVAR1ANT07", 1, "POMANDER"),
    Sample("IRONCLAD", 2, "ANC1ENT19", 1, "NEW_LEAF"),
    Sample("IRONCLAD", 2, "ANC1ENT22", 0, "NEW_LEAF"),
    Sample("DEFECT", 0, "ANC1ENT10", 1, "PRECISE_SCISSORS"),
    Sample("DEFECT", 0, "ACTVAR1ANT07", 1, "POMANDER"),
    Sample("DEFECT", 2, "ANC1ENT19", 2, "HEFTY_TABLET"),
    Sample("DEFECT", 2, "ANC1ENT22", 2, "PRECARIOUS_SHEARS"),
    Sample("IRONCLAD", 0, "SCENAR10A01", 0, "ARCANE_SCROLL"),
    Sample("IRONCLAD", 0, "ANC1ENT01", 0, "BOOMING_CONCH"),
)

SCENARIO_SET_REVISION = "act1-combat1-v1-" + hashlib.sha256(
    json.dumps([[sample.label, sample.relic] for sample in SAMPLE], separators=(",", ":")).encode("utf-8")
).hexdigest()[:16]
CERTIFICATE_PATH = REPOSITORY_ROOT / "certifications" / "full-app-reuse.json"
CERTIFICATION_REPORT_PATH = REPOSITORY_ROOT / "artifacts" / "reuse-certification" / "report.json"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _records(pool: NativeWorkerPool, samples: tuple[Sample, ...]) -> dict[Run, _RecordedRun]:
    """Every row the generator records for the runs the sample names, by Ancient choice index.

    The generator's public interface is the only thing used here: a request in, rows out. One call per
    distinct run enumerates that run's Ancient choices and the options their prompts open, which is
    what lets a sample name a choice by index and fail when the run no longer offers one.
    """
    runs: dict[Run, _RecordedRun] = {}
    for index, run in enumerate(dict.fromkeys(sample.run for sample in samples)):
        request = ScenarioRequest(characters=(run.character,), ascensions=(run.ascension,), seeds=(run.seed,))
        rows = generate_rows(request, pool.workers[index % len(pool.workers)])
        recorded: dict[int, list[_Record]] = {}
        for row in rows:
            if row["record_type"] != SCENARIO_RECORD:
                continue
            option_index = row["recipe"]["ancient_choice"]["option_index"]
            recorded.setdefault(option_index, []).append(_Record(row["recipe"], row["combat_initial_state"]))
        runs[run] = _RecordedRun(
            rows=recorded,
            # An element that could not produce a scenario is recorded as a failure row, and that row
            # is the element's own answer: it is kept beside the successes so a sample with no row can
            # say what happened rather than reporting a missing key.
            failures=[row for row in rows if row["record_type"] != SCENARIO_RECORD],
        )
    return runs


def _record_for(sample: Sample, runs: dict[Run, _RecordedRun]) -> _Record:
    """The row one sample compares, or the failure that stands in its place.

    A sample names a character, an Ascension, a seed and an Ancient choice, which is not enough to
    pick between the rows of a choice whose pick-up opens a reward or option prompt: those rows are
    that prompt's options, and this sample declares no option. Such a sample fails here, naming what
    it cannot choose between, rather than comparing whichever row happened to be recorded last.
    """
    recorded = runs[sample.run]
    branches = recorded.rows.get(sample.option_index, [])
    if len(branches) == 1:
        return branches[0]
    if branches:
        raise AssertionError(
            f"the generator recorded {len(branches)} rows for {sample.label}: the choice's pick-up opens a "
            "prompt whose options are branched on, and this sample declares no option of it — the nested "
            "branches are the nested-parity sample's to compare"
        )
    if recorded.failures:
        failure = recorded.failures[0]
        raise AssertionError(
            f"the generator recorded no scenario for {sample.label}: the run failed at {failure['stage']} — "
            f"{failure['error']['kind']}: {failure['error']['message']}"
        )
    raise AssertionError(
        f"the generator recorded no scenario for {sample.label}: the run offers choices "
        f"{sorted(recorded.rows)}, which the Ancient choice index {sample.option_index} is not among"
    )


def _answer_card_select(
    client: FullAppBridgeClient, nested: list[dict[str, Any]], cursor: int,
    capture: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int, dict[str, Any]]:
    """Answer one flat card-set prompt the way the record's own nested choice answered it.

    The record resolved the prompt with the generator's fixed rule — the first legal action, which for
    a prompt whose minimum is zero is skipping it — and stores the option ids it selected. Those ids
    are the encoder's own instance ids and are not comparable with the bridge's card names, so what is
    mirrored is the *rule*, through the two facts that survive it: how many cards were selected, and
    whether any were. Taking the first offered card on each report the prompt makes is that rule, and
    the fight that follows is what checks the two sides agreed.
    """
    if cursor >= len(nested):
        raise AssertionError("the shipped game opened a card prompt the record does not describe")
    choice = nested[cursor]
    _check(
        choice["kind"] == CARD_SELECT_KIND,
        f"the record describes a {choice['kind']!r} nested choice where the shipped game is at a card prompt",
    )
    _check(
        choice["selected_index"] == 0,
        f"the record's nested choice is the legal action at index {choice['selected_index']}, which the "
        "first-legal-action rule this drive mirrors does not reproduce",
    )

    wanted, selected, first_report = len(choice["selected_option_ids"]), 0, None
    while True:
        actions = client.legal_actions()
        current_observation = client.observe() if capture is not None else None
        cards = [action for action in actions if action.get("action_type") == CARD_SELECT_ACTION]
        if first_report is None:
            details = (client.observe().get("room") or {}).get("details") or {}
            first_report = {"offered": [action["action_id"] for action in cards], "details": details}
            _check(
                not details or details.get("min_select", 0) <= wanted <= details.get("max_select", wanted),
                f"the record selected {wanted} card(s) where the prompt asks for "
                f"{details.get('min_select')}..{details.get('max_select')}",
            )
        if selected == wanted:
            _check(
                any(action["action_id"] == CARD_SELECT_FINISH for action in actions),
                f"the prompt offers no way to leave it with the {wanted} card(s) the record selected",
            )
            if capture is not None and current_observation is not None:
                _capture_boundary(capture, current_observation, actions, CARD_SELECT_FINISH)
            return client.step(CARD_SELECT_FINISH)["observation"], cursor + 1, first_report
        _check(bool(cards), f"the prompt offers no card to select with {selected} of {wanted} chosen")
        if capture is not None and current_observation is not None:
            _capture_boundary(capture, current_observation, actions, cards[0]["action_id"])
        observation = client.step(cards[0]["action_id"])["observation"]
        selected += 1
        if str(observation.get("phase")) != CARD_SELECT_STAGE:
            _check(selected == wanted, f"the prompt ended after {selected} of the {wanted} card(s) the record selected")
            return observation, cursor + 1, first_report


def _drive_to_the_fight(
    client: FullAppBridgeClient, sample: Sample, record: _Record, started: dict[str, Any] | None = None,
    capture: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """Drive the shipped game to the fight the record describes, and hand back what it saw.

    The run starts on the seed the record carries — the canonical form, so the shipped game's own
    canonicalisation is a no-op and the two runs are the same run — and the Ancient room is the first
    decision it reports, offering as many choices as the record enumerated. A card prompt is answered
    from the record's own nested choices; every other stage is answered with the first legal action,
    which is the rule the generator's drive uses and the rule the row-1 node is picked by.
    """
    recipe = record.recipe
    if started is None:
        started = client.start_run(seed=recipe["seed"], character=sample.character, ascension=sample.ascension)
    observation = started["observation"]
    if capture is not None:
        hello = client.hello()
        capture.update(game_build=hello.get("game_build"), pid=hello.get("pid"),
                       process_mode=hello.get("process_mode"),
                       initial_history=client.history(), initial_state_hash=observation.get("state_hash"),
                       boundary_trace=[])
    _check(
        str(observation.get("phase")) == "event",
        f"the shipped run opened at {observation.get('phase')!r}, not in the act's Ancient room",
    )
    offered = (observation.get("room") or {}).get("options") or []
    _check(
        len(offered) == len(recipe["ancient_options"]),
        f"the Ancient room offers {len(offered)} choices where the record enumerated {len(recipe['ancient_options'])}",
    )
    _check(
        sample.option_index < len(offered),
        f"the Ancient room offers {len(offered)} choices, so there is no choice {sample.option_index}",
    )

    # The Ancient choice the record took, by the index the record holds. The room reports every option
    # as a legal action in offer order, so taking the first one would silently compare a different
    # record's situation — which is why the choice is taken here and not by the loop below.
    action = f"choose_event:{sample.option_index}"
    initial_actions = client.legal_actions()
    _check(
        any(candidate["action_id"] == action for candidate in initial_actions),
        f"the Ancient room does not offer {action!r} among its choices",
    )
    if capture is not None:
        _capture_boundary(capture, observation, initial_actions, action)
    stages: list[str] = [str(observation.get("phase"))]
    observation = client.step(action)["observation"]

    prompts: list[dict[str, Any]] = []
    nested, cursor = list(recipe["nested_choices"]), 0

    for _ in range(MAX_STEPS):
        if observation.get("combat"):
            _check(
                cursor == len(nested),
                f"the fight arrived with {len(nested) - cursor} recorded nested choice(s) unanswered",
            )
            if capture is not None:
                _capture_boundary(capture, observation, client.legal_actions(), None)
                capture["projection"] = project_bridge(observation)
            return observation, stages, prompts
        stage = str(observation.get("phase"))
        stages.append(stage)
        if stage == CARD_SELECT_STAGE:
            observation, cursor, prompt = _answer_card_select(client, nested, cursor, capture)
            prompts.append(prompt)
            continue
        actions = client.legal_actions()
        _check(bool(actions), f"the shipped run stalled in {stage!r} with no legal action at all; stages seen {stages}")
        if capture is not None:
            _capture_boundary(capture, observation, actions, actions[0]["action_id"])
        observation = client.step(actions[0]["action_id"])["observation"]

    raise AssertionError(f"no fight within {MAX_STEPS} decisions; stages seen {stages}")


def _capture_boundary(capture: dict[str, Any], observation: dict[str, Any],
                      actions: list[dict[str, Any]], chosen: str | None) -> None:
    """Record legal decision semantics without comparing minted card instance ids."""
    def semantic(action: dict[str, Any]) -> str:
        if action.get("action_type") == CARD_SELECT_ACTION:
            metadata = action.get("metadata") or {}
            return f"{CARD_SELECT_ACTION}:{metadata.get('card_index')}:{metadata.get('card_id')}"
        return str(action.get("action_id"))

    selected = next((semantic(action) for action in actions if action.get("action_id") == chosen), None)
    capture["boundary_trace"].append({"phase": observation.get("phase"),
                                       "legal": [semantic(action) for action in actions], "chosen": selected})


def _compare(record: _Record, observation: dict[str, Any]) -> dict[str, Any]:
    """The situation's givens, and every contract field the shipped game and the record differ on.

    The givens are checked after the comparison because they are what makes the two states the same
    situation at all: the drive stands on the node the record names, the choice granted the relic the
    record says it did, the run is the one the record was recorded on, and the fight is the encounter
    the record names. The coordinate is not a contract field, so all of this is reported beside the
    comparison rather than inside it. The two projections are also held to the contract's own field
    list here, so a projection cannot start comparing a field the contract does not declare.

    The Act variant is the first precondition and the sharpest one: a run in a different Act is not in
    the recorded situation at all — different node, different encounter pools, different everything — so
    there is nothing to compare field by field and the failure names the contract field that moved. The
    compared sample contains both variants, so this check proves the progression-complete shipped
    profile followed the same run-seed selection as the simulator.
    """
    recipe, state = record.recipe, record.state
    run, node = observation["run"], recipe["node"]
    coord = observation.get("map_coord") or {}
    relics = [relic["model_id"] for relic in (observation.get("inventory") or {}).get("relics", [])]
    givens: dict[str, Any] = {
        "map_coord": dict(coord),
        "relics": relics,
        "encounter": observation["combat"]["encounter"],
        # Which declared fields this sample actually had: a fight with no powers on the field leaves the
        # power paths unread, and the report sums these so a declared-but-never-read field is visible
        # rather than counted as compared. The record's side is what is asked, because the projection of
        # a fight is the same shape whichever encoder produced it.
        "exercised_fields": sorted(set(shape_paths(project_record(state))) & set(CONTRACT_FIELDS)),
    }

    _check(
        run["act_variant"] == recipe["act_variant"],
        f"the shipped run is in the {run['act_variant']} Act where the record's $.run.act_variant says "
        f"{recipe['act_variant']}, so the drive is not in the recorded situation",
    )
    _check(
        run["seed"] == recipe["seed"],
        f"the shipped run reports seed {run['seed']!r}, not the recorded {recipe['seed']!r}",
    )
    _check(run["ascension"] == recipe["ascension"], f"the shipped run reports Ascension {run['ascension']!r}")
    _check(
        (coord.get("col"), coord.get("row")) == (node["col"], node["row"]),
        f"the drive stands on {coord!r}, not on the recorded node {node!r}",
    )
    granted = recipe["ancient_choice"]["relic_model_id"]
    _check(granted in relics, f"the run does not hold the relic the recorded choice grants ({granted}): {relics}")

    for side, paths in (
        ("bridge", shape_paths(project_bridge(observation))),
        ("record", shape_paths(project_record(state))),
    ):
        undeclared = sorted(set(paths) - set(CONTRACT_FIELDS))
        _check(not undeclared, f"the {side} projection carries fields the contract does not declare: {undeclared}")

    return {**givens, **_difference(compare_contract(state, observation))}


def _difference(comparison: ContractComparison) -> dict[str, Any]:
    """One comparison as a result: whether it matched, what moved first, and how much of it moved."""
    first = comparison.first
    return {
        "matched": first is None,
        "compared_fields": comparison.compared_fields,
        "mismatched_fields": len(comparison.mismatches),
        "difference": None
        if first is None
        else {
            "path": first.path,
            "record": first.record,
            "shipped_game": first.shipped_game,
            "record_present": first.record_present,
            "shipped_present": first.shipped_present,
        },
        "differing_paths": [mismatch.path for mismatch in comparison.mismatches],
    }


def _dump(sample: Sample, record: _Record, observation: dict[str, Any], dump_dir: Path) -> None:
    """Write both sides of a sample that did not match, so the values behind the paths can be read.

    The comparison names *every* field that moved; what it does not carry is the two observations those
    paths were read from. Keeping them beside each other is how a maintainer answers "why did this one
    move" for the third and nineteenth path as well as the first — and it is not a second comparator,
    only the inputs the one comparator was given.
    """
    dump_dir.mkdir(parents=True, exist_ok=True)
    name = sample.label.replace("/", "_").replace("@", "_").replace("#", "_")
    for suffix, document in (
        ("record.json", record.state),
        ("bridge.json", observation),
        ("record.projected.json", project_record(record.state)),
        ("bridge.projected.json", project_bridge(observation)),
    ):
        (dump_dir / f"{name}.{suffix}").write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")


def _result_header(sample: Sample) -> dict[str, Any]:
    return {"label": sample.label, "character": sample.character,
            "ascension": sample.ascension, "nested_kinds": []}


def _record_metadata(record: _Record) -> dict[str, Any]:
    recipe = record.recipe
    return {
        "seed": recipe["seed"],
        "act_variant": recipe["act_variant"],
        "ancient_choice": recipe["ancient_choice"],
        "nested_kinds": [nested["kind"] for nested in recipe["nested_choices"]],
        "node": recipe["node"],
    }


def _sample_result(
    sample: Sample, runs: dict[Run, _RecordedRun], worker_id: int, dump_dir: Path | None = None,
    *, certify: bool = False,
) -> dict[str, Any]:
    """Drive one sample's shipped run and compare it, or report why it could not be compared.

    Everything about one sample is inside the guard, the record included: an element the generator could
    not turn into a scenario is that sample's failure, reported with the stage and the error it failed
    at, rather than an exception that ends the run and leaves the other samples unmeasured.
    """
    result = _result_header(sample)
    client = FullAppBridgeClient(FullAppClientConfig(worker_id=worker_id))
    observation: dict[str, Any] | None = None
    record: _Record | None = None
    capture: dict[str, Any] | None = {} if certify else None
    try:
        record = _record_for(sample, runs)
        result.update(_record_metadata(record))
        launch_at = time.monotonic()
        try:
            client.launch(requested_character=sample.character)
        finally:
            result["startup_seconds"] = time.monotonic() - launch_at
        result.update(client.launch_timings)
        result["pck_fingerprint_seconds"] = float(client.ready_hello.get("pck_fingerprint_seconds", 0.0))
        result["pck_fingerprint_count"] = 1
        result["pck_fingerprint_bytes"] = (Path(client.config.game_root) / "SlayTheSpire2.pck").stat().st_size
        started_at = time.monotonic()
        try:
            started = client.start_run(seed=record.recipe["seed"], character=sample.character,
                                       ascension=sample.ascension)
        finally:
            result["start_run_seconds"] = time.monotonic() - started_at
        drive_at = time.monotonic()
        try:
            observation, stages, prompts = _drive_to_the_fight(client, sample, record, started, capture)
        finally:
            result["drive_seconds"] = time.monotonic() - drive_at
        result.update({"stages": stages, "card_prompts": prompts})
        result.update(_compare(record, observation))
    except Exception as error:  # noqa: BLE001 — any failure is this sample's, and the run continues
        result.update({"matched": False, "difference": None, "failure": f"{type(error).__name__}: {error}"})
    finally:
        client.close()
        result.update(client.launch_timings)
        result["processes_started"] = client.processes_started
        result["close_seconds"] = client.last_close_seconds
    if capture is not None:
        result.update(capture)
        result["start_path"] = "menu"
    if dump_dir is not None and not result.get("matched") and observation is not None and record is not None:
        _dump(sample, record, observation, dump_dir)
    return result


def _reuse_candidate_result(
    sample: Sample, runs: dict[Run, _RecordedRun], worker: ReusableFullAppWorker,
    dump_dir: Path | None = None,
    *, certify: bool = False, after_teardown: Any = None,
) -> dict[str, Any]:
    """Compare one entry using the same drive and projection as fresh parity."""
    result = _result_header(sample)
    try:
        record = _record_for(sample, runs)
        result.update(_record_metadata(record))
    except Exception as error:  # noqa: BLE001 - a missing scenario belongs to this entry
        result.update({"matched": False, "difference": None, "failure": f"{type(error).__name__}: {error}"})
        return result

    entry = RunEntry(seed=record.recipe["seed"], character=sample.character, ascension=sample.ascension)
    capture: dict[str, Any] | None = {} if certify else None
    executed = worker.run_entry(entry, lambda client, started: _drive_to_the_fight(
        client, sample, record, started, capture), after_teardown=after_teardown)
    result.update({
        "pid": executed.pid,
        "process_entry_ordinal": executed.process_entry_ordinal,
        "start_path": executed.start_path,
        "warm": executed.start_path == "direct" if executed.start_path is not None else None,
        "process_mode": executed.process_mode,
        "startup_seconds": executed.startup_seconds,
        "sandbox_seconds": executed.sandbox_seconds,
        "process_ready_seconds": executed.process_ready_seconds,
        "pck_fingerprint_seconds": executed.pck_fingerprint_seconds,
        "start_run_seconds": executed.start_run_seconds,
        "drive_seconds": executed.drive_seconds,
        "entry_seconds": executed.entry_seconds,
        "teardown_seconds": executed.teardown_seconds,
        "close_seconds": executed.close_seconds,
        "replacement_count": executed.replacement_count,
        "pck_fingerprint_bytes": executed.pck_fingerprint_bytes,
        "pck_fingerprint_count": executed.pck_fingerprint_count,
        "teardown": executed.teardown,
    })
    if not executed.succeeded or executed.value is None:
        result.update({"matched": False, "difference": None, "failure": executed.error or "worker returned no observation"})
        if capture is not None:
            result.update(capture)
        return result
    observation, stages, prompts = executed.value
    result.update({"stages": stages, "card_prompts": prompts})
    try:
        result.update(_compare(record, observation))
    except Exception as error:  # noqa: BLE001 - comparison failure belongs to this entry
        result.update({"matched": False, "difference": None, "failure": f"{type(error).__name__}: {error}"})
    if capture is not None:
        result.update(capture)
    if dump_dir is not None and not result.get("matched"):
        _dump(sample, record, observation, dump_dir)
    return result


def report(
    results: list[dict[str, Any]], build: dict[str, Any], complete_sample: bool,
    *, process_mode: str = "fresh", total_wall_seconds: float = 0.0,
    certification: dict[str, Any] | None = None,
    native_pck: dict[str, float | int] | None = None,
    native_pool_start_seconds: float = 0.0,
    record_seconds: float = 0.0, full_app_close_seconds: float = 0.0,
) -> dict[str, Any]:
    """The run as a document: what was compared, what was covered, and what happened per sample.

    The contract block carries both halves of "stated explicitly": the fields the comparison covers and
    the fields it does not, each with a reason — and, beside them, the declared fields no sample
    *exercised*, because a field that is declared and never read is the same trap in a quieter form.

    This is also the handle the offline suite holds the oracle to: ``tests/test_parity_projection.py``
    builds the same document from no results and asserts that the contract block in it is the
    projection module's own declaration, which is what stops the two seams drifting apart.
    """
    covered = sorted({kind for result in results for kind in result["nested_kinds"]})
    # The coverage claim is checked rather than asserted: a sample that stopped opening the prompt it
    # was chosen for would otherwise report coverage it does not have.
    coverage_agrees = not complete_sample or set(covered) == set(NESTED_KINDS_COVERED)
    matched = [result for result in results if result.get("matched")]
    entries_agree = not complete_sample or (
        len(results) == len(SAMPLE) and {result["label"] for result in results} == {sample.label for sample in SAMPLE}
    )
    exercised = sorted(set().union(*(result.get("exercised_fields", []) for result in results)))
    one_process_evidence = False
    performance = {
        # Nested measurements are not additive: process readiness includes the game's
        # PCK hash, and native pool startup includes the shared native hash.
        "native_pool_start_seconds": native_pool_start_seconds,
        "record_seconds": record_seconds,
        "native_pck": native_pck,
        "sandbox_seconds": sum(result.get("sandbox_seconds", 0.0) for result in results),
        "process_ready_seconds": sum(result.get("process_ready_seconds", 0.0) for result in results),
        "full_app_pck_fingerprint_seconds": sum(result.get("pck_fingerprint_seconds", 0.0) for result in results),
        "start_run_seconds": sum(result.get("start_run_seconds", 0.0) for result in results),
        "drive_seconds": sum(result.get("drive_seconds", 0.0) for result in results),
        "teardown_seconds": sum(result.get("teardown_seconds", 0.0) for result in results),
        "close_seconds": (full_app_close_seconds if process_mode == "reuse" else
                          sum(result.get("close_seconds", 0.0) for result in results)),
        "pck_bytes_hashed": sum(result.get("pck_fingerprint_bytes", 0) for result in results),
        "pck_fingerprints": sum(result.get("pck_fingerprint_count", 0) for result in results),
        "total_wall_seconds": total_wall_seconds,
    }
    reuse_mode = process_mode == "reuse"
    if reuse_mode:
        process_count = max((result["replacement_count"] for result in results
                             if "replacement_count" in result), default=-1) + 1
        performance.update({
            "shipped_game_processes_started": process_count,
            # ReusableFullAppWorker owns one serial lane and closes a process before replacing it.
            "maximum_live_process_count": min(process_count, 1),
        })
    else:
        performance.update({
            "shipped_game_processes_started": sum(result.get("processes_started", 0) for result in results),
            "maximum_live_process_count": min(sum(result.get("processes_started", 0) for result in results), 1),
        })
    if reuse_mode:
        one_process_evidence = complete_sample and entries_agree and process_count == 1 and bool(results) and (
            performance["pck_fingerprints"] == 1
            and performance["pck_bytes_hashed"] > 0
            and len({result.get("pid") for result in results}) == 1
            and all(
                isinstance(result.get("pid"), int)
                and result.get("process_entry_ordinal") == index + 1
                and result.get("start_path") == ("menu" if index == 0 else "direct")
                and result.get("warm") is (index > 0)
                and result.get("process_mode") == "reuse"
                and result.get("replacement_count") == 0
                and all(
                    isinstance(result.get(field), (int, float)) and result[field] >= 0
                    for field in ("startup_seconds", "entry_seconds", "teardown_seconds")
                )
                and isinstance(result.get("teardown"), dict)
                and result["teardown"].get("final_state") == "idle"
                and type(result["teardown"].get("ended_generation")) is int
                and result["teardown"]["ended_generation"] > (
                    results[index - 1]["teardown"]["ended_generation"] if index > 0 else 0
                )
                and result["teardown"].get("driver_result") in ("abandoned", "cancelled")
                and result["teardown"].get("parked_wait_released") is True
                and isinstance(result["teardown"].get("reset_history_counts"), dict)
                for index, result in enumerate(results)
            )
        )
    document = {
        "success": len(matched) == len(results) and coverage_agrees and entries_agree
                   and (not reuse_mode or one_process_evidence),
        "process_mode": process_mode,
        "certification": certification,
        "game_build": build,
        "sample": {
            "size": len(results),
            "characters": sorted({result["character"] for result in results}),
            "ascensions": sorted({result["ascension"] for result in results}),
            "act_variants": sorted({result["act_variant"] for result in results if "act_variant" in result}),
            "seeds": sorted({result["seed"] for result in results if "seed" in result}),
        },
        "contract": {
            "fields_compared": list(CONTRACT_FIELDS),
            "fields_not_compared": [{"path": field.path, "reason": field.reason} for field in EXCLUDED_FIELDS],
            "optional_fields": sorted(OPTIONAL_FIELDS),
            "fields_declared_not_exercised": sorted(set(CONTRACT_FIELDS) - set(exercised)),
            "state_hashes_compared": 0,
        },
        "nested_choice_kinds": {
            "measured": covered,
            "declared": sorted(NESTED_KINDS_COVERED),
            "not_covered": NESTED_KINDS_NOT_COVERED,
            "agrees": coverage_agrees,
        },
        "act_variants_compared": sorted({result["act_variant"] for result in results if "act_variant" in result}),
        "matched": len(matched),
        "mismatched": len(results) - len(matched),
        "results": results,
    }
    document.update({"performance": performance})
    if reuse_mode:
        document["one_process_evidence"] = one_process_evidence
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3, help="native workers to record the sample's runs on")
    parser.add_argument("--worker-id", type=int, default=11, help="first sandbox index to run a shipped game in")
    parser.add_argument("--limit", type=int, help="compare only the first N samples, to try the seam cheaply")
    parser.add_argument(
        "--only", action="append", default=[], metavar="LABEL",
        help="compare only the samples with this label, repeatable — a run whose sample takes minutes needs a way "
             "to re-drive the one that a dropped game process cost",
    )
    parser.add_argument("--report", type=Path, help="also write the report to this JSON file")
    parser.add_argument("--process-mode", choices=("reuse", "fresh"), default="reuse",
                        help="reuse (default) requires a matching certification; fresh starts one menu-path game "
                             "process per entry and works without certification")
    parser.add_argument(
        "--dump", type=Path,
        help="keep both observations and both projections of every sample that did not match, in this directory",
    )
    arguments = parser.parse_args(argv)

    if arguments.process_mode == "reuse" and (arguments.limit or arguments.only):
        parser.error("reuse requires the complete sixteen-entry sample; select --process-mode fresh for a subset")

    wall_started = time.monotonic()
    samples = SAMPLE[: arguments.limit] if arguments.limit else SAMPLE
    if arguments.only:
        named = set(arguments.only)
        samples = tuple(sample for sample in SAMPLE if sample.label in named)
        if not samples:
            parser.error(f"no sample is labelled {sorted(named)}")
    pool_started = time.monotonic()
    with NativeWorkerPool(arguments.workers) as pool:
        native_pool_start_seconds = time.monotonic() - pool_started
        runs_to_record = len({sample.run for sample in samples})
        print(f"Recording {runs_to_record} runs with {arguments.workers} native workers...", flush=True)
        record_started = time.monotonic()
        runs = _records(pool, samples)
        record_seconds = time.monotonic() - record_started
        build = pool.workers[0].build
        try:
            identity = current_certification_identity(build, SCENARIO_SET_REVISION)
        except CertificationError as error:
            if arguments.process_mode == "reuse":
                parser.error(str(error))
            identity = {"assembly_sha256": build.get("assembly_sha256"),
                        "pck_sha256": build.get("pck_sha256"),
                        "scenario_set_revision": SCENARIO_SET_REVISION}
        if arguments.process_mode == "reuse":
            try:
                certificate = require_certificate(identity, CERTIFICATE_PATH, CERTIFICATION_REPORT_PATH)
            except CertificationError as error:
                parser.error(str(error))
            certification = {"status": "matched", "identity": identity,
                             "passed_at_utc": certificate["passed_at_utc"],
                             "report_sha256": certificate["report_sha256"]}
        else:
            certification = {"status": "not_required", "identity": identity}
        print(f"Recorded on game build {build['assembly_sha256']}; now driving the shipped game.", flush=True)

        results: list[dict[str, Any]] = []
        full_app_close_seconds = 0.0
        if arguments.process_mode == "reuse":
            identity_checked = False
            with ReusableFullAppWorker(FullAppClientConfig(worker_id=arguments.worker_id, process_mode="reuse")) as worker:
                for offset, sample in enumerate(samples):
                    print(f"[{offset + 1}/{len(samples)}] reusing a shipped game for {sample.label}...", flush=True)
                    result = _reuse_candidate_result(sample, runs, worker, arguments.dump)
                    results.append(result)
                    if not identity_checked and worker.game_build is not None:
                        if (worker.game_build != build
                            or worker.lifecycle_protocol_revision != identity["lifecycle_protocol_revision"]
                            or worker.progression_policy_revision != identity["profile_policy_revision"]):
                            raise CertificationError("Running bridge identity differs from certification; "
                                                     "run the dedicated certify_full_app_reuse gate or select --process-mode fresh.")
                        identity_checked = True
                    state = "matched" if result.get("matched") else ("FAILED" if result.get("failure") else "MISMATCH")
                    print(f"    {sample.label}: {state}", flush=True)
            full_app_close_seconds = worker.close_seconds_total
        else:
            for offset, sample in enumerate(samples):
                print(f"[{offset + 1}/{len(samples)}] launching a headless shipped game for {sample.label}...", flush=True)
                result = _sample_result(sample, runs, arguments.worker_id + offset, arguments.dump)
                results.append(result)
                state = "matched" if result.get("matched") else ("FAILED" if result.get("failure") else "MISMATCH")
                print(f"    {sample.label}: {state}", flush=True)
        native_pck = getattr(pool, "fingerprint_summary", lambda: None)()

    document = report(results, build, complete_sample=tuple(samples) == SAMPLE,
                      process_mode=arguments.process_mode,
                      total_wall_seconds=time.monotonic() - wall_started,
                      certification=certification, native_pck=native_pck,
                      native_pool_start_seconds=native_pool_start_seconds,
                      record_seconds=record_seconds, full_app_close_seconds=full_app_close_seconds)
    if arguments.report is not None:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in document.items() if key != "results"}, indent=2, sort_keys=True))
    for result in results:
        if not result.get("matched"):
            print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    print(f"\n{document['matched']} of {len(results)} samples matched field for field.")
    return 0 if document["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
