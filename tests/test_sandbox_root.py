from __future__ import annotations

from pathlib import Path

import pytest

from sts2_native_sim import paths
from sts2_native_sim.full_app_client import FullAppClientConfig


def test_sandbox_root_can_be_named_explicitly(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit-sandboxes"
    assert paths.find_sandbox_root(explicit) == explicit.resolve()


def test_sandbox_root_can_be_named_by_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "env-sandboxes"
    monkeypatch.setenv("STS2_SANDBOX_ROOT", str(target))
    assert paths.find_sandbox_root() == target.resolve()


def test_explicit_sandbox_root_wins_over_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STS2_SANDBOX_ROOT", str(tmp_path / "env-sandboxes"))
    explicit = tmp_path / "explicit-sandboxes"
    assert paths.find_sandbox_root(explicit) == explicit.resolve()


def test_default_sandbox_root_sits_beside_the_discovered_install(
    fake_install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STS2_SANDBOX_ROOT", raising=False)
    monkeypatch.setenv("STS2_GAME_ROOT", str(fake_install))
    local_appdata = tmp_path / "local-appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    root = paths.find_sandbox_root()

    assert paths.volume_root(root) == paths.volume_root(fake_install)
    assert root == (fake_install.parent / "divine-sts2" / "full-app-sandboxes").resolve()
    assert local_appdata not in root.parents


def test_default_sandbox_root_accepts_a_named_install(fake_install: Path) -> None:
    root = paths.find_sandbox_root(game_root=fake_install)
    assert paths.volume_root(root) == paths.volume_root(fake_install)
    assert root == paths.sandbox_root_beside(fake_install)


def test_client_config_puts_the_sandbox_beside_the_game_root_it_names(
    fake_install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STS2_SANDBOX_ROOT", raising=False)
    monkeypatch.setenv("STS2_GAME_ROOT", str(tmp_path / "other-library" / "Slay the Spire 2"))

    config = FullAppClientConfig(game_root=str(fake_install))

    assert Path(config.sandbox_root) == paths.sandbox_root_beside(fake_install)


def test_environment_sandbox_root_beats_the_game_root_default(
    fake_install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = tmp_path / "named-sandboxes"
    monkeypatch.setenv("STS2_SANDBOX_ROOT", str(named))

    config = FullAppClientConfig(game_root=str(fake_install))

    assert Path(config.sandbox_root) == named.resolve()


def test_sandbox_root_falls_back_to_local_appdata_without_an_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STS2_SANDBOX_ROOT", raising=False)
    monkeypatch.delenv("STS2_GAME_ROOT", raising=False)
    local_appdata = tmp_path / "local-appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    def undiscoverable(*args: object, **kwargs: object) -> Path:
        raise paths.DiscoveryError("no install here")

    monkeypatch.setattr(paths, "find_game_root", undiscoverable)

    assert paths.find_sandbox_root() == (local_appdata / "divine-sts2" / "full-app-sandboxes").resolve()


def test_volume_root_names_a_drive_or_mount_point(fake_install: Path) -> None:
    volume = paths.volume_root(fake_install / "SlayTheSpire2.pck")
    assert volume
    assert (fake_install / "SlayTheSpire2.pck").is_relative_to(Path(volume))


def test_existing_discovery_overrides_are_unchanged(fake_install: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert paths.find_game_root(fake_install) == fake_install.resolve()

    monkeypatch.setenv("STS2_GAME_ROOT", str(fake_install))
    assert paths.find_game_root() == fake_install.resolve()
    assert paths.find_game_assembly() == (fake_install / paths.GAME_DATA_DIRECTORY_NAME / "sts2.dll").resolve()
