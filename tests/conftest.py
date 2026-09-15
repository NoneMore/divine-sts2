from __future__ import annotations

from pathlib import Path

import pytest

from sts2_native_sim import paths


@pytest.fixture
def fake_install(tmp_path: Path) -> Path:
    """A minimal shipped-install layout that game-root discovery accepts."""
    root = tmp_path / "SlayTheSpire2"
    (root / paths.GAME_DATA_DIRECTORY_NAME).mkdir(parents=True)
    (root / "SlayTheSpire2.exe").write_bytes(b"exe")
    (root / "SlayTheSpire2.pck").write_bytes(b"pck")
    (root / paths.GAME_DATA_DIRECTORY_NAME / "sts2.dll").write_bytes(b"dll")
    (root / "controller_config").mkdir()
    (root / "controller_config" / "controller.save").write_bytes(b"cfg")
    return root
