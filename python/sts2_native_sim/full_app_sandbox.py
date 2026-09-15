"""Sharing a shipped install into a full-app sandbox without copying it.

Each full-app worker runs the shipped game from its own sandbox directory with
its own user-data directories. The install is shared rather than repeated: its
top-level files are hard-linked and its directories are junctioned, so a sandbox
costs no install-sized copy. A hard link cannot cross volumes, so a link failure
names the volume it tried instead of silently falling back to a copy.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .paths import GAME_DATA_DIRECTORY_NAME, sandbox_root_beside, volume_root


SANDBOX_ROOT_ENVIRONMENT_VARIABLE = "STS2_SANDBOX_ROOT"
INSTALL_DIRECTORY_JUNCTIONS = ("controller_config", GAME_DATA_DIRECTORY_NAME)


class SandboxPreparationError(RuntimeError):
    """Raised when a sandbox cannot be prepared without copying the install."""


@dataclass(frozen=True)
class SandboxShare:
    """The install entries a sandbox shares, as created by one sharing call."""

    linked_files: tuple[Path, ...] = ()
    junctioned_dirs: tuple[Path, ...] = ()


@dataclass(frozen=True)
class SandboxLayout:
    """Where a worker's sandbox is, and what it shares with the install."""

    game_root: Path
    sandbox_root: Path
    worker_dir: Path
    share: SandboxShare

    @property
    def volume(self) -> str:
        return volume_root(self.worker_dir)

    def describe(self) -> str:
        return (
            f"full-app sandbox {self.worker_dir} on volume {self.volume} "
            f"(root {self.sandbox_root}, install {self.game_root}): "
            f"{len(self.share.linked_files)} install files hard-linked, "
            f"{len(self.share.junctioned_dirs)} install directories junctioned"
        )


def _link_install_file(source: Path, destination: Path) -> None:
    """Hard-link one install file into a sandbox, naming the volumes on failure."""
    try:
        os.link(source, destination)
    except OSError as exc:
        raise SandboxPreparationError(
            f"Could not hard-link {source} to {destination}: {exc}. "
            f"Hard links cannot cross volumes: the install is on {volume_root(source)} "
            f"and the sandbox is on {volume_root(destination)}. Point the sandbox root at the install's "
            f"volume, for example {SANDBOX_ROOT_ENVIRONMENT_VARIABLE}={sandbox_root_beside(source.parent)}."
        ) from exc


def _junction_directory(source: Path, destination: Path) -> None:
    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(destination), str(source)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SandboxPreparationError(
            f"Could not junction install directory {source} into the sandbox at {destination}: {exc}. "
            f"The install is on {volume_root(source)} and the sandbox is on {volume_root(destination)}."
        ) from exc


def share_install(game_root: Path, sandbox_dir: Path) -> SandboxShare:
    """Hard-link the install's files and junction its directories into a sandbox."""
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    linked: list[Path] = []
    for item in sorted(game_root.iterdir()):
        if not item.is_file():
            continue
        destination = sandbox_dir / item.name
        if destination.exists():
            continue
        _link_install_file(item, destination)
        linked.append(destination)

    junctioned: list[Path] = []
    for name in INSTALL_DIRECTORY_JUNCTIONS:
        source = game_root / name
        destination = sandbox_dir / name
        if not source.is_dir() or destination.exists():
            continue
        _junction_directory(source, destination)
        junctioned.append(destination)

    return SandboxShare(tuple(linked), tuple(junctioned))
