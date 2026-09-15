"""Shipped-game acceptance for driving an Ancient choice and any nested prompt to completion.

Taking one of the Ancient's offered choices has to obtain the relic that choice reported,
through the game's own option-completion path, and consume only the randomness the game
itself consumes. Some choices open a second, blocking prompt — a card select, a reward set,
a bundle pick, or a reward set *inside* a reward set, which is what `NEOWS_BONES` reaches
when the relic it offers offers rewards of its own. Every one of those is answerable
through the same headless decision loop as any other run-mode decision.

The script drives real native workers over the same 37-seed offer sweep ticket 03 uses —
both act-1 Act variants — and takes *every* offered choice on each seed, walking the first
legal action at each step. Per choice it checks:

* the relic the choice reported is in the run's relic list afterwards, the relics it did
  not grant are untouched, and the only extra relics are the ones the chosen relic's own
  effect grants (``LARGE_CAPSULE`` and ``SMALL_CAPSULE`` pull relics, ``NEOWS_BONES``
  offers two);
* the choice reaches ``event_complete`` and the room can then be left for the map;
* the nested prompts it opens are exactly the kinds declared for its relic — no choice
  opens a prompt kind this table does not describe — and every declared kind is reached
  somewhere in the sweep, so card select, reward set and bundle pick are all covered;
* a choice whose relic opens no prompt reaches ``event_complete`` with no intervening
  decision at all;
* a reward set that begins while another reward set is open is driven to completion and
  the enclosing set comes back as the decision (observable as ``depth`` 2 in the reward
  snapshot, then depth 1 again), whether the nested set is taken from or skipped;
* the run-level RNG counters afterwards are the ones the game's own code produces: a
  choice that draws nothing the run counts leaves every counter where it was, the choices
  that do draw move exactly the counters their shipped model draws, and ``NEOWS_BONES``
  costs its own curse draw plus exactly what each relic it granted costs when the Ancient
  offers that relic directly.

The last check is the ticket's answer to "only the game's randomness is consumed": the
nested reward set is not a reimplementation, so a relic taken from inside one draws what
the same relic draws from the Ancient's own offer. It is the simulator-side claim — the
counters a shipped run reaches for the same seed and choice are ticket 15's comparison.

Requires the shipped game and a Godot-hosted worker (the repository's ``*_acceptance.py``
convention). ``--snapshot`` prints the per-choice facts instead of asserting them, which is
how the tables below are maintained.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sts2_native_sim import NativeWorkerPool
from sts2_native_sim.ancient import (
    EVENT_COMPLETE,
    MAP_CHOICE,
    PROMPT_FREE_CHOICES,
    NestedDecision,
    ancient_action,
    choice_actions,
    drive_choice,
)

# The shipped build these tables were read and observed against. Acceptance that asserts
# recorded game facts fails closed on a mismatch rather than reporting a difference between
# the game and the simulator where there is only a different game.
_OBSERVED_BUILD = "A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52"

# The seeds of ticket 03's offer sweep: the 24 `ANCIENT*` seeds and the 13 `ACTVARIANT*`
# seeds, which between them cover both act-1 Act variants. Every offered choice on every
# seed is driven here, so the classification and counter tables below are complete
# statements about what these seeds offer.
_SEEDS = tuple(f"ANCIENT{index:02d}" for index in range(1, 25)) + tuple(
    f"ACTVARIANT{index:02d}" for index in range(1, 14)
)

# Every relic the act-1 Ancient offers on these seeds, with the decision kinds its pick-up
# opens. An empty set means the pick-up runs no second prompt at all.
#
# The kinds are the run's own decision vocabulary, so the mapping from a decision to the
# actions a caller may take is the one below. `option_choice` is the shipped
# `CardSelectCmd.FromChooseABundleScreen` branch: no offered Ancient relic reaches
# `RelicSelectCmd.FromChooseARelicScreen`, which reports the same kind.
#
# `NEOWS_BONES` is the one choice whose pick-up offers a reward set, and the relics that
# reward set offers may themselves open a card select, so its kinds are the union of what
# its own offer can reach rather than a fixed sequence. `ARCANE_SCROLL` is a `Neow`
# positive relic these 37 seeds never draw, so it is deliberately not described here.
_NESTED_PROMPTS: dict[str, frozenset[str]] = {
    "BOOMING_CONCH": frozenset(),
    "CURSED_PEARL": frozenset(),
    "FISHING_ROD": frozenset(),
    "GOLDEN_PEARL": frozenset(),
    "HEFTY_TABLET": frozenset({"card_choice"}),
    "KALEIDOSCOPE": frozenset({"custom_reward_choice"}),
    "LARGE_CAPSULE": frozenset(),
    "LAVA_ROCK": frozenset(),
    "LEAD_PAPERWEIGHT": frozenset({"card_choice"}),
    "LEAFY_POULTICE": frozenset(),
    "LOST_COFFER": frozenset({"custom_reward_choice"}),
    "NEOWS_BONES": frozenset({"custom_reward_choice", "card_choice"}),
    "NEOWS_TALISMAN": frozenset(),
    "NEOWS_TORMENT": frozenset(),
    "NEW_LEAF": frozenset({"card_choice"}),
    "NUTRITIOUS_OYSTER": frozenset(),
    "PHIAL_HOLSTER": frozenset(),
    "POMANDER": frozenset({"card_choice"}),
    "PRECARIOUS_SHEARS": frozenset({"card_choice"}),
    "PRECISE_SCISSORS": frozenset({"card_choice"}),
    "SCROLL_BOXES": frozenset({"option_choice"}),
    "SILKEN_TRESS": frozenset(),
    "SILVER_CRUCIBLE": frozenset(),
    "SMALL_CAPSULE": frozenset({"custom_reward_choice"}),
    "STONE_HUMIDIFIER": frozenset(),
    "WINGED_BOOTS": frozenset(),
}

# The actions a decision of each kind offers. A caller selects among these, so a decision
# whose actions do not belong to its kind is not answerable.
_DECISION_ACTION_KINDS = {
    "card_choice": frozenset({"choose_cards"}),
    "option_choice": frozenset({"choose_option"}),
    "custom_reward_choice": frozenset({"choose_custom_reward", "skip_custom_rewards"}),
}

# How many further relics each offered relic's own pick-up grants, over and above itself.
_EXTRA_RELICS = {"LARGE_CAPSULE": 2, "SMALL_CAPSULE": 1, "NEOWS_BONES": 2}

# The run-level randomness each offered relic's shipped code draws, in the named counters
# the run reports. A relic with no entry draws nothing the run counts.
_COUNTER_DRAWS: dict[str, dict[str, int]] = {
    # `NeowsBones.AfterObtained` draws one `Rng.Niche` item per curse it adds, and offers a
    # reward set whose relics draw whatever they draw when the Ancient offers them directly;
    # `_bones_cost` composes that.
    "NEOWS_BONES": {"Niche": 1},
    # `NewLeaf.AfterObtained` transforms a card with `CardCmd.TransformToRandom(Rng.Niche)`.
    "NEW_LEAF": {"Niche": 1},
    # `Kaleidoscope.AfterObtained` stable-shuffles the other characters' card pools with
    # `Rng.Niche` and then builds a card reward per drawn card.
    "KALEIDOSCOPE": {"Niche": 6},
    # `PhialHolster.AfterObtained` gains two potion slots and procures one potion per slot.
    "PHIAL_HOLSTER": {"CombatPotionGeneration": 4},
}


def _run_state(seed: str) -> dict:
    """The reset request for one sample: the fully unlocked shipped run start."""
    return {
        "game_build": {}, "seed": seed, "rng_counters": {}, "character": "IRONCLAD",
        "ascension": 0, "encounter": "first", "current_hp": 80, "max_hp": 80, "deck": [],
        "gold": 99, "use_character_starting_loadout": True,
    }


def _moved(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """The counters that moved between two observations, with their deltas."""
    return {name: value - before.get(name, 0) for name, value in after.items() if value != before.get(name, 0)}


def _add(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    total = dict(left)
    for name, value in right.items():
        total[name] = total.get(name, 0) + value
    return {name: value for name, value in total.items() if value}


def _bones_cost(granted: list[str]) -> dict[str, int]:
    """What `NEOWS_BONES` costs: its own curse draw plus what each granted relic draws."""
    return _add(_COUNTER_DRAWS["NEOWS_BONES"],
                {k: v for relic in granted for k, v in _COUNTER_DRAWS.get(relic, {}).items()})


def _decision_facts(decision: NestedDecision) -> dict:
    """One nested decision, as a caller sees it, and the action the caller took from it."""
    state = decision.state
    options = (state["observation"].get("outstanding_choice") or {}).get("options") or []
    rewards = state["observation"].get("outstanding_rewards") or {}
    return {
        "kind": state["observation"]["decision"]["kind"],
        "action_kinds": sorted({action["kind"] for action in state["legal_actions"]}),
        "action_ids": [action["action_id"] for action in state["legal_actions"]],
        "taken": decision.action_id,
        # A bundle pick's options carry the cards of each bundle; a relic pick's carry a
        # model id. Both report `option_choice`, so the snapshot is what tells them apart.
        "option_shape": sorted({("cards" if option.get("cards") else "model_id") for option in options}),
        "reward_depth": rewards.get("depth"),
        "reward_kinds": [reward["reward"]["kind"] for reward in rewards.get("rewards", []) if not reward["reward"]["selected"]],
    }


def _drive(worker, seed: str, choice_index: int, *, choose=None) -> dict:
    """Take one offered Ancient choice, answer every prompt, and record what happened."""
    reset = worker.run_reset(_run_state(seed))
    ancient = ancient_action(reset)
    if ancient is None:
        raise AssertionError(f"{seed}: a run does not offer the act's Ancient node at its start")
    entered = worker.run_step(ancient["action_id"])
    options = choice_actions(entered)
    if choice_index >= len(options):
        raise AssertionError(f"{seed}: the Ancient offered {len(options)} choices, not {choice_index + 1}")
    action = options[choice_index]
    drive = drive_choice(worker, action, choose=choose)
    left = worker.run_step("leave_event")
    counters_before = reset["observation"]["run"]["rng_counters"]
    counters_after = drive.state["observation"]["run"]["rng_counters"]
    return {
        "label": f"{seed}#{choice_index}",
        "seed": seed,
        "choice_index": choice_index,
        "relic": action["parameters"]["relic_model_id"],
        "decisions": [_decision_facts(state) for state in drive.decisions],
        "relics_before": entered["observation"]["run"]["relics"],
        "relics_after": drive.state["observation"]["run"]["relics"],
        "counter_moves": _moved(counters_before, counters_after),
        "counters_after": counters_after,
        "reset_hash": reset["state_hash"],
        "entered_hash": entered["state_hash"],
        "driven_hash": drive.state["state_hash"],
        "driven_handle": drive.state["state_handle"],
        "left_hash": left["state_hash"],
        "final_kind": drive.state["observation"]["decision"]["kind"],
        "left_kind": left["observation"]["decision"]["kind"],
    }


def _kinds(record: dict) -> frozenset[str]:
    return frozenset(decision["kind"] for decision in record["decisions"])


def _granted(record: dict) -> list[str]:
    """The relics the choice's own effect added, over the one the choice reported."""
    extras = record["relics_after"][len(record["relics_before"]):]
    return [relic for relic in extras if relic != record["relic"]]


def _assert_choice(record: dict) -> None:
    label, relic = record["label"], record["relic"]
    def check(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(f"{label} ({relic}): {message}")

    check(record["final_kind"] == EVENT_COMPLETE, f"the choice ended in {record['final_kind']!r}, not {EVENT_COMPLETE!r}")
    check(record["left_kind"] == MAP_CHOICE, f"leaving the Ancient gave {record['left_kind']!r}, not {MAP_CHOICE!r}")
    # The relic the action reported is the relic the run holds, and nothing else moved.
    check(record["relics_before"] == record["relics_after"][:len(record["relics_before"])],
          f"the run's relics changed before the chosen one: {record['relics_before']} -> {record['relics_after']}")
    check(relic in record["relics_after"], f"the run does not hold the relic the choice reported: {record['relics_after']}")
    # The only relics beyond the reported one are the ones the choice's own effect grants;
    # a capsule pulls a further relic, and one of those could itself be a capsule, so those
    # two are bounded rather than counted.
    extras = len(record["relics_after"]) - len(record["relics_before"])
    if relic in _EXTRA_RELICS:
        check(extras >= 1 + _EXTRA_RELICS[relic],
              f"the choice left {extras} relics, at least {1 + _EXTRA_RELICS[relic]} were expected")
    else:
        check(extras == 1, f"the choice left {extras} relics, only the one it reported was expected")
    # Every decision the choice opens is answerable: its kind and its actions agree, it offers at
    # least one action to select, and the action the driver took is one of them.
    for decision in record["decisions"]:
        expected = _DECISION_ACTION_KINDS.get(decision["kind"])
        check(expected is not None, f"a decision reported an unknown kind {decision['kind']!r}")
        check(decision["action_kinds"] and set(decision["action_kinds"]) <= expected,
              f"a {decision['kind']} offered {decision['action_kinds']}")
        check(bool(decision["action_ids"]), f"a {decision['kind']} offered no legal action")
        check(decision["taken"] in decision["action_ids"],
              f"the driver took {decision['taken']!r}, which is not among {decision['action_ids']}")
        if decision["kind"] == "option_choice":
            check(decision["option_shape"] == ["cards"],
                  f"the bundle pick offered {decision['option_shape']} instead of bundles of cards")
        if decision["kind"] == "custom_reward_choice":
            check(isinstance(decision["reward_depth"], int), "a reward set reported no depth")
    # The prompts it opens are the ones declared for its relic, and no others.
    declared = _NESTED_PROMPTS[relic]
    check(_kinds(record) <= declared, f"the choice opened {sorted(_kinds(record))}, only {sorted(declared)} is declared")
    # A choice whose relic opens no prompt reaches the map with no intervening decision.
    if not declared:
        check(not record["decisions"], f"a prompt-free choice opened {[d['kind'] for d in record['decisions']]}")
    # Its randomness is the game's own.
    if relic == "NEOWS_BONES":
        check(record["counter_moves"] == _bones_cost(_granted(record)),
              f"the pick-up moved {record['counter_moves']}, not {_bones_cost(_granted(record))} "
              f"for the relics it granted {_granted(record)}")
    else:
        check(record["counter_moves"] == _COUNTER_DRAWS.get(relic, {}),
              f"the pick-up moved {record['counter_moves']}, not {_COUNTER_DRAWS.get(relic, {})}")


def _assert_sweep(records: list[dict]) -> None:
    offered = {record["relic"] for record in records}
    if offered != set(_NESTED_PROMPTS):
        unknown = sorted(offered - set(_NESTED_PROMPTS))
        missing = sorted(set(_NESTED_PROMPTS) - offered)
        raise AssertionError(
            f"the sweep and the nested-prompt table disagree: unknown {unknown}, never offered {missing}"
        )
    # Every declared kind is reachable and completable somewhere in the sweep, which is what
    # makes "card select, reward set and bundle pick are covered" a check rather than a hope.
    reached = frozenset(kind for record in records for kind in _kinds(record))
    declared = frozenset(kind for kinds in _NESTED_PROMPTS.values() for kind in kinds)
    if reached != declared:
        raise AssertionError(f"the sweep reached {sorted(reached)} of the declared {sorted(declared)}")
    # `leave_ancient`'s reachability rule must stay sound: every relic it prefers really is
    # prompt-free.
    prompt_free = frozenset(relic for relic, kinds in _NESTED_PROMPTS.items() if not kinds)
    if not PROMPT_FREE_CHOICES <= prompt_free:
        raise AssertionError(
            f"the reachability rule prefers {sorted(PROMPT_FREE_CHOICES - prompt_free)}, which do open a prompt"
        )
    # A reward set inside a reward set is the case ticket 03 could not reach, and the reason
    # the environment keeps the shipped synchronizer's stack.
    nested = [record for record in records for decision in record["decisions"]
              if decision["kind"] == "custom_reward_choice" and decision["reward_depth"] == 2]
    if not nested:
        raise AssertionError("no choice drove a reward set that began while another reward set was open")
    for record in records:
        for decision in record["decisions"]:
            if decision["kind"] == "custom_reward_choice" and decision["reward_depth"] not in (1, 2):
                raise AssertionError(f"{record['label']}: reward set depth {decision['reward_depth']}")


def _assert_deterministic(pool, records: list[dict]) -> dict:
    """The same choice on a second worker reaches the same states and the same counters.

    The sample is one of the choices that drove a reward set inside a reward set, so the
    reproduction covers the nesting rather than only the easy path.
    """
    sample = next(record for record in records if any(
        decision["reward_depth"] == 2 for decision in record["decisions"]))
    worker = pool.workers[1]
    repeated = _drive(worker, sample["seed"], sample["choice_index"])
    for field in ("relics_after", "counter_moves", "counters_after", "driven_hash", "left_hash"):
        if repeated[field] != sample[field]:
            raise AssertionError(f"{sample['label']}: a second worker disagrees about {field}: {sample[field]} -> {repeated[field]}")
    restored = worker.restore(repeated["driven_handle"])
    if restored["state_hash"] != sample["driven_hash"]:
        raise AssertionError(f"{sample['label']}: restoring the resolved choice gave {restored['state_hash']}")
    return repeated


def _skip_reward_sets(state: dict) -> str:
    """Skip the reward set the run is offering; take the first action when it forbids it."""
    for action in state["legal_actions"]:
        if action["kind"] == "skip_custom_rewards":
            return action["action_id"]
    return state["legal_actions"][0]["action_id"]


def _assert_skipping(pool, records: list[dict]) -> list[dict]:
    """A reward set resolved by skipping still hands the choice back and reaches the map.

    Skipping is the other half of the reward-set loop, and `NEOWS_BONES` is the case that
    skips a set nested inside a set that forbids skipping. The samples are the first offered
    choice of each relic whose pick-up offers a skippable set, plus the first `NEOWS_BONES`
    choice that actually nests one.
    """
    samples = [next(record for record in records if record["relic"] == relic)
               for relic in ("KALEIDOSCOPE", "LOST_COFFER", "SMALL_CAPSULE")]
    samples.append(next(
        record for record in records if record["relic"] == "NEOWS_BONES"
        and any(decision["kind"] == "custom_reward_choice" and decision["reward_depth"] == 2
                for decision in record["decisions"])
    ))
    skipped = []
    for index, record in enumerate(samples):
        drive = _drive(pool.workers[index % len(pool.workers)], record["seed"], record["choice_index"],
                       choose=_skip_reward_sets)
        label = f"{drive['label']} ({drive['relic']}, skipping)"
        if drive["final_kind"] != EVENT_COMPLETE or drive["left_kind"] != MAP_CHOICE:
            raise AssertionError(f"{label}: skipping left the run in {drive['final_kind']!r}")
        if drive["relic"] not in drive["relics_after"]:
            raise AssertionError(f"{label}: the reported relic is not held: {drive['relics_after']}")
        depths = [decision["reward_depth"] for decision in drive["decisions"]
                  if decision["kind"] == "custom_reward_choice"]
        if not depths:
            raise AssertionError(f"{label}: no reward set was answered by skipping")
        skipped.append({"label": label, "depths": depths, "relics": drive["relics_after"]})
    if not any(2 in entry["depths"] for entry in skipped):
        raise AssertionError("no reward set nested inside a reward set was resolved by skipping")
    return skipped


def _assert_build(pool) -> dict:
    """The tables below are statements about one shipped build; fail closed on any other."""
    build = pool.workers[0].build
    if build.get("assembly_sha256") != _OBSERVED_BUILD:
        raise AssertionError(
            f"these tables were observed against sts2.dll {_OBSERVED_BUILD}, this host has "
            f"{build.get('assembly_sha256')}: re-observe them with --snapshot before trusting a run"
        )
    return build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4, help="native workers to spread the sweep over; at least two")
    parser.add_argument("--snapshot", action="store_true", help="print the per-choice facts instead of asserting")
    arguments = parser.parse_args()
    if arguments.workers < 2:
        raise SystemExit("--workers must be at least 2: the repetition check needs a second worker")

    choices = [(seed, index) for seed in _SEEDS for index in range(3)]
    with NativeWorkerPool(arguments.workers) as pool:
        records: list[dict] = []
        for start in range(0, len(choices), arguments.workers):
            batch = choices[start:start + arguments.workers]
            records.extend(pool.map(lambda worker, choice: _drive(worker, *choice), batch))
        if arguments.snapshot:
            print(json.dumps({
                "choices": {record["label"]: record for record in records},
                "nested_prompts": {relic: sorted(kinds) for relic, kinds in sorted(_NESTED_PROMPTS.items())},
            }, indent=2, sort_keys=True))
            return

        build = _assert_build(pool)
        # The sweep-wide checks run first: they are the ones that can say "this table does not
        # describe what the sweep met", which a per-choice lookup would otherwise report as a
        # bare KeyError.
        _assert_sweep(records)
        for record in records:
            _assert_choice(record)
        repeated = _assert_deterministic(pool, records)
        skipped = _assert_skipping(pool, records)
        print(json.dumps({
            "success": True,
            "game_build": build,
            "seeds": len(_SEEDS),
            "choices_driven": len(records),
            "relics_offered": {relic: sorted(_NESTED_PROMPTS[relic]) for relic in sorted(_NESTED_PROMPTS)},
            "prompt_free_choices": len([record for record in records if not record["decisions"]]),
            "nested_reward_sets": len([
                decision for record in records for decision in record["decisions"]
                if decision["kind"] == "custom_reward_choice" and decision["reward_depth"] == 2
            ]),
            "nested_decisions": {kind: len([
                decision for record in records for decision in record["decisions"] if decision["kind"] == kind
            ]) for kind in sorted(_DECISION_ACTION_KINDS)},
            "counter_moves": {relic: _COUNTER_DRAWS.get(relic, {}) for relic in sorted(_COUNTER_DRAWS)},
            "skipped_reward_sets": skipped,
            "repeat_of": f"{repeated['seed']}#{repeated['choice_index']}",
            "repeat_driven_hash": repeated["driven_hash"],
        }, indent=2))


if __name__ == "__main__":
    main()
