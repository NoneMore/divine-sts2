#!/usr/bin/env python3
"""Shipped-game acceptance for the card-select prompt an Ancient choice opens.

Several of the act-1 Ancient's choices hand the run a relic whose pick-up asks the player to select a
card — a removal, an upgrade or a transform — and the shipped game asks its installed card selector
for that selection before it would push any screen. The bridge's autoplay installs a selector that
answers such a prompt at random, so before this seam existed the prompt was resolved with no
observation branch at all: a caller was handed no room and no legal action, and a shipped run that
reached one could not be driven. This script drives real ``SlayTheSpire2.exe`` workers to that prompt
and checks what a caller sees and can do there:

* the stage the bridge reports while the prompt is open is one the decision vocabulary maps onto the
  simulator's ``card_choice``, rather than a stage with no block at all;
* the room names the cards on offer, and every legal action names the card it selects, so a caller
  selects a card by identity instead of guessing which position the bridge means;
* the range the game asked for travels with the room, and the action that leaves the prompt is
  offered exactly while the game allows it — so a prompt whose minimum is zero can be skipped;
* selecting the cards the prompt asks for advances the shipped run past the prompt, and the selection
  is honoured: the cards the actions named are the cards the run no longer holds, and the deck is
  shorter by exactly the number the prompt asked for;
* a prompt that wants more than one card is reported again with the rest of the offer and the cards
  already chosen beside them, so a caller can tell that the prompt is not finished yet;
* the run then reaches the map, which is the room the Ancient's choice leads to.

Three samples are driven, one per prompt the Ancient's choices open in this repository's own terms,
and the docstring of each says which native command it reaches: ``TRACERBULLET``'s first Ancient
choice is ``PRECISE_SCISSORS``, a one-card removal (``FromDeckForRemoval``); ``ANC1ENT01``'s third is
``PRECARIOUS_SHEARS``, a two-card removal; and ``ANCIENT01``'s third is ``HEFTY_TABLET`` on this
build, a card to *add* chosen from a small offered set (``FromChooseACardScreen``) whose minimum is
zero, so the drive skips it. ``ANCIENT01`` is not a canonical seed — the shipped game canonicalises it
to ``ANC1ENT01``, which offers a different set of choices — which is why both forms appear here and
why the sample names the relic it expects. The upgrade, transform and discard prompts the game routes
through the same selector are read from the decompiled build rather than measured here: they are the
same seam, and this script's three samples already cover a removal, a multi-card removal and a
skippable add. The set of Ancient choices a parity campaign can drive is wider than these three.

One nested choice is deliberately **not** covered, and this script reports rather than implies
otherwise: the *bundle* pick ``SCROLL_BOXES`` opens has no selector branch in the shipped game, so it
arrives at the AutoSlay handler this bridge does not take, and ``GYMSCENAR10``'s second Ancient choice
reaches it. That drive is recorded as evidence of the bound — the bundle pick is answered off-bridge,
so a caller cannot select a bundle by identity on this seam — and is not asserted, because it
describes a gap rather than the behaviour this ticket establishes.

The bridge's deck card-select screen stage is untouched by this ticket and is not observed here: the
shipped autoplay's selector answers before that screen is ever pushed, so there is nothing to drive.

Requires the shipped game (the repository's ``*_acceptance.py`` convention). The sandbox is
hard-linked beside the install, so it has to sit on the install's volume.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).parent))

from sts2_native_sim import decision_vocabulary
from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig

#: The stage word the bridge reports while a flat card-set prompt is open, and the decision kind the
#: vocabulary says that stage stands for — the kind the simulator reports for the same situation.
CARD_SELECT_STAGE = "simple_card_select"
CARD_SELECT_KIND = "card_choice"

#: The room a caller recognises the prompt by, and the members the room and its actions report.
CARD_SELECT_ROOM = "SimpleCardSelect"
CARD_SELECT_ACTION = "choose_card_select"
CARD_ACTION_METADATA_KEYS = ("card_index", "card_id")
ROOM_DETAIL_KEYS = ("min_select", "max_select", "selected")

#: The action that leaves a prompt with what has been chosen, which is also how a prompt whose
#: minimum is zero — one the game lets the player skip — is skipped.
FINISH_ACTION = "finish_card_select"

#: How many decisions the drive may take to leave the Ancient room, so a stall names where it stalled.
MAX_STEPS = 12

#: How many card selections one prompt may ask for, so a prompt that never finishes is a failure
#: rather than a loop.
MAX_SELECTIONS = 5

#: The stage the Ancient room hands over to once its choice — and any prompt that choice opened — ends.
MAP_STAGE = "map"


@dataclass(frozen=True)
class Sample:
    """One Ancient choice whose pick-up opens a card-select prompt, and how this drive answers it."""

    character: str
    ascension: int
    seed: str
    option_index: int
    relic: str
    #: The minimum the game asks the prompt for, which is what makes a prompt skippable when it is 0.
    min_select: int
    #: "take" selects the first offered card on every report; "skip" leaves the prompt unanswered.
    plan: str
    #: What the relic's own pick-up does around the selection: `remove_chosen` takes out exactly the
    #: cards chosen, `add_curse_and_chosen` adds the curse the relic always adds plus whatever was
    #: chosen. The deck is where a selection becomes visible, so this is what it is checked against.
    effect: str


#: The curse Hefty Tablet adds to the deck whether or not a card was chosen for it.
HEFTY_TABLET_CURSE = "INJURY"

SAMPLES = (
    Sample("DEFECT", 0, "TRACERBULLET", 0, "PRECISE_SCISSORS", min_select=1, plan="take", effect="remove_chosen"),
    Sample("IRONCLAD", 0, "ANC1ENT01", 2, "PRECARIOUS_SHEARS", min_select=2, plan="take", effect="remove_chosen"),
    # The raw `ANCIENT01` is not the seed's canonical form, so the shipped game canonicalises it to
    # `ANC1ENT01` and offers a different set of choices than that seed does. On this build its third
    # choice grants `HEFTY_TABLET`, whose pick-up asks for a rare card to *add* and lets the player
    # skip it — the one prompt in this sample whose minimum is zero, and the one driven by skipping.
    Sample(
        "IRONCLAD", 0, "ANCIENT01", 2, "HEFTY_TABLET",
        min_select=0, plan="skip", effect="add_curse_and_chosen",
    ),
)

#: The Ancient choice whose relic opens a bundle pick instead of a card select. Its drive is reported
#: rather than asserted: it is the bound on which nested kinds this seam can drive.
BUNDLE_SAMPLE = Sample(
    "IRONCLAD", 0, "GYMSCENAR10", 1, "SCROLL_BOXES", min_select=0, plan="take", effect="add_curse_and_chosen"
)


def _check(condition: bool, record: dict[str, Any], message: str) -> None:
    if not condition:
        raise AssertionError(f"{message}\nobserved: {json.dumps(record, indent=2, sort_keys=True)}")


def _room(observation: dict[str, Any]) -> dict[str, Any]:
    room = observation.get("room")
    return cast(dict[str, Any], room) if isinstance(room, dict) else {}


def _deck(observation: dict[str, Any]) -> list[str]:
    deck = observation.get("deck_cards")
    return list(deck) if isinstance(deck, list) else []


def _relics(observation: dict[str, Any]) -> list[str]:
    inventory = observation.get("inventory") or {}
    return [relic["model_id"] for relic in inventory.get("relics", [])]


def _step_first_legal(client: FullAppBridgeClient, record: dict[str, Any], where: str) -> dict[str, Any]:
    """Take the first legal action the bridge reports, or fail naming the stage that stalled."""
    actions = client.legal_actions()
    _check(bool(actions), record, f"the run stalled in {where} with no legal action at all")
    return client.step(actions[0]["action_id"])["observation"]


def _drive_to_prompt(client: FullAppBridgeClient, sample: Sample, record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Take the sample's Ancient choice and drive on until the card-select prompt reports itself.

    The Ancient room's own loop reports the room again while the relic's pick-up runs, so a stage that
    is not the prompt is answered with its own first legal action rather than treated as a missed
    prompt.
    """
    observation = client.start_run(seed=sample.seed, character=sample.character, ascension=sample.ascension)["observation"]
    stages = [str(observation.get("phase"))]
    _check(stages[0] == "event", record, f"the run did not open in the Ancient room: {stages[0]!r}")

    offered_choices = _room(observation)["options"]
    _check(
        sample.option_index < len(offered_choices),
        record,
        f"the Ancient offered {len(offered_choices)} choices, not the {sample.option_index + 1} this sample takes",
    )

    observation = client.step(f"choose_event:{sample.option_index}")["observation"]
    for _ in range(MAX_STEPS):
        stage = str(observation.get("phase"))
        if stage == CARD_SELECT_STAGE:
            return observation, stages
        stages.append(stage)
        observation = _step_first_legal(client, record, f"stage {stage!r} on the way to the prompt")

    raise AssertionError(f"no card-select prompt within {MAX_STEPS} decisions; stages seen {stages}")


def _check_prompt(
    observation: dict[str, Any],
    actions: list[dict[str, Any]],
    selected: list[str],
    record: dict[str, Any],
    sample: Sample,
) -> tuple[dict[str, Any], list[str]]:
    """The prompt as a caller sees it: a stage the vocabulary maps, a room, and card-naming actions.

    `selected` is what the caller has already chosen for this prompt, which the room has to agree with
    on a prompt that is reported again because it is not finished yet. The range is the game's own:
    the sample names the minimum it read for this choice, so a build that changed the prompt fails
    here rather than being normalised away.
    """
    stage = str(observation.get("phase"))
    kinds = decision_vocabulary.decision_kinds_for_bridge_phase(stage)
    _check(
        CARD_SELECT_KIND in kinds,
        record,
        f"the prompt reports stage {stage!r}, which the vocabulary maps onto {sorted(kinds)}",
    )

    room = _room(observation)
    _check(
        room.get("room_type") == CARD_SELECT_ROOM,
        record,
        f"the prompt reports no {CARD_SELECT_ROOM!r} room: {room!r}",
    )

    offered = room["options"]
    _check(isinstance(offered, list) and bool(offered), record, f"the prompt names no card on offer: {offered!r}")
    _check(all(isinstance(card, str) and card for card in offered), record, f"the prompt offers {offered!r}")

    details = room["details"]
    missing = [key for key in ROOM_DETAIL_KEYS if key not in details]
    _check(not missing, record, f"the room does not report {missing}: {sorted(details)}")
    _check(
        details["min_select"] == sample.min_select,
        record,
        f"the prompt reports min_select {details['min_select']!r}, not the {sample.min_select} of this choice",
    )
    _check(
        isinstance(details["max_select"], int) and details["max_select"] >= details["min_select"],
        record,
        f"the prompt reports max_select {details['max_select']!r}",
    )
    _check(
        details["selected"] == selected,
        record,
        f"the room reports {details['selected']!r} as selected, not what the caller has chosen ({selected!r})",
    )

    _check(bool(actions), record, "the prompt offers no legal action at all")
    card_actions = [action for action in actions if action["action_id"] != FINISH_ACTION]
    action_types = {action["action_type"] for action in card_actions}
    _check(
        action_types == {CARD_SELECT_ACTION},
        record,
        f"the prompt's actions are {sorted(action_types)} rather than {CARD_SELECT_ACTION!r}",
    )
    _check(
        len(card_actions) == len(offered),
        record,
        f"the prompt offers {len(offered)} cards and {len(card_actions)} actions to select one",
    )
    for index, action in enumerate(card_actions):
        parts = action["action_id"].split(":")
        _check(
            len(parts) == 3 and parts[0] == CARD_SELECT_ACTION and parts[2] == offered[index],
            record,
            f"action {index} is {action['action_id']!r}, which does not name the card at that position ({offered[index]!r})",
        )
        metadata = action.get("metadata") or {}
        _check(
            all(key in metadata for key in CARD_ACTION_METADATA_KEYS),
            record,
            f"action {index} reports metadata {metadata!r}",
        )
        _check(
            metadata["card_id"] == offered[index] and metadata["card_index"] == index,
            record,
            f"action {index} reports {metadata!r}, not the card it names",
        )

    # Leaving the prompt is offered exactly while the game allows it: at or above the minimum, and
    # only while another card may still be taken — which is what makes a minimum of zero a skip.
    can_finish = details["min_select"] <= len(selected) < details["max_select"]
    finishing = [action for action in actions if action["action_id"] == FINISH_ACTION]
    _check(
        bool(finishing) == can_finish,
        record,
        f"the prompt offers {len(finishing)} way(s) to finish with {len(selected)} of "
        f"{details['min_select']}..{details['max_select']} chosen",
    )

    return room, list(offered)


def _answer_prompt(
    client: FullAppBridgeClient,
    observation: dict[str, Any],
    record: dict[str, Any],
    sample: Sample,
) -> tuple[dict[str, Any], list[str]]:
    """Answer the prompt until it stops being the decision, one offered card per report.

    A prompt that wants two cards is reported twice: the first report offers the whole deck, the
    second offers it without the card just chosen and names that card as already selected. The first
    report is recorded as the prompt a caller sees, because that is the one that states the range. A
    sample planned as `skip` answers the first report by leaving it, which the game allows exactly
    when the prompt's minimum is zero.
    """
    chosen: list[str] = []
    first: dict[str, Any] | None = None

    for _ in range(MAX_SELECTIONS):
        actions = client.legal_actions()
        room, offered = _check_prompt(observation, actions, chosen, record, sample)
        if first is None:
            first = room
            record["prompt_stage"] = observation["phase"]
            record["prompt_room_type"] = room["room_type"]
            record["prompt_details"] = room["details"]
            record["prompt_offered"] = offered
            record["prompt_actions"] = [action["action_id"] for action in actions]
            record["prompt_state_hash"] = observation["state_hash"]

        if sample.plan == "skip":
            _check(
                any(action["action_id"] == FINISH_ACTION for action in actions),
                record,
                f"the prompt cannot be skipped although it asks for a minimum of {sample.min_select}",
            )
            observation = client.step(FINISH_ACTION)["observation"]
            record["prompt_selected"] = []
            return observation, []

        chosen.append(offered[0])
        observation = client.step(actions[0]["action_id"])["observation"]
        if str(observation.get("phase")) != CARD_SELECT_STAGE:
            record["prompt_selected"] = chosen
            return observation, chosen

    raise AssertionError(f"the prompt was still open after {MAX_SELECTIONS} selections: {chosen}")


def _drive_to_map(client: FullAppBridgeClient, observation: dict[str, Any], record: dict[str, Any]) -> list[str]:
    """Drive on after the prompt until the Ancient room hands over the map."""
    stages = [str(observation.get("phase"))]
    for _ in range(MAX_STEPS):
        if str(observation.get("phase")) == MAP_STAGE:
            return stages
        observation = _step_first_legal(client, record, f"stage {stages[-1]!r} after the prompt")
        stages.append(str(observation.get("phase")))
    raise AssertionError(f"the run did not reach the map within {MAX_STEPS} decisions: stages seen {stages}")


def _check_the_selection_was_applied(
    deck_before: list[str],
    deck_after: list[str],
    chosen: list[str],
    sample: Sample,
    record: dict[str, Any],
) -> None:
    """The cards the caller selected are the cards the relic's own pick-up puts in or out of the deck.

    The deck is where a card selection becomes visible, and what it shows is the relic's own effect
    around it: a shears or scissors prompt removes exactly what was chosen, while Hefty Tablet adds the
    `Injury` it always adds plus whichever rare card was chosen — so a skipped Hefty Tablet prompt
    still grows the deck by that one curse, which is the game's behaviour rather than the bridge's.
    """
    gained = Counter(deck_after) - Counter(deck_before)
    lost = Counter(deck_before) - Counter(deck_after)
    if sample.effect == "remove_chosen":
        expected_gained: Counter[str] = Counter()
        expected_lost: Counter[str] = Counter(chosen)
    else:
        expected_gained = Counter([HEFTY_TABLET_CURSE]) + Counter(chosen)
        expected_lost = Counter()

    _check(
        gained == expected_gained,
        record,
        f"the run gained {sorted(gained.elements())} against the {sorted(expected_gained.elements())} expected",
    )
    _check(
        lost == expected_lost,
        record,
        f"the run lost {sorted(lost.elements())} against the {sorted(expected_lost.elements())} expected",
    )

    record["deck_size_before"] = len(deck_before)
    record["deck_size_after"] = len(deck_after)
    record["deck_gained"] = sorted(gained.elements())
    record["deck_lost"] = sorted(lost.elements())


def _drive_sample(client: FullAppBridgeClient, sample: Sample) -> dict[str, Any]:
    """One Ancient choice whose pick-up opens a card select, checked from the prompt to the map."""
    record: dict[str, Any] = {
        "character": sample.character,
        "ascension": sample.ascension,
        "seed": sample.seed,
        "ancient_option_index": sample.option_index,
        "expected_relic": sample.relic,
        "planned_min_select": sample.min_select,
        "plan": sample.plan,
    }

    observation, stages = _drive_to_prompt(client, sample, record)
    record["stages_before_the_prompt"] = stages
    record["run_seed"] = (observation.get("run") or {}).get("seed")
    _check(
        sample.relic in _relics(observation),
        record,
        f"the run does not hold the relic the sample's choice grants: {_relics(observation)}",
    )

    deck_before = _deck(observation)
    observation, chosen = _answer_prompt(client, observation, record, sample)
    record["stages_after_the_prompt"] = _drive_to_map(client, observation, record)
    _check_the_selection_was_applied(deck_before, _deck(observation), chosen, sample, record)
    return record


def _drive_bundle_sample(client: FullAppBridgeClient) -> dict[str, Any]:
    """What the bridge reports for a bundle pick, which this seam deliberately does not drive.

    Reported rather than asserted: the bundle screen is answered by the shipped autoplay's own
    handler, so no stage is reported for it and a caller cannot select a bundle. A later ticket that
    gives the bundle its own seam changes this record and nothing else.
    """
    sample = BUNDLE_SAMPLE
    record: dict[str, Any] = {
        "character": sample.character,
        "ascension": sample.ascension,
        "seed": sample.seed,
        "ancient_option_index": sample.option_index,
        "relic": sample.relic,
    }
    observation = client.start_run(seed=sample.seed, character=sample.character, ascension=sample.ascension)["observation"]
    stages = [str(observation.get("phase"))]
    observation = client.step(f"choose_event:{sample.option_index}")["observation"]
    for _ in range(MAX_STEPS):
        stage = str(observation.get("phase"))
        if stage == MAP_STAGE:
            break
        stages.append(stage)
        actions = client.legal_actions()
        if not actions:
            break
        observation = client.step(actions[0]["action_id"])["observation"]

    record["stages_seen"] = stages
    record["bundle_stage_reported"] = any(
        stage in (CARD_SELECT_STAGE, "deck_card_select", "rewards") for stage in stages
    )
    record["relic_granted"] = sample.relic in _relics(observation)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", type=int, default=7, help="first sandbox index to run in")
    arguments = parser.parse_args(argv)

    records: list[dict[str, Any]] = []
    for offset, sample in enumerate(SAMPLES):
        client = FullAppBridgeClient(FullAppClientConfig(worker_id=arguments.worker_id + offset))
        try:
            print(f"Launching a headless shipped game in {client.sandbox_dir}...", flush=True)
            client.launch(requested_character=sample.character)
            print(f"Worker ready on port {client.bound_port}; driving {sample.seed} to {sample.relic}...", flush=True)
            records.append(_drive_sample(client, sample))
        finally:
            client.close()

    bundle_client = FullAppBridgeClient(FullAppClientConfig(worker_id=arguments.worker_id + len(SAMPLES)))
    try:
        print(f"Launching a headless shipped game in {bundle_client.sandbox_dir}...", flush=True)
        bundle_client.launch(requested_character=BUNDLE_SAMPLE.character)
        print(f"Worker ready on port {bundle_client.bound_port}; observing the bundle pick...", flush=True)
        bundle = _drive_bundle_sample(bundle_client)
    finally:
        bundle_client.close()

    print(json.dumps({
        "success": True,
        "prompts_driven": len(records),
        "card_select_stage": CARD_SELECT_STAGE,
        "card_select_decision_kind": CARD_SELECT_KIND,
        "finish_action": FINISH_ACTION,
        "samples": records,
        "nested_kinds_this_seam_drives": [CARD_SELECT_KIND],
        "nested_kinds_this_seam_does_not_drive": {"option_choice": bundle},
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
