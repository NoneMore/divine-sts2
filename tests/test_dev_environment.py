from __future__ import annotations

import json
import os
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
    monkeypatch.setattr(paths, "_registry_steam_roots", lambda: [])

    with pytest.raises(paths.DiscoveryError) as failure:
        paths.find_game_root()

    message = str(failure.value)
    assert "STS2_GAME_ROOT" in message
    assert "STEAM_PATH" in message


def test_python_dot_env_fills_only_variables_that_are_not_already_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("STS2_TEST_PROBE=from-file\nSTS2_TEST_KEPT=from-file\n", encoding="utf-8")
    monkeypatch.delenv("STS2_TEST_PROBE", raising=False)
    monkeypatch.setenv("STS2_TEST_KEPT", "from-environment")

    paths._load_dot_env(env_file)

    assert os.environ["STS2_TEST_PROBE"] == "from-file"
    assert os.environ["STS2_TEST_KEPT"] == "from-environment"


def test_find_dotnet_prefers_a_compatible_system_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOTNET", raising=False)
    monkeypatch.setattr(paths, "REPOSITORY_ROOT", tmp_path)
    (tmp_path / "global.json").write_text(
        json.dumps({"sdk": {"version": "9.0.318"}}),
        encoding="utf-8",
    )
    system_dotnet = tmp_path / "system" / "dotnet.exe"
    bundled_dotnet = tmp_path / ".tools" / "dotnet9" / "dotnet.exe"
    system_dotnet.parent.mkdir()
    bundled_dotnet.parent.mkdir(parents=True)
    system_dotnet.touch()
    bundled_dotnet.touch()

    monkeypatch.setattr(paths.shutil, "which", lambda name: str(system_dotnet) if name == "dotnet" else None)
    monkeypatch.setattr(paths, "_dotnet_has_expected_sdk", lambda executable: executable == system_dotnet.resolve())

    assert paths.find_dotnet() == system_dotnet.resolve()


def test_find_dotnet_uses_repo_fallback_when_system_sdk_is_incompatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOTNET", raising=False)
    monkeypatch.setattr(paths, "REPOSITORY_ROOT", tmp_path)
    (tmp_path / "global.json").write_text(
        json.dumps({"sdk": {"version": "9.0.318"}}),
        encoding="utf-8",
    )
    system_dotnet = tmp_path / "system" / "dotnet.exe"
    bundled_dotnet = tmp_path / ".tools" / "dotnet9" / "dotnet.exe"
    system_dotnet.parent.mkdir()
    bundled_dotnet.parent.mkdir(parents=True)
    system_dotnet.touch()
    bundled_dotnet.touch()

    monkeypatch.setattr(paths.shutil, "which", lambda name: str(system_dotnet) if name == "dotnet" else None)
    monkeypatch.setattr(paths, "_dotnet_has_expected_sdk", lambda executable: executable == bundled_dotnet)

    assert paths.find_dotnet() == bundled_dotnet.resolve()


def test_find_godot_prefers_a_compatible_system_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GODOT", raising=False)
    system_godot = tmp_path / "godot.exe"
    system_godot.touch()

    monkeypatch.setattr(paths.shutil, "which", lambda name: str(system_godot) if name == "godot" else None)
    monkeypatch.setattr(paths, "_is_supported_godot", lambda executable: executable == system_godot.resolve())

    assert paths.find_godot() == system_godot.resolve()


def test_game_assembly_is_derived_from_game_root_not_a_second_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game_root = tmp_path / "game"
    data_dir = game_root / paths.GAME_DATA_DIRECTORY_NAME
    data_dir.mkdir(parents=True)
    (game_root / "SlayTheSpire2.exe").touch()
    (game_root / "SlayTheSpire2.pck").touch()
    assembly = data_dir / "sts2.dll"
    assembly.touch()
    rogue = tmp_path / "rogue-sts2.dll"
    rogue.touch()

    monkeypatch.setenv("STS2_GAME_ROOT", str(game_root))
    monkeypatch.setenv("STS2_ASSEMBLY", str(rogue))

    assert paths.find_game_assembly() == assembly.resolve()


def test_power_shell_common_delegates_environment_discovery_to_python() -> None:
    common = (paths.REPOSITORY_ROOT / "scripts" / "common.ps1").read_text(encoding="utf-8")

    assert "Import-DivineDotEnv" not in common
    assert "Invoke-DivinePathDiscovery" in common
    assert "find_game_root" in common
    assert "find_godot" in common


def test_native_worker_does_not_assume_repo_local_dotnet_path() -> None:
    client = (paths.REPOSITORY_ROOT / "python" / "sts2_native_sim" / "client.py").read_text(encoding="utf-8")

    assert 'find_dotnet()' in client
    assert '.tools" / "dotnet9"' not in client
