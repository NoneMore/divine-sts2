"""Command-line entry point for setup validation and native workers."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from .client import NativeWorker
from .paths import (
    DiscoveryError,
    REPOSITORY_ROOT,
    expected_dotnet_version,
    find_dotnet,
    find_game_assembly,
    find_game_root,
    find_godot,
    find_host_assembly,
)
from .scenarios import ScenarioRequest, ScenarioRequestError, generate_corpus

SUPPORTED_BUILD = {
    "assembly_sha256": "A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52",
    "pck_sha256": "42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def doctor(deep: bool = False) -> dict[str, Any]:
    expected_dotnet = expected_dotnet_version()
    dotnet: str | None = None
    dotnet_sdks: list[str] = []
    try:
        dotnet = str(find_dotnet())
    except DiscoveryError:
        pass
    if dotnet:
        try:
            result = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True, timeout=10, check=False)
            if result.returncode == 0:
                dotnet_sdks = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.TimeoutExpired):
            pass
    checks: dict[str, Any] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "repository_root": str(REPOSITORY_ROOT),
        "dotnet": dotnet,
        "dotnet_sdk_expected": expected_dotnet,
        "dotnet_sdks": dotnet_sdks,
    }
    try:
        import torch

        checks["torch"] = torch.__version__
        checks["cuda_available"] = torch.cuda.is_available()
        checks["cuda_device"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        checks["torch"] = None
        checks["cuda_available"] = False
        checks["cuda_device"] = None
    failures: list[str] = []
    for name, discover in (("game_root", find_game_root), ("game_assembly", find_game_assembly), ("host_assembly", find_host_assembly)):
        try:
            checks[name] = str(discover())
        except DiscoveryError as error:
            checks[name] = None
            failures.append(str(error))

    try:
        checks["godot"] = str(find_godot())
    except DiscoveryError:
        checks["godot"] = None

    if deep and not failures:
        assembly = Path(checks["game_assembly"])
        game_root = Path(checks["game_root"])
        checks["sts2_assembly_sha256"] = _sha256(assembly)
        checks["sts2_pck_sha256"] = _sha256(game_root / "SlayTheSpire2.pck")
        for key, expected in SUPPORTED_BUILD.items():
            actual = checks["sts2_" + key]
            if actual != expected:
                failures.append(f"Unsupported game build: {key}={actual}; expected {expected}.")
        try:
            with NativeWorker() as worker:
                checks["worker_hello"] = worker.hello()
                checks["worker_catalog_counts"] = {
                    key: len(value) for key, value in worker.catalog().items() if isinstance(value, list)
                }
        except Exception as error:  # The report should retain every earlier check.
            details = getattr(error, "details", None)
            suffix = f" details={details}" if details else ""
            failures.append(f"Native worker smoke failed: {error}{suffix}")

    has_expected_dotnet = any(version.startswith(f"{expected_dotnet} ") for version in dotnet_sdks)
    checks["ok"] = not failures and has_expected_dotnet
    checks["failures"] = failures + (
        [] if has_expected_dotnet else [f".NET SDK {expected_dotnet} was not found; run `pwsh ./dev.ps1 setup`."]
    )
    checks["ok"] = not checks["failures"]
    return checks


def _report_counts(summary: dict[str, Any], root: str) -> None:
    """Say how many rows each type the batch produced, so a corpus that lost elements is visible.

    A failure row is a row, so the corpus is still written and the exit status still reports that
    the command did what it was asked; the counts are what a caller checks to learn whether the
    corpus is complete, rather than parsing the rows back.
    """
    def count(number: int, noun: str) -> str:
        return f"{number} {noun} row" if number == 1 else f"{number} {noun} rows"

    shards = "1 shard" if summary["workers"] == 1 else f"{summary['workers']} shards"
    print(
        f"divine-sts2 scenario: {shards} under {root}: "
        f"{count(summary['succeeded'], 'scenario')}, {count(summary['failed'], 'failure')}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="divine-sts2")
    subcommands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subcommands.add_parser("doctor", help="validate the local game/tool installation")
    doctor_parser.add_argument("--deep", action="store_true", help="hash game files and start a native worker")
    doctor_parser.add_argument("--json", action="store_true", help="emit compact JSON")
    scenario_parser = subcommands.add_parser(
        "scenario", help="record the act-1 opening scenarios a character, Ascension and seed set produce"
    )
    scenario_parser.add_argument(
        "--character", action="append", required=True, metavar="CHARACTER",
        help="a character to start runs as, e.g. IRONCLAD; repeat for more than one",
    )
    scenario_parser.add_argument(
        "--ascension", action="append", type=int, metavar="N",
        help="an Ascension to start runs at; repeat for more than one (default 0)",
    )
    scenario_parser.add_argument(
        "--seed", action="append", required=True, metavar="SEED",
        help="a run seed, in any form the shipped game accepts; repeat for more than one",
    )
    scenario_parser.add_argument(
        "--workers", type=int, default=1, metavar="N",
        help="native workers to spread the batch over; each writes one shard (default 1)",
    )
    scenario_parser.add_argument(
        "--output-dir", required=True, metavar="DIR",
        help="artifact root for the corpus; a root already holding this request is resumed",
    )
    scenario_parser.add_argument(
        "--compression", type=int, default=3, choices=range(10),
        help="gzip compression level of the shards (default 3)",
    )
    args = parser.parse_args(argv)

    if args.command == "doctor":
        report = doctor(args.deep)
        print(json.dumps(report, indent=None if args.json else 2, default=str))
        raise SystemExit(0 if report["ok"] else 1)

    if args.command == "scenario":
        request = ScenarioRequest(
            characters=tuple(args.character),
            ascensions=tuple(args.ascension or (0,)),
            seeds=tuple(args.seed),
        )
        try:
            # No worker factory is passed, so the batch builds its own workers — one per shard, and
            # only for a shard it still has to write. The request and the artifact root are checked,
            # and a corpus already there is read, before the first of them is built, so a request
            # this batch cannot run says so on a host with no game installed.
            summary = generate_corpus(
                request,
                args.workers,
                args.output_dir,
                compression=args.compression,
            )
        except ScenarioRequestError as error:
            # An input error is not a run failure: say what is wrong and write nothing, rather
            # than half a corpus.
            print(f"divine-sts2 scenario: {error}", file=sys.stderr)
            raise SystemExit(2) from error
        _report_counts(summary, args.output_dir)
        raise SystemExit(0)


if __name__ == "__main__":
    main()
