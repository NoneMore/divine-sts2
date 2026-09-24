"""Research-only partial compiler probe for IRONCLAD/A0 first combats.

Ports the shipped seed hash, xoshiro256** RNG, and Act 1 selection.  The
field walk deliberately labels every still-unimplemented observation leaf;
it must never be mistaken for a complete first-combat compiler.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from sts2_native_sim.client import NativeWorker
from sts2_native_sim.scenarios import ScenarioRequest, generate_rows

MASK = (1 << 64) - 1
SEEDS = ("A1B2C3D4E5", "1", "2", "3")


def hash32(value: str) -> int:
    a = b = 352654597
    for index in range(0, len(value), 2):
        a = (((a << 5) + a) ^ ord(value[index])) & 0xFFFFFFFF
        if index + 1 < len(value):
            b = (((b << 5) + b) ^ ord(value[index + 1])) & 0xFFFFFFFF
    return (a + b * 1566083941) & 0xFFFFFFFF


def rotl(value: int, count: int) -> int:
    return ((value << count) | (value >> (64 - count))) & MASK


class Rng:
    def __init__(self, seed: int, name: str):
        seed = (seed + hash32(name)) & 0xFFFFFFFF
        state = []
        for _ in range(4):
            seed = (seed + 0x9E3779B97F4A7C15) & MASK
            x = seed
            x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & MASK
            x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & MASK
            state.append(x ^ (x >> 31))
        self.state = state

    def next_int(self, limit: int) -> int:
        a, b, c, d = self.state
        bits = (rotl((b * 5) & MASK, 7) * 9) & MASK
        shift = (b << 17) & MASK
        c ^= a
        d ^= b
        b ^= c
        a ^= d
        c ^= shift
        d = rotl(d, 45)
        self.state = [a, b, c, d]
        return int(((bits >> 11) * (2 ** -53)) * limit)


def compile_partial(seed: str) -> dict[str, object]:
    # ModelDb.ActsByIndex[0] = [Overgrowth, Underdocks] for fully unlocked runs.
    index = Rng(hash32(seed), "act_selection").next_int(2)
    return {"run.seed": seed, "run.ascension": 0,
            "run.act_variant": ("OVERGROWTH", "UNDERDOCKS")[index],
            "decision.kind": "combat_action", "terminal": False, "victory": False}


def leaves(value: object, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from leaves(child, f"{path}[{index}]")
    else:
        yield path, value


def main() -> None:
    tick = time.perf_counter()
    predictions = {seed: compile_partial(seed) for seed in SEEDS}
    compile_seconds = time.perf_counter() - tick
    worker = NativeWorker()
    result = {"prototype": "partial seed-to-act compiler", "seeds": list(SEEDS),
              "compile_seconds": compile_seconds, "rows": []}
    detailed = []
    try:
        for seed in SEEDS:
            native_rows = generate_rows(ScenarioRequest(("IRONCLAD",), (0,), (seed,)), worker)
            for row in native_rows:
                if row["record_type"] != "scenario":
                    result["rows"].append({"seed": seed, "failure": row.get("error")})
                    continue
                observation = row["combat_initial_state"]
                observed = dict(leaves(observation))
                prediction = predictions[seed]
                compared = {path: {"expected": expected, "actual": observed.get(path),
                                   "match": expected == observed.get(path)}
                            for path, expected in prediction.items()}
                diff = {path: {"status": "match" if path in prediction and prediction[path] == actual
                                        else "mismatch" if path in prediction else "unimplemented",
                               "actual": actual, **({"expected": prediction[path]} if path in prediction else {})}
                        for path, actual in observed.items()}
                detailed.append({"seed": seed, "choice": row["recipe"]["ancient_choice"],
                                 "observation_fields": diff})
                result["rows"].append({
                    "seed": seed, "choice": row["recipe"]["ancient_choice"],
                    "leaf_fields_total": len(observed),
                    "fields_compared": compared,
                    "unimplemented_leaf_fields": len(observed) - len(compared),
                })
    finally:
        worker.close()
    artifact = ROOT / "artifacts" / "scenario-performance" / "fast-first-combat-field-diff.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(detailed, indent=2), encoding="utf-8")
    result["field_diff_artifact"] = str(artifact)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
