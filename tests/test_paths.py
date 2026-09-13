from __future__ import annotations

import itertools
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from sts2_native_sim.paths import (
    REPOSITORY_ROOT,
    DiscoveryError,
    find_game_root,
    load_env_file,
    parse_env_file,
)

_SCRATCH_ROOT = REPOSITORY_ROOT / ".tmp-tests"
_scratch_counter = itertools.count()


@pytest.fixture
def scratch_dir() -> Iterator[Path]:
    """Repository-local scratch directory.

    The `tmp_path` fixture is deliberately avoided: `tempfile.mkdtemp` creates a
    directory with an owner-only DACL that a restricted sandbox token cannot
    reopen, which surfaces as a fixture permission error instead of a test result.
    """
    directory = _SCRATCH_ROOT / f"paths-{os.getpid()}-{next(_scratch_counter)}"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_parse_env_file_ignores_comments_and_normalizes_values() -> None:
    parsed = parse_env_file(
        "\n".join(
            [
                "# comment",
                "",
                "STS2_GAME_ROOT=D:\\Games\\Slay the Spire 2",
                'GODOT="C:\\tools\\godot.exe"',
                "export DOTNET='C:\\tools\\dotnet.exe'",
                "MALFORMED",
                "  SPACED  =  value  ",
            ]
        )
    )

    assert parsed == {
        "STS2_GAME_ROOT": "D:\\Games\\Slay the Spire 2",
        "GODOT": "C:\\tools\\godot.exe",
        "DOTNET": "C:\\tools\\dotnet.exe",
        "SPACED": "value",
    }


def test_load_env_file_does_not_override_process_environment(
    scratch_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = scratch_dir / ".env"
    env_file.write_text("STS2_GAME_ROOT=D:\\from-file\nGODOT=D:\\from-file\n", encoding="utf-8")
    monkeypatch.setenv("STS2_GAME_ROOT", "E:\\from-process")
    monkeypatch.delenv("GODOT", raising=False)

    applied = load_env_file(env_file)

    assert applied == ["GODOT"]
    assert os.environ["STS2_GAME_ROOT"] == "E:\\from-process"
    assert os.environ["GODOT"] == "D:\\from-file"


def test_load_env_file_overrides_only_the_documented_windows_keys(
    scratch_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`APPDATA`/`LOCALAPPDATA` are always defined, so a sandboxed session can only redirect
    engine user data into the checkout through this documented exception."""
    env_file = scratch_dir / ".env"
    env_file.write_text(
        "APPDATA=D:\\redirected\\roaming\nLOCALAPPDATA=D:\\redirected\\local\nSTS2_GAME_ROOT=D:\\from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APPDATA", "D:\\profile\\AppData\\Roaming")
    monkeypatch.setenv("LOCALAPPDATA", "D:\\profile\\AppData\\Local")
    monkeypatch.setenv("STS2_GAME_ROOT", "E:\\from-process")

    applied = load_env_file(env_file)

    assert applied == ["APPDATA", "LOCALAPPDATA"]
    assert os.environ["APPDATA"] == "D:\\redirected\\roaming"
    assert os.environ["LOCALAPPDATA"] == "D:\\redirected\\local"
    assert os.environ["STS2_GAME_ROOT"] == "E:\\from-process"


def test_load_env_file_missing_file_is_noop(scratch_dir: Path) -> None:
    assert load_env_file(scratch_dir / "absent.env") == []


def test_find_game_root_accepts_complete_install(scratch_dir: Path) -> None:
    install = scratch_dir / "Slay the Spire 2"
    (install / "data_sts2_windows_x86_64").mkdir(parents=True)
    (install / "SlayTheSpire2.exe").write_bytes(b"")
    (install / "SlayTheSpire2.pck").write_bytes(b"")
    (install / "data_sts2_windows_x86_64" / "sts2.dll").write_bytes(b"")

    assert find_game_root(install) == install.resolve()


def test_find_game_root_rejects_incomplete_install(scratch_dir: Path) -> None:
    install = scratch_dir / "Slay the Spire 2"
    install.mkdir(parents=True)
    (install / "SlayTheSpire2.exe").write_bytes(b"")

    with pytest.raises(DiscoveryError):
        find_game_root(install)
