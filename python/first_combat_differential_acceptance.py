#!/usr/bin/env python3
"""E5 golden differential: compare Neow -> first-combat roots and full first combats.

`docs/first-combat-scene-generation-plan.md` E5 asks for a frozen manifest authority gate against
`full_application_native`. This script is its runner:

* **targeted** — the plan's thirteen fixtures: the seven high-risk blessings, an A10 case, and one
  run start for each remaining character. Each fixture enumerates its fast-path roots and compares a
  bounded, evenly spaced sample of them on the shipped application, following the recorded branch to
  the root and then out to the unified first-combat endpoint.
* **breadth** — a frozen manifest of 100 distinct seeds, one (character, ascension) cell per seed so
  the ten cells are covered evenly. Every entry drives the shared deterministic decision policy to
  the first-combat root and compares there, with `combat.turn == 1 && combat.phase == Play` proven on
  both environments; the first ten entries (one per cell) continue to the unified endpoint, which is
  the plan's "one step-by-step replay per character/ascension cell" requirement.

Both modes settle where they say they settle: the entry's `stop` field is `root` or `endpoint`, and
`decision_kinds` lists the action kinds actually taken. The combat is executed by the same deterministic
semantic policy on both sides (the smallest legal semantic key, wrappers excluded), which in combat
selects `end_turn` whenever it is legal — the report states that rather than implying card-play coverage.

Every entry uses its own isolated shipped-application process. A fresh sandbox worker is part of the
measurement, not an implementation detail, but the reason is this bridge's lifecycle rather than a game
limit: the bridge starts the shipped autoplay driver once and that driver exits the process when its run
ends, while the game itself can tear a run down and start another in the same process (see
docs/e5-differential-run-cost-and-process-reuse-report.md).
Reports (including every mismatch with its raw seed, branch and action) land under `artifacts/`,
which is git-ignored. Nothing is written into the game installation.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sts2_native_sim.client import NativeWorker
from sts2_native_sim.first_combat import EnumerationLimits, enumerate_first_combat_roots, run_start_request
from sts2_native_sim.first_combat_differential import (
    DIFFERENTIAL_SCHEMA_VERSION,
    ROOT_SCHEMA,
    EntryResult,
    aggregate,
    run_entry,
)
from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig
from sts2_native_sim.paths import find_game_root

# The plan's E5 targeted manifest: five characters, A0/A10, and the seven high-risk Neow outcomes the
# E3/E4 fixtures pin. The blessing each seed offers is asserted by the E4 acceptance; here it is
# recorded so a report shows which outcome was compared.
TARGETED_FIXTURES = (
    ("NEOWSWEEP0000", "IRONCLAD", 0, "LARGE_CAPSULE"),
    ("NEOWSWEEP0001", "IRONCLAD", 0, "PHIAL_HOLSTER"),
    ("NEOWSWEEP0019", "IRONCLAD", 0, "SMALL_CAPSULE"),
    ("NEOWSWEEP0015", "IRONCLAD", 0, "NEW_LEAF"),
    ("NEOWSWEEP0006", "IRONCLAD", 0, "LEAFY_POULTICE"),
    ("NEOWSWEEP0007", "IRONCLAD", 0, "SCROLL_BOXES"),
    ("NEOWSWEEP0013", "IRONCLAD", 0, "NEOWS_BONES"),
    ("NEOWSWEEP0007", "IRONCLAD", 10, "SCROLL_BOXES_A10"),
    ("NEOWSWEEP0006", "DEFECT", 0, "WINGED_BOOTS_DEFECT"),
    ("NEOWSWEEP0003", "SILENT", 0, "SILENT_A0"),
    ("NEOWSWEEP0004", "REGENT", 0, "REGENT_A0"),
    ("NEOWSWEEP0005", "NECROBINDER", 0, "NECROBINDER_A0"),
    ("NEOWSWEEP0001", "DEFECT", 10, "DEFECT_A10"),
)

CHARACTERS = ("IRONCLAD", "SILENT", "DEFECT", "NECROBINDER", "REGENT")

# Frozen breadth manifest: 100 distinct seeds. Each seed pins one (character, ascension) cell, so the
# ten cells are covered evenly (ten seeds each) without taking the full 10x100 cartesian product: this
# bridge serves one run start per process, so every entry is its own measurement (the lifecycle reason
# is recorded in docs/e5-differential-run-cost-and-process-reuse-report.md).
BREADTH_SEEDS = tuple(f"E5BREADTH{index:03d}" for index in range(100))

# Cell order is character-major then ascension, so the first ten seeds cover all ten cells once each.
# The plan's verification gradient asks for a full step-by-step first-combat replay per cell, so those
# ten entries run with trajectories and the remaining ninety compare roots only.
BREADTH_CELLS = tuple(
    (character, ascension)
    for ascension in (0, 10)
    for character in CHARACTERS
)


def breadth_manifest() -> tuple[tuple[str, str, int, str], ...]:
    entries = []
    for index, seed in enumerate(BREADTH_SEEDS):
        character, ascension = BREADTH_CELLS[index % len(BREADTH_CELLS)]
        entries.append((seed, character, ascension, "breadth"))
    return tuple(entries)


def worker_factory(index: int):
    def create() -> FullAppBridgeClient:
        client = FullAppBridgeClient(FullAppClientConfig(worker_id=100 + index))
        client.launch()
        return client

    return create


def compare_root_sample(
    seed: str,
    character: str,
    ascension: int,
    limit: int,
    labels: dict[str, str],
    fixture_index: int,
    workers: int,
    stop: str,
) -> list[EntryResult]:
    """Enumerate one fixture's roots and compare an evenly spaced sample on the shipped application."""
    results: list[EntryResult] = []
    with NativeWorker() as fast:
        limits = EnumerationLimits(max_actions_per_branch=16, max_roots=512, max_expansions=1024)
        enumeration = enumerate_first_combat_roots(fast, seed, character, ascension, limits)
        labels_key = f"{seed}|{character}|A{ascension}"
        roots = list(enumeration.roots)
        if not roots:
            return [
                EntryResult(
                    seed=seed,
                    character=character,
                    ascension=ascension,
                    label=labels_key,
                    status="error",
                    stage="enumeration",
                    error="the reconstructed environment enumerated no root",
                )
            ]
        # Evenly spaced sample so a fixture with many converged branches still covers the trace space.
        step = max(1, len(roots) // limit)
        sample = roots[::step][:limit]
        run_start = run_start_request(seed, character, ascension, fast.build)
        neow_options = [str(option.get("text_key")) for option in enumeration.neow_decision.get("options") or []]
        for index, root in enumerate(sample):
            result = run_entry(
                fast,
                worker_factory(fixture_index * 8 + index if index < 8 else fixture_index + index),
                seed=seed,
                character=character,
                ascension=ascension,
                label=labels.get(labels_key, labels_key),
                trace=root.trace,
                run_start=run_start,
                stop=stop,
            )
            result.neow_options = neow_options
            results.append(result)
            print(
                f"  [targeted] {labels_key} root {index + 1}/{len(sample)} ({len(roots)} enumerated) [{stop}] "
                f"-> {result.status} boundaries={result.boundaries} {result.stage or ''}",
                flush=True,
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("targeted", "breadth", "both"), default="targeted")
    parser.add_argument("--roots-per-fixture", type=int, default=3, help="how many sampled roots each targeted fixture compares")
    parser.add_argument("--breadth-limit", type=int, default=100, help="how many frozen breadth entries to compare")
    parser.add_argument("--workers", type=int, default=4, help="concurrent shipped-application processes")
    parser.add_argument("--trajectory", action="store_true", help="play the first combat out for every entry (stop=endpoint) instead of settling at the first-combat root (stop=root)")
    parser.add_argument(
        "--only-label",
        action="append",
        default=[],
        help="compare only the targeted fixture(s) with this label; repeat for several (cheap re-verification)",
    )
    parser.add_argument("--out", type=Path, default=Path("artifacts/e5-differential/differential-report.json"))
    args = parser.parse_args(argv)

    report: dict[str, Any] = {
        "schema_version": DIFFERENTIAL_SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "game_root": str(find_game_root()),
        "mode": args.mode,
        "roots_per_fixture": args.roots_per_fixture,
        "breadth_limit": args.breadth_limit,
        "workers": args.workers,
        "trajectory": args.trajectory,
        "root_schema": ROOT_SCHEMA,
        "breadth_seeds": list(BREADTH_SEEDS),
        "breadth_cells": [{"character": character, "ascension": ascension} for character, ascension in BREADTH_CELLS],
        "targeted_manifest": [
            {"seed": seed, "character": character, "ascension": ascension, "outcome": outcome}
            for seed, character, ascension, outcome in TARGETED_FIXTURES
        ],
        "only_label": list(args.only_label),
        "build": {},
        "results": [],
    }

    results: list[EntryResult] = []
    started = time.perf_counter()
    try:
        if args.mode in ("targeted", "both"):
            labels = {f"{s}|{c}|A{a}": f"{outcome}" for s, c, a, outcome in TARGETED_FIXTURES}
            fixtures = [fixture for fixture in TARGETED_FIXTURES if not args.only_label or fixture[3] in args.only_label]
            if args.only_label and not fixtures:
                parser.error(f"--only-label matched no targeted fixture: {', '.join(args.only_label)}")
            targeted_stop = "endpoint" if args.trajectory else "root"
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
                futures = [
                    (
                        (seed, character, ascension, outcome),
                        executor.submit(compare_root_sample, seed, character, ascension, args.roots_per_fixture, labels, index, args.workers, targeted_stop),
                    )
                    for index, (seed, character, ascension, outcome) in enumerate(fixtures)
                ]
                for (seed, character, ascension, outcome), future in futures:
                    try:
                        results.extend(future.result())
                    except Exception as error:  # noqa: BLE001 - one broken fixture must not hide the rest
                        results.append(
                            EntryResult(
                                seed=seed,
                                character=character,
                                ascension=ascension,
                                label=outcome,
                                status="error",
                                stage="fixture",
                                error=f"{type(error).__name__}: {error}",
                            )
                        )

        if args.mode in ("breadth", "both"):
            manifest = breadth_manifest()[: args.breadth_limit]

            def compare_breadth(item: tuple[str, str, int, str], index: int) -> EntryResult:
                seed, character, ascension, label = item
                # The first len(BREADTH_CELLS) entries cover every character/ascension cell once, and
                # the plan requires one full step-by-step first combat per cell. Every other entry
                # still drives to the first-combat root and proves the boundary there.
                cell_endpoint = index < len(BREADTH_CELLS)
                stop = "endpoint" if (args.trajectory or cell_endpoint) else "root"
                try:
                    with NativeWorker() as fast:
                        return run_entry(
                            fast,
                            worker_factory(index % max(1, args.workers)),
                            seed=seed,
                            character=character,
                            ascension=ascension,
                            label=f"{label}:cell" if cell_endpoint else label,
                            stop=stop,
                        )
                except Exception as error:  # noqa: BLE001 - one failed entry must not hide the rest
                    return EntryResult(
                        seed=seed,
                        character=character,
                        ascension=ascension,
                        label=label,
                        status="error",
                        stage="worker",
                        stop=stop,
                        error=f"{type(error).__name__}: {error}",
                    )

            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
                futures = {
                    executor.submit(compare_breadth, item, index): item for index, item in enumerate(manifest)
                }
                for future in concurrent.futures.as_completed(futures):
                    item = futures[future]
                    result = future.result()
                    results.append(result)
                    print(
                        f"  [breadth] {result.seed}|{result.character}|A{result.ascension} [{result.stop}] -> "
                        f"{result.status} boundaries={result.boundaries} combat_steps={result.combat_steps} "
                        f"{result.stage or ''}",
                        flush=True,
                    )

        if results:
            report["build"] = dict(results[0].build)
    finally:
        report["wall_seconds"] = time.perf_counter() - started
        report["results"] = [result.as_record() for result in results]
        report["aggregate"] = aggregate(results)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nreport: {args.out}", flush=True)
        print(json.dumps(report["aggregate"], indent=2), flush=True)

    failures = [result for result in results if result.status != "match"]
    return 0 if results and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
