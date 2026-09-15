"""Shipped-game acceptance for the act-1 Act variant a run seed rolls.

A simulator run must play the Act variant the shipped game rolls for the same
run seed, and must report it. This script drives real native workers, reads the
variant off the run observation, and checks it against an independent port of the
shipped roll — the seed hash, the ``act_selection`` generator and the act pool in
the order the shipped database lists it — so a hard-coded or drifting roll cannot
pass.

It also re-checks the recorded pre-change map and RNG counters for the same
seeds. Those are properties of the run seed alone, so they must not move now that
the act roll picks a different variant for some of them; a shift means the roll
started consuming a stream the map, the encounter pools or a combat reads.

Requires the shipped game and a Godot-hosted worker (the repository's
``*_acceptance.py`` convention). Run with ``--snapshot`` on an unmodified build to
re-record the baseline this script compares against.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sts2_native_sim import NativeWorkerPool

_UINT32 = 0xFFFFFFFF
_UINT64 = 0xFFFFFFFFFFFFFFFF
_INT32_SEED = 352654597
_INT32_MULTIPLIER = 1566083941
_ACT_SELECTION_STREAM = "act_selection"
# ModelDb.ActsByIndex[0]: the act-1 variants in the order the shipped database
# lists them, default first.
_DEFAULT_VARIANT = "OVERGROWTH"
_ACT_POOL = (_DEFAULT_VARIANT, "UNDERDOCKS")

# Seeds chosen so that both act-1 variants occur, half of them each. The oracle
# below says which is which without the game; the shipped-game run must agree
# seed by seed.
_SEEDS = (
    "ACTVARIANT01",
    "ACTVARIANT02",
    "ACTVARIANT03",
    "ACTVARIANT04",
    "ACTVARIANT05",
    "ACTVARIANT07",
    "ACTVARIANT12",
    "ACTVARIANT13",
)

# The game build the baseline below was recorded on. A different build may change
# the map or the draw counts for innocent reasons, so the comparison fails closed
# on a mismatch instead of reporting a moved stream. Re-record with `--snapshot`.
_BASELINE_BUILD = "A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52"

# Recorded on the build above, before the act roll was derived from the seed, when
# every run played the default variant. A seed that still plays the default variant
# must reproduce its baseline bit for bit; a seed that now plays the other variant
# must keep its map and every counter except the encounter-pool draw. That pool is
# built from the act's own encounter and event lists, which differ in size between
# variants, so its draw count legitimately follows the act in play — exactly as the
# shipped game's does.
_BASELINE_COUNTERS = {
    "CombatCardGeneration": 0, "CombatCardSelection": 0, "CombatEnergyCosts": 0, "CombatOrbs": 0,
    "CombatPotionGeneration": 0, "CombatTargets": 0, "MonsterAi": 0, "Niche": 1, "Shuffle": 9,
    "TreasureRoomRelics": 0, "UnknownMapPoint": 0,
}
_BASELINE = {
    "ACTVARIANT01": {"map_digest": "58e50b2ae4be1c7dc18cec638fae207998a4a650eb79548a856b9cfbda52cda8", "up_front": 408},
    "ACTVARIANT02": {"map_digest": "8d29f0794edddb1bad576c9aea0ed306d2e40eff9d6869bc5b3e57dbc4d9d7a0", "up_front": 414},
    "ACTVARIANT03": {"map_digest": "f6c917b8ddf9bb61bb9c6c6e7bc5acca7841f85cd6a31a666f814ed917a593ba", "up_front": 409},
    "ACTVARIANT04": {"map_digest": "0df7326dda1fa308fcb49d4ec95782d2423dbee0b9d8077d11ccb6dd54631a3b", "up_front": 412},
    "ACTVARIANT05": {"map_digest": "b50bd9965b0411e2c4e71946eda7bc5b92d6ac1b6b5924aaed93c6bfa88faa68", "up_front": 419},
    "ACTVARIANT07": {"map_digest": "6c4a22dfe33d87e2019faac4465badc973a54d22102526357d98a4f2c21a85b7", "up_front": 410},
    "ACTVARIANT12": {"map_digest": "cd4531d7f01983c54bf1ef383bfbad5c67164c0e5bfa996f67bf8c2569017eec", "up_front": 415},
    "ACTVARIANT13": {"map_digest": "9c784443b82465cddc54da3e91023d0f7582ee264cc145ff2db402685d5d51fa", "up_front": 416},
}


def _code_units(text: str) -> list[int]:
    """The UTF-16 code units `StringHelper.GetDeterministicHashCode` iterates."""
    raw = text.encode("utf-16-le")
    return [raw[index] | (raw[index + 1] << 8) for index in range(0, len(raw), 2)]


def _deterministic_hash_code(text: str) -> int:
    """Port of `StringHelper.GetDeterministicHashCode`, in 32-bit wrapping arithmetic."""
    units = _code_units(text)
    num = _INT32_SEED
    num2 = num
    for index in range(0, len(units), 2):
        num = (((num << 5) + num) ^ units[index]) & _UINT32
        if index == len(units) - 1:
            break
        num2 = (((num2 << 5) + num2) ^ units[index + 1]) & _UINT32
    return (num + num2 * _INT32_MULTIPLIER) & _UINT32


def _rotate_left(value: int, count: int) -> int:
    return ((value << count) | (value >> (64 - count))) & _UINT64


class _MegaRandom:
    """Port of the shipped `MegaRandom`: splitmix64 seeding over xoshiro256**."""

    def __init__(self, seed: int) -> None:
        self._state = [0, 0, 0, 0]
        state = seed & _UINT64
        for index in range(4):
            state = (state + 11400714819323198485) & _UINT64
            value = state
            value = ((value ^ (value >> 30)) * 13787848793156543929) & _UINT64
            value = ((value ^ (value >> 27)) * 10723151780598845931) & _UINT64
            self._state[index] = value ^ (value >> 31)

    def _next_ulong(self) -> int:
        s0, s1, s2, s3 = self._state
        result = (_rotate_left((s1 * 5) & _UINT64, 7) * 9) & _UINT64
        shifted = (s1 << 17) & _UINT64
        s2 ^= s0
        s3 ^= s1
        s1 ^= s2
        s0 ^= s3
        s2 ^= shifted
        s3 = _rotate_left(s3, 45)
        self._state = [s0, s1, s2, s3]
        return result

    def next_below(self, exclusive: int) -> int:
        """`Rng.NextInt(0, exclusive)`, i.e. one uniform integer draw."""
        # MegaRandom's own double step: the top 53 bits scaled by its 2^-53 step.
        return int((self._next_ulong() >> 11) * 1.1102230246251565e-16 * exclusive)


def rolled_act_variant(seed: str) -> str:
    """The variant the shipped roll picks: `new Rng(hash(seed), "act_selection")`."""
    selection = (_deterministic_hash_code(seed) + _deterministic_hash_code(_ACT_SELECTION_STREAM)) & _UINT32
    return _ACT_POOL[_MegaRandom(selection).next_below(len(_ACT_POOL))]


def _run_state(seed: str, ascension: int = 0) -> dict:
    return {
        "game_build": {},
        "seed": seed,
        "rng_counters": {},
        "character": "IRONCLAD",
        "ascension": ascension,
        "encounter": "first",
        "current_hp": 80,
        "max_hp": 80,
        "deck": [],
        "gold": 99,
        "use_character_starting_loadout": True,
    }


def _map_digest(observation: dict) -> str:
    """A stable digest of the map the run generated, visited state excluded."""
    map_state = observation["map"]
    shape = {
        "points": [
            {"coord": point["coord"], "point_type": point["point_type"], "children": point["children"]}
            for point in map_state["points"]
        ],
        "current": map_state.get("current"),
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _variant_of(state: dict) -> str | None:
    return state["observation"]["run"].get("act_variant")


def _snapshot(state: dict) -> dict:
    return {"rng_counters": state["observation"]["run"]["rng_counters"], "map_digest": _map_digest(state["observation"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", action="store_true", help="print the map and RNG baseline for the sample seeds")
    parser.add_argument("--workers", type=int, default=2, help="native workers to spread the sample over")
    arguments = parser.parse_args()

    with NativeWorkerPool(arguments.workers) as pool:
        # One reset at a time per worker: a worker is a whole native game process.
        states = [pool.workers[index % arguments.workers].run_reset(_run_state(seed)) for index, seed in enumerate(_SEEDS)]

        if arguments.snapshot:
            print(json.dumps({seed: _snapshot(state) for seed, state in zip(_SEEDS, states)}, indent=2, sort_keys=True))
            return

        game_build = pool.workers[0].build
        assert game_build["assembly_sha256"] == _BASELINE_BUILD, (
            f"the recorded baseline is for game assembly {_BASELINE_BUILD}, this machine runs "
            f"{game_build['assembly_sha256']}; re-record it with --snapshot"
        )

        observed = dict(zip(_SEEDS, (_variant_of(state) for state in states)))
        expected = {seed: rolled_act_variant(seed) for seed in _SEEDS}
        for seed in _SEEDS:
            assert observed[seed] == expected[seed], f"{seed}: observed {observed[seed]}, shipped roll says {expected[seed]}"
        assert set(observed.values()) == set(_ACT_POOL), f"the sample must exercise every act-1 variant, saw {observed}"

        # The same seed on another worker must reach the same variant.
        second = pool.workers[1 % arguments.workers]
        repeated = _variant_of(second.run_reset(_run_state(_SEEDS[0])))
        assert repeated == observed[_SEEDS[0]], f"{_SEEDS[0]}: variant changed on a second worker ({observed[_SEEDS[0]]} -> {repeated})"

        # Every run observation that reports run facts must name the variant in
        # play, not just the map the run starts on. Custom rewards exercise the
        # snapshot shared by the act transition, run terminal, treasure and shop.
        worker = pool.workers[0]
        worker.run_reset(_run_state(_SEEDS[0]))
        elsewhere = {
            "reward": _variant_of(worker.reward_reset(_run_state(_SEEDS[0]))),
            "item_reward": _variant_of(worker.item_reward_reset(_run_state(_SEEDS[0]), "potion")),
            "rest": _variant_of(worker.rest_reset(_run_state(_SEEDS[0]))),
            "event": _variant_of(worker.event_reset(_run_state(_SEEDS[0]), "SUNKEN_STATUE")),
            "custom_reward": _variant_of(worker.custom_reward_reset(_run_state(_SEEDS[0]), ["gold"])),
        }
        assert set(elsewhere.values()) == {observed[_SEEDS[0]]}, f"another run observation disagreed: {elsewhere}"

        # The act roll must consume nothing the run's own streams count: the map
        # every seed generates, and every counter except the pool draw, must be
        # what the same seed produced before the roll derived the variant. The
        # seeds that still play the default variant pin the roll itself: the same
        # roll ran for them, so a draw it took would show in their counters too.
        for seed, state in zip(_SEEDS, states):
            baseline = _BASELINE[seed]
            current = _snapshot(state)
            assert current["map_digest"] == baseline["map_digest"], (
                f"{seed}: the run's own map moved ({baseline['map_digest']} -> {current['map_digest']})"
            )
            counters = current["rng_counters"]
            unchanged = {name: value for name, value in counters.items() if name != "UpFront"}
            assert unchanged == _BASELINE_COUNTERS, (
                f"{seed}: the run's own RNG counters moved ({_BASELINE_COUNTERS} -> {unchanged})"
            )
            if observed[seed] == _DEFAULT_VARIANT:
                assert counters == {**_BASELINE_COUNTERS, "UpFront": baseline["up_front"]}, (
                    f"{seed}: the default variant's pool draw moved "
                    f"({baseline['up_front']} -> {counters['UpFront']})"
                )

    print(json.dumps({
        "success": True,
        "game_build": game_build,
        "seeds": len(_SEEDS),
        "variants": observed,
        "observations_checked": sorted(("map", *elsewhere)),
        "baseline_seeds_checked": sorted(_BASELINE),
    }, indent=2))


if __name__ == "__main__":
    main()
