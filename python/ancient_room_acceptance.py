"""Shipped-game acceptance for entering the act-1 Ancient room at run start.

A run the simulator starts must offer the act's Ancient as its first and only map
action, and travelling to it must open the Ancient's run-start choice through the
game's own map-point entry — the room the shipped game enters, the map-point history
entry it appends, and therefore the floor bookkeeping that seeds the first combat.

The script drives real native workers and checks, per sample seed:

* the run-start map offers exactly ``StandardActMap``'s starting point, ``(3, 0)``,
  typed ``Ancient``, and nothing else;
* travelling to it produces an ``event_choice`` decision for the act-1 Ancient with
  three legal actions, one per offered choice, each carrying its index and the relic
  model id it grants, in the order the run offered them;
* the offered relic ids are the ones an independent port of ``Neow``'s
  ``GenerateInitialOptions`` produces for the seed (the port also says which draws it
  takes, so a drifting offer cannot pass);
* entering the Ancient consumes no randomness the run's own streams count and
  changes nothing about the map, and it advances ``TotalFloor`` from 0 to 1;
* the Ancient's heal leaves the HP a fully unlocked run has, including
  ``WearyTraveler``'s reduced heal;
* after the Ancient and the first row-1 node the run's floors are the shipped ones
  (``ActFloor`` 2, ``TotalFloor`` 2), the first fight is the same encounter as
  before the Ancient room existed, and its randomised monster composition is the
  one the shipped ``SlimesWeak`` generator produces at ``TotalFloor == 2`` — with
  the port validated against a recorded ``TotalFloor == 1`` observation of the same
  seeds.

It is not the shipped-game parity comparison: that compares whole states field by
field against a real client, and belongs to the parity ticket. What this script
covers is the simulator's side of the claim, plus the independent ports that make
"the offer is the offered one" and "the composition is the floor-2 composition"
checkable rather than assumed.

Requires the shipped game and a Godot-hosted worker (the repository's
``*_acceptance.py`` convention). ``--snapshot`` prints the per-seed facts instead of
asserting them, which is how the sample and its recorded offer/fight expectations are
maintained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sts2_native_sim import NativeWorkerPool
from sts2_native_sim.ancient import ancient_action, drive_choice, prompt_free_choice_action
from sts2_native_sim.shipped_rng import Rng, deterministic_hash_code, rng_for_content

# `StandardActMap` puts the act's starting point at the middle column of row 0, and
# `RunManager.GenerateMap` leaves it typed `Ancient` because a fully unlocked run has
# the Neow epoch revealed (Sts2.NativeSim.Core's fully-unlocked baseline).
_ANCIENT_COORD = (3, 0)
_ANCIENT_POINT_TYPE = "Ancient"
_ANCIENT_EVENT_ID = "NEOW"
# `AscensionLevel.WearyTraveler`: the Ancient's heal is multiplied by 0.8.
_HEAL_REDUCTION_ASCENSION = 2

# `Neow.PositiveOptions` and `Neow.CurseOptions` in declaration order, plus the six
# relics `Neow.GenerateInitialOptions` adds as a coin-flip pair (`LavaRock` or
# `SmallCapsule`, and so on). A single-player offer removes `MassiveScroll`
# (`RelicModel.IsAllowed` wants more than one player) and keeps every other member,
# because a fully unlocked run allows them all: `Kaleidoscope` needs every character
# card pool unlocked and `ScrollBoxes` needs four commons and two uncommons, both of
# which hold. The curses are all allowed.
_NEOW_POSITIVE = (
    "ARCANE_SCROLL", "BOOMING_CONCH", "FISHING_ROD", "GOLDEN_PEARL", "KALEIDOSCOPE",
    "LEAD_PAPERWEIGHT", "LOST_COFFER", "MASSIVE_SCROLL", "NEOWS_TORMENT", "NEW_LEAF",
    "PHIAL_HOLSTER", "PRECISE_SCISSORS", "SCROLL_BOXES", "WINGED_BOOTS",
)
_NEOW_POSITIVE_PAIR = ("LAVA_ROCK", "SMALL_CAPSULE", "NUTRITIOUS_OYSTER", "STONE_HUMIDIFIER", "NEOWS_TALISMAN", "POMANDER")
_NEOW_CURSE = (
    "CURSED_PEARL", "HEFTY_TABLET", "LARGE_CAPSULE", "LEAFY_POULTICE", "NEOWS_BONES",
    "PRECARIOUS_SHEARS", "SILKEN_TRESS", "SILVER_CRUCIBLE",
)
_MULTIPLAYER_ONLY = frozenset({"MASSIVE_SCROLL"})
# The relic each curse choice removes from the positive pool, from `Neow`'s own
# conditionals.
_CURSE_EXCLUDES = {
    "CURSED_PEARL": "GOLDEN_PEARL",
    "HEFTY_TABLET": "ARCANE_SCROLL",
    "LEAFY_POULTICE": "NEW_LEAF",
    "PRECARIOUS_SHEARS": "PRECISE_SCISSORS",
}

# `SlimesWeak.GenerateMonsters`' pools, in declaration order.
_SLIME_SMALL = ("LEAF_SLIME_S", "TWIG_SLIME_S")
_SLIME_MEDIUM = ("LEAF_SLIME_M", "TWIG_SLIME_M")
_SLIMES_WEAK_ID = "SLIMES_WEAK"

# The sample's Ancient choice is the first offered one whose relic pick-up opens no
# second prompt (``sts2_native_sim.ancient.PROMPT_FREE_CHOICES``), so reaching the
# first fight does not depend on the nested prompts, which are their own ticket's work.


@dataclass(frozen=True)
class Sample:
    """One run the script drives end to end, and what makes it worth driving."""

    seed: str
    ascension: int = 0
    # A wounded start is how the Ancient's heal becomes observable at Ascension 0: a run
    # that uses the character's starting loadout already stands at full HP, so healing to
    # full would look the same as not healing at all.
    wounded: bool = False

    @property
    def label(self) -> str:
        return f"{self.seed}@A{self.ascension}" + (" wounded" if self.wounded else "")


# Both act-1 Act variants, both Ancient heals, every shape the row-1 node produced for
# these seeds before the Ancient room existed (randomised composition, fixed composition,
# fixed composition with randomised starting moves), and one wounded start.
_SAMPLE = (
    Sample("ANCIENT01"),
    Sample("ANCIENT02"),
    Sample("ANCIENT03"),
    Sample("ANCIENT03", 2),
    Sample("ANCIENT03", wounded=True),
    Sample("ANCIENT04"),
    Sample("ANCIENT06"),
    Sample("ANCIENT10"),
    Sample("ANCIENT12"),
    Sample("ANCIENT13"),
    Sample("ANCIENT15"),
    Sample("ANCIENT19"),
    Sample("ANCIENT20"),
    Sample("ANCIENT21"),
    Sample("ANCIENT22"),
)

# The seeds the offer port is checked against, beyond the sample above. Each one only
# needs its run started and its Ancient room entered, so the sweep is cheap and the
# port's agreement with the live run is a property of this repository rather than of a
# probe run once by hand.
_OFFER_SWEEP = tuple(f"ANCIENT{index:02d}" for index in range(1, 25)) + tuple(
    f"ACTVARIANT{index:02d}" for index in range(1, 14)
)

# What this simulator produced for the same seed *before* the Ancient room was entered:
# the state a run reached by travelling straight to its first row-1 node, which appended
# only one map-point history entry and therefore had TotalFloor == 1. Recorded on game
# assembly A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52; the run
# asserts that build before using it.
_PRE_CHANGE_BUILD = "A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52"
_PRE_CHANGE = {
    "ANCIENT01": {"entry_action": "choose_map:0:1", "composition": ["CORPSE_SLUG", "CORPSE_SLUG"]},
    "ANCIENT02": {"entry_action": "choose_map:2:1", "composition": ["LEAF_SLIME_S", "TWIG_SLIME_M", "TWIG_SLIME_S"]},
    "ANCIENT03": {"entry_action": "choose_map:0:1", "composition": ["NIBBIT"]},
    "ANCIENT04": {"entry_action": "choose_map:2:1", "composition": ["TWIG_SLIME_S", "LEAF_SLIME_M", "LEAF_SLIME_S"]},
    "ANCIENT06": {"entry_action": "choose_map:0:1", "composition": ["LEAF_SLIME_S", "LEAF_SLIME_M", "TWIG_SLIME_S"]},
    "ANCIENT10": {"entry_action": "choose_map:1:1", "composition": ["SEAPUNK"]},
    "ANCIENT12": {"entry_action": "choose_map:1:1", "composition": ["LEAF_SLIME_S", "TWIG_SLIME_M", "TWIG_SLIME_S"]},
    "ANCIENT13": {"entry_action": "choose_map:2:1", "composition": ["CORPSE_SLUG", "CORPSE_SLUG"]},
    "ANCIENT15": {"entry_action": "choose_map:0:1", "composition": ["LEAF_SLIME_S", "TWIG_SLIME_M", "TWIG_SLIME_S"]},
    "ANCIENT19": {"entry_action": "choose_map:2:1", "composition": ["SEAPUNK"]},
    "ANCIENT20": {"entry_action": "choose_map:1:1", "composition": ["FUZZY_WURM_CRAWLER"]},
    "ANCIENT21": {"entry_action": "choose_map:1:1", "composition": ["SHRINKER_BEETLE"]},
    "ANCIENT22": {"entry_action": "choose_map:0:1", "composition": ["CORPSE_SLUG", "CORPSE_SLUG"]},
}


def neow_offer(seed: str) -> list[str]:
    """Port of `Neow.GenerateInitialOptions` for one fully unlocked single-player seed.

    `EventModel.BeginEvent` keys the event's generator on the run seed, the player
    slot and the event's own id, so the draws below are the ones the Ancient room
    makes on this seed.
    """
    rng = rng_for_content(seed, _ANCIENT_EVENT_ID)
    curse = rng.next_item(list(_NEOW_CURSE))
    positives = [relic for relic in _NEOW_POSITIVE if relic not in _MULTIPLAYER_ONLY]
    if curse in _CURSE_EXCLUDES:
        positives.remove(_CURSE_EXCLUDES[curse])
    if curse != "LARGE_CAPSULE":
        positives.append("LAVA_ROCK" if rng.next_bool() else "SMALL_CAPSULE")
    positives.append("NUTRITIOUS_OYSTER" if rng.next_bool() else "STONE_HUMIDIFIER")
    positives.append("NEOWS_TALISMAN" if rng.next_bool() else "POMANDER")
    offered = rng.unstable_shuffle(positives)[:2]
    return [offered[0], offered[1], curse]


def slime_composition(seed: str, total_floor: int) -> list[str]:
    """Port of `SlimesWeak.GenerateMonsters` at the floor `EncounterModel` seeds it with.

    `EncounterModel.GenerateMonstersWithSlots` builds the per-encounter generator from
    the run's seed, `runState.TotalFloor` and the encounter id, which is why the
    Ancient room's history entry decides this composition.
    """
    rng = Rng(deterministic_hash_code(seed) + total_floor + deterministic_hash_code(_SLIMES_WEAK_ID))
    small = list(_SLIME_SMALL)
    first = small.pop(rng.next_int(len(small)))
    rng.next_int(len(small))  # the remaining small slime is the only option, and the draw is real
    medium = _SLIME_MEDIUM[rng.next_int(len(_SLIME_MEDIUM))]
    return [first, medium, small[0]]


def _run_state(sample: Sample) -> dict:
    """The reset request for one sample.

    A sample that uses the character's starting loadout is the fully unlocked shipped
    run start the ticket asks about; the wounded sample keeps the same run but hands the
    simulator a low current HP (which the loadout path would overwrite), so that the
    Ancient's heal has somewhere to heal to.
    """
    state = {
        "game_build": {},
        "seed": sample.seed,
        "rng_counters": {},
        "character": "IRONCLAD",
        "ascension": sample.ascension,
        "encounter": "first",
        "current_hp": 80,
        "max_hp": 80,
        "deck": [],
        "gold": 99,
        "use_character_starting_loadout": not sample.wounded,
    }
    if sample.wounded:
        state.update({
            "current_hp": 10,
            "deck": [{"instance_id": f"strike-{index}", "model_id": "STRIKE_IRONCLAD"} for index in range(10)],
        })
    return state


def _map_digest(observation: dict) -> str:
    """A stable digest of the map a run generated, visited state excluded.

    ``points`` is every grid point the act's map has, starting point excluded, so the
    digest answers "is this the same map" and not "has the run travelled".
    """
    shape = [
        {"coord": point["coord"], "point_type": point["point_type"], "children": point["children"]}
        for point in observation["map"]["points"]
    ]
    return hashlib.sha256(json.dumps(shape, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _enemies(observation: dict) -> list[dict]:
    return [
        {"model_id": creature["model_id"], "hp": creature["hp"]}
        for creature in observation["combat"]["creatures"]
        if creature["side"] == "Enemy"
    ]


def _check(condition: bool, sample: Sample, message: str) -> None:
    if not condition:
        raise AssertionError(f"{sample.label}: {message}")


def _drive(worker, sample: Sample) -> dict:
    """Travel the Ancient room and the first row-1 node, recording what each step saw."""
    seed, ascension = sample.seed, sample.ascension
    reset = worker.run_reset(_run_state(sample))
    reset_observation = reset["observation"]
    actions = reset_observation["decision"]["legal_actions"]
    _check(reset_observation["decision"]["kind"] == "map_choice", sample, "run start is not a map choice")
    _check(len(actions) == 1, sample, f"run start offers {len(actions)} actions, not just the Ancient node")
    action = actions[0]
    _check(action["kind"] == "choose_map", sample, f"run start offers a {action['kind']} action")
    _check(
        (action["parameters"]["col"], action["parameters"]["row"]) == _ANCIENT_COORD
        and action["parameters"]["point_type"] == _ANCIENT_POINT_TYPE,
        sample, f"run start offers {action['parameters']} instead of the Ancient node",
    )
    record: dict = {
        "label": sample.label,
        "seed": seed,
        "ascension": ascension,
        "act_variant": reset_observation["run"]["act_variant"],
        "hp_at_reset": reset["scoring_features"]["current_hp"],
        "ancient_action": action["action_id"],
        "reset_hash": reset["state_hash"],
        "counters_at_reset": reset_observation["run"]["rng_counters"],
        "map_at_reset": _map_digest(reset_observation),
        "total_floor_at_reset": reset["scoring_features"]["total_floor"],
        "act_floor_at_reset": reset["scoring_features"]["act_floor"],
    }

    entered = worker.run_step(action["action_id"])
    observation = entered["observation"]
    _check(observation["decision"]["kind"] == "event_choice", sample, f"the Ancient room decided {observation['decision']['kind']!r}")
    _check(observation["event"]["model_id"] == _ANCIENT_EVENT_ID, sample, f"the Ancient room is {observation['event']['model_id']}")
    options = observation["event"]["options"]
    offered = [option["relic_model_id"] for option in options]
    record.update({
        "entered_hash": entered["state_hash"],
        "offered": offered,
        "option_indices": [option["option_index"] for option in options],
        "counters_at_ancient": observation["run"]["rng_counters"],
        "hp_at_ancient": observation["run"]["current_hp"],
        "max_hp_at_ancient": observation["run"]["max_hp"],
        "total_floor_at_ancient": entered["scoring_features"]["total_floor"],
        "act_floor_at_ancient": entered["scoring_features"]["act_floor"],
        "entered_handle": entered["state_handle"],
    })
    _check(len(options) == 3, sample, f"the Ancient offered {len(options)} choices, not three")
    _check(
        [option["option_index"] for option in options] == [0, 1, 2],
        sample, "the offered choices do not report their index in offer order",
    )
    _check(all(relic is not None for relic in offered), sample, f"an offered choice grants no relic: {offered}")
    _check(len(set(offered)) == len(offered), sample, f"the same relic was offered twice: {offered}")
    _check(offered[2] in _NEOW_CURSE, sample, f"the last choice {offered[2]} is not one of the Ancient's curse options")
    _check(
        all(relic in _NEOW_POSITIVE + _NEOW_POSITIVE_PAIR for relic in offered[:2]),
        sample, f"the first two choices are not relic choices: {offered[:2]}",
    )
    # One legal action per *selectable* offered choice, in the order the run offered them.
    # A page can also carry an option that is locked or already chosen; those are not
    # choices a caller may take, so they are not what the legal actions correspond to.
    selectable = [option for option in options if not option["locked"] and not option["chosen"]]
    choice_actions = [legal for legal in entered["legal_actions"] if legal["kind"] == "choose_event"]
    _check(
        len(choice_actions) == len(selectable),
        sample, f"{len(choice_actions)} legal actions for {len(selectable)} selectable offered choices",
    )
    _check(
        [legal["parameters"]["option_index"] for legal in choice_actions] == [option["option_index"] for option in selectable],
        sample, "the legal actions do not follow the offered order",
    )
    _check(
        [legal["parameters"]["relic_model_id"] for legal in choice_actions] == [option["relic_model_id"] for option in selectable],
        sample, "a legal action does not report the relic its choice grants",
    )

    pick = prompt_free_choice_action(entered)
    if pick is None:
        raise AssertionError(f"{sample.label}: no offered choice picks a relic that opens no second prompt: {offered}")
    driven = drive_choice(worker, pick)
    _check(
        driven.state["observation"]["decision"]["kind"] == "event_complete",
        sample,
        f"the Ancient choice did not finish ({driven.state['observation']['decision']['kind']})",
    )
    record["chosen"] = pick["parameters"]["relic_model_id"]
    record["nested_steps"] = len(driven.decisions)

    left = worker.run_step("leave_event")
    _check(left["observation"]["decision"]["kind"] == "map_choice", sample, "leaving the Ancient did not return to the map")
    record["map_after_ancient"] = _map_digest(left["observation"])
    record["hp_leaving_ancient"] = left["scoring_features"]["current_hp"]
    record["max_hp_leaving_ancient"] = left["scoring_features"]["max_hp"]
    _check(left["scoring_features"]["total_floor"] == 1, sample, f"TotalFloor is {left['scoring_features']['total_floor']} after the Ancient room")
    _check(left["scoring_features"]["act_floor"] == 1, sample, f"ActFloor is {left['scoring_features']['act_floor']} after the Ancient room")
    row_one = left["legal_actions"]
    _check(
        bool(row_one) and all(action["parameters"]["row"] == 1 and action["parameters"]["point_type"] == "Monster" for action in row_one),
        sample, f"the Ancient's children are not the row-1 monster nodes: {[action['action_id'] for action in row_one]}",
    )
    # The fixed row-1 rule ("the first legal map action in the order the environment
    # reports them") must pick the node the pre-change run picked, so that the fight
    # being compared is the same fight. The recording is an Ascension-0 map, and
    # SwarmingElites moves where the row-1 nodes are, so the node comparison is only
    # made where the recording applies.
    if not sample.wounded:
        expected_entry = _PRE_CHANGE[seed]["entry_action"]
        _check(row_one[0]["action_id"] == expected_entry, sample,
               f"the first row-1 action is {row_one[0]['action_id']}, not the recorded {expected_entry}")

    combat = worker.run_step(row_one[0]["action_id"])
    observation = combat["observation"]
    _check(observation["decision"]["kind"] == "combat_action", sample, f"the row-1 node resolved to {observation['decision']['kind']!r}")
    enemies = _enemies(observation)
    record.update({
        "combat_hash": combat["state_hash"],
        "combat_handle": combat["state_handle"],
        "enemies": enemies,
        "total_floor_at_combat": combat["scoring_features"]["total_floor"],
        "act_floor_at_combat": combat["scoring_features"]["act_floor"],
        "counters_at_combat": observation["run"]["rng_counters"],
    })
    _check(combat["scoring_features"]["total_floor"] == 2, sample, f"TotalFloor is {combat['scoring_features']['total_floor']} at the first fight, not 2")
    _check(combat["scoring_features"]["act_floor"] == 2, sample, f"ActFloor is {combat['scoring_features']['act_floor']} at the first fight, not 2")
    return record


def _assert_common(records: dict[Sample, dict], build: dict) -> None:
    if build["assembly_sha256"] != _PRE_CHANGE_BUILD:
        raise AssertionError(
            f"the recorded pre-change fights are for game assembly {_PRE_CHANGE_BUILD}, this machine runs "
            f"{build['assembly_sha256']}; re-record the table from a build without the Ancient room before "
            f"trusting the comparison (``--snapshot`` prints this build's facts)"
        )
    for sample, record in records.items():
        seed, ascension = sample.seed, sample.ascension
        _check(record["total_floor_at_reset"] == 0 and record["act_floor_at_reset"] == 0, sample,
               "the run did not start with empty floor bookkeeping")
        # Entering the Ancient room must consume nothing the run's own streams count,
        # and must not disturb the map the run generated.
        _check(record["counters_at_ancient"] == record["counters_at_reset"], sample,
               f"entering the Ancient moved the run's counters: {record['counters_at_reset']} -> {record['counters_at_ancient']}")
        _check(record["map_after_ancient"] == record["map_at_reset"], sample, "entering the Ancient regenerated the map")
        _check(record["total_floor_at_ancient"] == 1, sample,
               f"TotalFloor is {record['total_floor_at_ancient']} in the Ancient room, not 1")
        _check(record["act_floor_at_ancient"] == 1, sample,
               f"ActFloor is {record['act_floor_at_ancient']} in the Ancient room, not 1")
        # The Ancient heals the player; WearyTraveler multiplies the heal by 0.8. The HP is
        # read from the map state the run reaches *after* leaving the room, so a relic the
        # chosen option grants has already been applied.
        max_hp = record["max_hp_leaving_ancient"]
        expected_hp = max_hp if ascension < _HEAL_REDUCTION_ASCENSION else int(max_hp * 0.8)
        _check(record["hp_leaving_ancient"] == expected_hp, sample,
               f"leaving the Ancient left {record['hp_leaving_ancient']} HP, not {expected_hp}")
        # A wounded start is what makes the heal itself observable: every other sample
        # begins at full HP, so "healed to full" and "not healed at all" would look alike.
        if sample.wounded:
            _check(record["hp_leaving_ancient"] > record["hp_at_reset"], sample,
                   f"the Ancient's heal is not observable: {record['hp_at_reset']} -> {record['hp_leaving_ancient']}")
        # The offer is the one Neow's own generation produces for this seed.
        expected_offer = neow_offer(seed)
        _check(record["offered"] == expected_offer, sample,
               f"the Ancient offered {record['offered']}, the ported offer is {expected_offer}")
        # The composition is the one the shipped SlimesWeak generator produces at
        # TotalFloor == 2, or the recorded pre-change composition for an encounter that
        # does not randomise its monsters.
        recorded = _PRE_CHANGE[seed]["composition"]
        observed = [enemy["model_id"] for enemy in record["enemies"]]
        if all(model in _SLIME_SMALL + _SLIME_MEDIUM for model in recorded):
            at_one, at_two = slime_composition(seed, 1), slime_composition(seed, 2)
            _check(at_one == recorded, sample,
                   f"the SlimesWeak port does not reproduce the recorded floor-1 composition: {at_one} != {recorded}")
            _check(observed == at_two, sample,
                   f"the first fight's randomised composition is {observed}, the floor-2 composition is {at_two}")
        else:
            _check(observed == recorded, sample,
                   f"the first fight's composition moved to {observed}, the recorded floor-1 composition is {recorded}")
        # Monster HP is drawn per monster from the run's Niche stream, so its count must
        # not move either.
        _check(record["counters_at_combat"]["Niche"] == record["counters_at_reset"]["Niche"] + len(observed), sample,
               "the Niche stream did not draw exactly one value per enemy")
    # The Ascension-2 sample must otherwise be the same run. Ascension moves where the
    # row-1 nodes are (SwarmingElites), but the encounter is the act pool's first normal
    # encounter either way, and no ascension touches the act-1 encounter pools: the same
    # entry of the same pool is the comparison, not the same map coordinate.
    for sample in records:
        reduced = Sample(sample.seed, _HEAL_REDUCTION_ASCENSION)
        if sample == Sample(sample.seed) and reduced in records:
            plain = [enemy["model_id"] for enemy in records[sample]["enemies"]]
            ascended = [enemy["model_id"] for enemy in records[reduced]["enemies"]]
            _check(plain == ascended, reduced,
                   f"ascension {_HEAL_REDUCTION_ASCENSION} changed the first encounter: {plain} -> {ascended}")


def _assert_deterministic(records: dict[Sample, dict], pool, sample: Sample) -> dict:
    """The same sample on a second worker reaches the same states, and restore replays them.

    Each worker restores the handles it minted itself: a branch handle names a node in
    one worker's local history, and the next ``run_reset`` on that worker clears it.
    """
    first_worker = pool.workers[0]
    second_worker = pool.workers[1 % len(pool.workers)]
    first = _drive(first_worker, sample)
    second = _drive(second_worker, sample)
    recorded = records[sample]
    for field in ("reset_hash", "entered_hash", "combat_hash"):
        _check(first[field] == recorded[field], sample,
               f"driving the sample again moved {field} ({recorded[field]} -> {first[field]})")
        _check(second[field] == recorded[field], sample,
               f"{field} differs on a second worker ({recorded[field]} -> {second[field]})")
    for field in ("offered", "option_indices", "enemies", "total_floor_at_combat", "act_floor_at_combat"):
        _check(second[field] == recorded[field], sample,
               f"a second worker disagrees about {field}: {recorded[field]} -> {second[field]}")
    for worker, record in ((first_worker, first), (second_worker, second)):
        restored = worker.restore(record["entered_handle"])
        _check(restored["state_hash"] == record["entered_hash"], sample,
               f"restoring the Ancient room produced {restored['state_hash']}, not {record['entered_hash']}")
        restored = worker.restore(record["combat_handle"])
        _check(restored["state_hash"] == record["combat_hash"], sample,
               f"restoring the first fight produced {restored['state_hash']}, not {record['combat_hash']}")
    return second


def _check_offer_against_port(worker, seed: str) -> dict:
    """Start one more run and compare the Ancient's offer with the port.

    Only the offer, the run's counters and its floor bookkeeping are read, so the sweep
    can cover many seeds at the price of one map step each; the fights are the sample's
    subject, not the sweep's.
    """
    sample = Sample(seed)
    reset = worker.run_reset(_run_state(sample))
    counter_before = reset["observation"]["run"]["rng_counters"]
    action = ancient_action(reset)
    if action is None:
        _check(False, sample, "the run does not offer the Ancient node at its start")
        raise AssertionError("the run does not offer the Ancient node at its start")
    entered = worker.run_step(action["action_id"])
    observation = entered["observation"]
    _check(observation["event"]["model_id"] == _ANCIENT_EVENT_ID, sample, f"the Ancient room is {observation['event']['model_id']}")
    expected = neow_offer(seed)
    offered = [option["relic_model_id"] for option in observation["event"]["options"]]
    _check(offered == expected, sample, f"the Ancient offered {offered}, the ported offer is {expected}")
    _check(observation["run"]["rng_counters"] == counter_before, sample, "entering the Ancient moved the run's counters")
    _check(entered["scoring_features"]["total_floor"] == 1, sample, "entering the Ancient did not advance TotalFloor to 1")
    return {"act_variant": reset["observation"]["run"]["act_variant"], "offered": offered}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4, help="native workers to spread the sample over")
    parser.add_argument("--snapshot", action="store_true", help="print the per-seed facts instead of asserting")
    arguments = parser.parse_args()

    with NativeWorkerPool(arguments.workers) as pool:
        records = {
            sample: _drive(pool.workers[index % arguments.workers], sample)
            for index, sample in enumerate(_SAMPLE)
        }
        sweep = {
            seed: _check_offer_against_port(pool.workers[index % arguments.workers], seed)
            for index, seed in enumerate(_OFFER_SWEEP)
        }
        if arguments.snapshot:
            print(json.dumps({record["label"]: record for record in records.values()}, indent=2, sort_keys=True))
            print(json.dumps({"offer_sweep": sweep}, indent=2, sort_keys=True))
            return

        _assert_common(records, pool.workers[0].build)
        repeated = _assert_deterministic(records, pool, _SAMPLE[0])

        print(json.dumps({
            "success": True,
            "game_build": pool.workers[0].build,
            "samples": [sample.label for sample in _SAMPLE],
            "ancient_offers": {record["label"]: record["offered"] for record in records.values()},
            "offer_sweep_seeds": len(sweep),
            "first_fights": {record["label"]: [enemy["model_id"] for enemy in record["enemies"]]
                             for record in records.values()},
            "total_floor_at_first_fight": {record["label"]: record["total_floor_at_combat"]
                                           for record in records.values()},
            "hp_leaving_ancient": {record["label"]: record["hp_leaving_ancient"]
                                   for record in records.values()},
            "repeat_of": _SAMPLE[0].label,
            "repeat_combat_hash": repeated["combat_hash"],
        }, indent=2))


if __name__ == "__main__":
    main()
