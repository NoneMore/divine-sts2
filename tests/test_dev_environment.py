from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from sts2_native_sim import paths


def test_a_writable_directory_is_accepted_and_left_clean(tmp_path: Path) -> None:
    target = tmp_path / "writable"

    assert paths.is_directory_writable(target) is True
    assert list(target.iterdir()) == []


def test_a_refused_directory_is_reported_as_not_writable(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")

    assert paths.is_directory_writable(blocker / "child") is False


def test_a_writable_user_directory_is_not_redirected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    assert paths.native_worker_user_directory_overrides(root=tmp_path / "redirect") == {}


def test_a_refused_user_directory_is_redirected_into_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "profile-file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(blocker / "Roaming"))
    root = tmp_path / "redirect"

    overrides = paths.native_worker_user_directory_overrides(root=root)

    assert set(overrides) == {"APPDATA", "LOCALAPPDATA", "TEMP", "TMP"}
    assert Path(overrides["APPDATA"]) == root / "appdata"
    assert Path(overrides["LOCALAPPDATA"]) == root / "localappdata"
    assert Path(overrides["TEMP"]) == Path(overrides["TMP"]) == root / "temp"
    for value in set(overrides.values()):
        assert Path(value).is_dir()


def test_no_user_directory_is_redirected_without_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("APPDATA", raising=False)

    assert paths.native_worker_user_directory_overrides(root=tmp_path / "redirect") == {}


def test_game_root_failure_names_the_variable_and_the_searched_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STS2_GAME_ROOT", raising=False)
    monkeypatch.delenv("STEAM_PATH", raising=False)
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "no-steam"))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "no-steam"))

    with pytest.raises(paths.DiscoveryError) as failure:
        paths.find_game_root()

    message = str(failure.value)
    assert "STS2_GAME_ROOT" in message
    assert "STEAM_PATH" in message


def test_dot_env_fills_only_variables_that_are_not_already_set(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("pwsh is not available")
    env_file = tmp_path / ".env"
    env_file.write_text("STS2_TEST_PROBE=from-file\nSTS2_TEST_KEPT=from-file\n", encoding="utf-8")
    common = paths.REPOSITORY_ROOT / "scripts" / "common.ps1"
    command = (
        f". '{common}'\n"
        f"Import-DivineDotEnv -Path '{env_file}'\n"
        '"probe=$env:STS2_TEST_PROBE"\n'
        '"kept=$env:STS2_TEST_KEPT"\n'
    )
    environment = dict(os.environ, STS2_TEST_KEPT="from-environment")

    completed = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command], capture_output=True, text=True, env=environment, check=True
    )

    assert "probe=from-file" in completed.stdout
    assert "kept=from-environment" in completed.stdout
