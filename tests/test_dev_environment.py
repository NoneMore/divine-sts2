from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from sts2_native_sim import paths


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
