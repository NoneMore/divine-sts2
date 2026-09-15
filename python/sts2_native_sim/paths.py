"""Portable discovery for user-owned game and tool installations."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GAME_DIRECTORY_NAME = "Slay the Spire 2"
GAME_DATA_DIRECTORY_NAME = "data_sts2_windows_x86_64"
_SANDBOX_DIRECTORY = Path("divine-sts2") / "full-app-sandboxes"


class DiscoveryError(FileNotFoundError):
    """Raised when a required local dependency cannot be discovered."""


def _steam_roots() -> list[Path]:
    candidates: list[Path] = []
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Steam")
    steam_path = os.environ.get("STEAM_PATH")
    if steam_path:
        candidates.insert(0, Path(steam_path))

    roots: list[Path] = []
    for steam in candidates:
        roots.append(steam)
        manifest = steam / "steamapps" / "libraryfolders.vdf"
        if not manifest.is_file():
            continue
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for value in re.findall(r'"path"\s+"([^"]+)"', text):
            roots.append(Path(value.replace("\\\\", "\\")))
    return list(dict.fromkeys(path.resolve() for path in roots if path.exists()))


def find_game_root(explicit: str | Path | None = None) -> Path:
    override = explicit or os.environ.get("STS2_GAME_ROOT")
    if override:
        candidate = Path(override).expanduser().resolve()
        if (
            (candidate / "SlayTheSpire2.exe").is_file()
            and (candidate / "SlayTheSpire2.pck").is_file()
            and (candidate / GAME_DATA_DIRECTORY_NAME / "sts2.dll").is_file()
        ):
            return candidate
        raise DiscoveryError(f"Configured STS2_GAME_ROOT is not a complete game install: {candidate}")

    candidates: list[Path] = []
    candidates.extend(root / "steamapps" / "common" / GAME_DIRECTORY_NAME for root in _steam_roots())
    for candidate in candidates:
        candidate = candidate.resolve()
        if (
            (candidate / "SlayTheSpire2.exe").is_file()
            and (candidate / "SlayTheSpire2.pck").is_file()
            and (candidate / GAME_DATA_DIRECTORY_NAME / "sts2.dll").is_file()
        ):
            return candidate
    searched = ", ".join(str(path) for path in candidates) or "standard Steam libraries"
    raise DiscoveryError(
        "Slay the Spire 2 was not found. Set STS2_GAME_ROOT to the installed game directory, or put "
        "it in .env. Steam libraries are read from %PROGRAMFILES%, %PROGRAMFILES(X86)% and STEAM_PATH "
        "only, so a Steam installation that is not below one of those needs the variable. "
        f"Searched: {searched}"
    )


def find_game_assembly(explicit: str | Path | None = None) -> Path:
    override = explicit or os.environ.get("STS2_ASSEMBLY")
    candidate = Path(override).expanduser().resolve() if override else find_game_root() / GAME_DATA_DIRECTORY_NAME / "sts2.dll"
    if not candidate.is_file():
        raise DiscoveryError(f"STS2 assembly not found: {candidate}")
    return candidate


def find_dotnet(explicit: str | Path | None = None) -> Path:
    override = explicit or os.environ.get("DOTNET")
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise DiscoveryError(f"Dotnet executable not found: {candidate}")

    exe_name = "dotnet.exe" if os.name == "nt" else "dotnet"
    candidates = [
        REPOSITORY_ROOT / ".tools" / "dotnet9" / exe_name,
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()

    resolved = shutil.which("dotnet")
    if resolved:
        return Path(resolved).resolve()
    raise DiscoveryError(".NET 9 SDK was not found. Run scripts/install-dotnet-9.ps1 or set DOTNET.")


def find_host_assembly(explicit: str | Path | None = None) -> Path:
    override = explicit or os.environ.get("STS2_NATIVE_HOST")
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise DiscoveryError(f"Host assembly not found: {candidate}")

    release_dll = REPOSITORY_ROOT / "src" / "Sts2.NativeSim.Host" / "bin" / "Release" / "net9.0" / "Sts2.NativeSim.Host.dll"
    if release_dll.is_file():
        return release_dll.resolve()

    debug_dll = REPOSITORY_ROOT / "src" / "Sts2.NativeSim.Host" / "bin" / "Debug" / "net9.0" / "Sts2.NativeSim.Host.dll"
    if debug_dll.is_file():
        return debug_dll.resolve()

    # Also check for .exe
    release_exe = REPOSITORY_ROOT / "src" / "Sts2.NativeSim.Host" / "bin" / "Release" / "net9.0" / "Sts2.NativeSim.Host.exe"
    if release_exe.is_file():
        return release_exe.resolve()

    raise DiscoveryError("Sts2.NativeSim.Host was not built. Run scripts/build-persistent-server.ps1 or dotnet build.")


def find_godot(explicit: str | Path | None = None) -> Path:
    override = explicit or os.environ.get("GODOT")
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise DiscoveryError(f"Godot executable not found: {candidate}")

    tool_roots = [
        REPOSITORY_ROOT / ".tools" / "godot-4.5.1-mono",
    ]
    names = (
        "Godot_v4.5.1-stable_mono_win64_console.exe",
        "Godot_v4.5.1-stable_mono_win64.exe",
    )
    for tool_root in tool_roots:
        if tool_root.exists():
            for name in names:
                match = next(tool_root.rglob(name), None)
                if match:
                    return match.resolve()
    for name in ("godot", "godot4", *names):
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved).resolve()
    raise DiscoveryError("Godot 4.5.1 .NET was not found. Optional for pure .NET runner; required only for FullAppBridge.")


def volume_root(path: str | Path) -> str:
    """The volume a path lives on: a drive root on Windows, `/` elsewhere.

    A full-app sandbox hard-links the shipped install, and hard links cannot
    cross volumes, so this is what a sandbox location has to match.
    """
    return Path(path).expanduser().absolute().anchor or os.sep


def sandbox_root_beside(install: str | Path) -> Path:
    """The default sandbox root for an install: beside it, on the install's volume."""
    return Path(install).expanduser().resolve().parent / _SANDBOX_DIRECTORY


def _local_appdata_sandbox_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return base / _SANDBOX_DIRECTORY


def find_sandbox_root(explicit: str | Path | None = None, *, game_root: str | Path | None = None) -> Path:
    """Resolve where full-app sandboxes are prepared.

    Named explicitly, then through `STS2_SANDBOX_ROOT`, then beside the game
    install — on its own volume, because the install is hard-linked into each
    sandbox and a hard link cannot cross volumes. Without a discoverable install
    there is nothing to link, so the local application data location is used
    instead; preparation still refuses loudly if that turns out to be another
    volume.
    """
    override = explicit or os.environ.get("STS2_SANDBOX_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    try:
        install = Path(game_root).expanduser().resolve() if game_root else find_game_root()
    except DiscoveryError:
        return _local_appdata_sandbox_root()
    return sandbox_root_beside(install)


def is_directory_writable(directory: str | Path) -> bool:
    """Whether files can be created under `directory`, leaving nothing behind.

    A probe rather than a permission query: a file sandbox refuses writes that the
    filesystem's own permissions allow. It writes a file and removes it again — never
    `tempfile`, whose directories are created with `mode=0o700` and are refused by a
    sandbox that would have accepted an ordinary file.
    """
    target = Path(directory).expanduser()
    probe = target / f".sts2-write-probe-{os.urandom(4).hex()}"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return True


def native_worker_user_directory_overrides(root: str | Path | None = None) -> dict[str, str]:
    """Environment that redirects the worker's user-facing directories into the repository.

    Godot writes its `user://` data under `%APPDATA%` and dies headless, before it starts,
    when that location is refused — a sandboxed host, or a read-only profile. Only a
    location that is actually refused is redirected, so a host that allows it keeps its own
    user data; without an `%APPDATA%` at all (not a Windows host) there is nothing to
    redirect. `root` names the repository-local base, for tests.
    """
    appdata = os.environ.get("APPDATA")
    if not appdata or is_directory_writable(appdata):
        return {}
    base = Path(root) if root else REPOSITORY_ROOT / ".tools" / "tmp" / "native-worker"
    overrides = {
        "APPDATA": base / "appdata",
        "LOCALAPPDATA": base / "localappdata",
        "TEMP": base / "temp",
        "TMP": base / "temp",
    }
    for directory in dict.fromkeys(overrides.values()):
        directory.mkdir(parents=True, exist_ok=True)
    return {name: str(directory) for name, directory in overrides.items()}
