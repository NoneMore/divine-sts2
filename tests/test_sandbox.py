from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from sts2_native_sim import full_app_client, full_app_sandbox, paths
from sts2_native_sim.full_app_client import FullAppBridgeClient, FullAppClientConfig


def test_install_files_are_hard_linked_rather_than_copied(fake_install: Path, tmp_path: Path) -> None:
    sandbox_dir = tmp_path / "sandboxes" / "worker_0"

    share = full_app_sandbox.share_install(fake_install, sandbox_dir)

    linked = sandbox_dir / "SlayTheSpire2.pck"
    source = fake_install / "SlayTheSpire2.pck"
    assert linked.read_bytes() == b"pck"
    assert os.stat(linked).st_ino == os.stat(source).st_ino
    assert os.stat(linked).st_nlink >= 2
    assert {path.name for path in share.linked_files} == {"SlayTheSpire2.exe", "SlayTheSpire2.pck"}


def test_install_directories_are_junctioned_rather_than_copied(fake_install: Path, tmp_path: Path) -> None:
    sandbox_dir = tmp_path / "sandboxes" / "worker_0"

    share = full_app_sandbox.share_install(fake_install, sandbox_dir)

    isjunction = getattr(os.path, "isjunction", None)
    for name in ("controller_config", paths.GAME_DATA_DIRECTORY_NAME):
        shared, installed = sandbox_dir / name, fake_install / name
        assert shared.is_dir()
        # A junction resolves to the install's own directory; a copy would not.
        assert os.stat(shared).st_ino == os.stat(installed).st_ino
        if isjunction is not None:
            assert isjunction(shared)
    assert {path.name for path in share.junctioned_dirs} == {"controller_config", paths.GAME_DATA_DIRECTORY_NAME}
    assert (sandbox_dir / "controller_config" / "controller.save").read_bytes() == b"cfg"


def test_sharing_the_install_twice_is_idempotent(fake_install: Path, tmp_path: Path) -> None:
    sandbox_dir = tmp_path / "sandboxes" / "worker_0"

    first = full_app_sandbox.share_install(fake_install, sandbox_dir)
    second = full_app_sandbox.share_install(fake_install, sandbox_dir)

    assert first.linked_files
    assert second.linked_files == ()
    assert second.junctioned_dirs == ()


def test_cross_volume_link_failure_names_the_volume_and_copies_nothing(
    fake_install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_to_link(source: object, destination: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", refuse_to_link)
    sandbox_dir = tmp_path / "sandboxes" / "worker_0"

    with pytest.raises(full_app_sandbox.SandboxPreparationError) as raised:
        full_app_sandbox.share_install(fake_install, sandbox_dir)

    message = str(raised.value)
    assert str(fake_install / "SlayTheSpire2.exe") in message
    assert str(sandbox_dir / "SlayTheSpire2.exe") in message
    assert paths.volume_root(fake_install) in message
    assert paths.volume_root(sandbox_dir) in message
    assert "STS2_SANDBOX_ROOT" in message
    assert list(sandbox_dir.iterdir()) == []


def test_prepare_sandbox_reports_the_location_it_used(
    fake_install: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STS2_SANDBOX_ROOT", raising=False)
    if not full_app_client.bridge_package_dir().is_dir():
        pytest.skip("the full-app bridge package is not built")

    sandbox_root = tmp_path / "sandboxes"
    client = FullAppBridgeClient(
        FullAppClientConfig(game_root=str(fake_install), sandbox_root=str(sandbox_root), worker_id=0)
    )

    layout = client.prepare_sandbox()

    assert layout.worker_dir == client.sandbox_dir
    assert layout.sandbox_root == sandbox_root.resolve()
    assert layout.volume == paths.volume_root(sandbox_root)
    assert str(sandbox_root) in layout.describe()
    linked = client.sandbox_dir / "SlayTheSpire2.pck"
    assert os.stat(linked).st_ino == os.stat(fake_install / "SlayTheSpire2.pck").st_ino
