"""Ports of the shipped game's seed hash and deterministic randomness.

Acceptance scripts have to predict what the shipped game derives from a run seed
without asking the game. These are direct ports of three decompiled pieces, named
at each function, so a game update that changes any of them is a change here too:

* ``StringHelper.GetDeterministicHashCode`` — the seed hash ``RunRngSet`` and every
  named run stream is built from.
* ``MegaRandom`` — splitmix64 seeding over xoshiro256**.
* the draw surface of ``Rng`` that content uses: ``NextInt``/``NextItem``,
  ``NextBool`` and ``UnstableShuffle``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

_UINT32 = 0xFFFFFFFF
_UINT64 = 0xFFFFFFFFFFFFFFFF
_INT32_SEED = 352654597
_INT32_MULTIPLIER = 1566083941
_INCR_DOUBLE = 1.1102230246251565e-16

T = TypeVar("T")


def _code_units(text: str) -> list[int]:
    """The UTF-16 code units `StringHelper.GetDeterministicHashCode` iterates."""
    raw = text.encode("utf-16-le")
    return [raw[index] | (raw[index + 1] << 8) for index in range(0, len(raw), 2)]


def deterministic_hash_code(text: str) -> int:
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


class MegaRandom:
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

    def next_ulong(self) -> int:
        """Port of `MegaRandom.NextULongInner`, the one xoshiro256** step."""
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

    def next_double(self) -> float:
        """Port of `MegaRandom.NextDouble`: the top 53 bits scaled by its 2^-53 step."""
        return (self.next_ulong() >> 11) * _INCR_DOUBLE

    def next_below(self, exclusive: int) -> int:
        """`MegaRandom.Next(exclusive)`, i.e. one uniform draw below `exclusive`."""
        return int(self.next_double() * exclusive)


class Rng:
    """Port of the shipped `Rng` draw surface, over one ``MegaRandom``.

    ``stream`` reproduces the ``Rng(uint seed, string name)`` constructor, which is
    how the game keys a generator to a piece of content: the name's deterministic
    hash is added to the seed before the generator is built.
    """

    def __init__(self, seed: int = 0, *, stream: str | None = None) -> None:
        if stream is not None:
            seed = (seed + deterministic_hash_code(stream)) & _UINT32
        self._random = MegaRandom(seed & _UINT32)

    def next_int(self, maximum: int, minimum: int = 0) -> int:
        """`Rng.NextInt(minimum, maximum)`, with `minimum` defaulting to zero."""
        return self._random.next_below(maximum - minimum) + minimum

    def next_bool(self) -> bool:
        """`Rng.NextBool`: `Next(2) == 0`, not the sign bit."""
        return self.next_int(2) == 0

    def next_item(self, items: Sequence[T]) -> T:
        """`Rng.NextItem`: one draw over the item count."""
        return items[self.next_int(len(items))]

    def unstable_shuffle(self, items: list[T]) -> list[T]:
        """Port of `ListExtensions.UnstableShuffle`, in place, returning the list."""
        for index in range(len(items) - 1, 0, -1):
            other = self.next_int(index + 1)
            items[index], items[other] = items[other], items[index]
        return items


def rng_for_content(seed: str, content_id: str, player_slot: int = 0, mixin: int = 0) -> Rng:
    """Port of ``Rng(Player, ModelId, mixin)`` for a fully specified run seed."""
    return Rng((deterministic_hash_code(seed) + player_slot + deterministic_hash_code(content_id)) + mixin)
