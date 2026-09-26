"""Portable discovery for user-owned game and tool installations."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GAME_DIRECTORY_NAME = "Slay the Spire 2"
GAME_DATA_DIRECTORY_NAME = "data_sts2_windows_x86_64"
GODOT_VERSION = "4.5.1"
_SANDBOX_DIRECTORY = Path("divine-sts2") / "full-app-sandboxes"
_DOT_ENV_PATH_VARIABLES = {
    "STS2_GAME_ROOT",
    "STS2_SANDBOX_ROOT",
    "GODOT",
}


class DiscoveryError(FileNotFoundError):
    """Raised when a required local dependency cannot be discovered."""


def _load_dot_env(path: str | Path | None = None) -> None:
    """Fill unset environment variables from the repository-local .env file."""

    env_path = Path(path) if path is not None else REPOSITORY_ROOT / ".env"
    if not env_path.is_file():
        return

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        name, value = (part.strip() for part in stripped.split("=", 1))
        if not name or name in os.environ:
            continue
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        if name in _DOT_ENV_PATH_VARIABLES and value and not Path(value).is_absolute():
            value = str((REPOSITORY_ROOT / value).resolve())
        os.environ[name] = value


def _registry_steam_roots() -> list[Path]:
    if os.name != "nt":
        return []

    try:
        import winreg
    except ImportError:
        return []

    probes = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    )
    roots: list[Path] = []
    for hive, key_name, value_name in probes:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue
        if value:
            roots.append(Path(str(value)))
    return roots


def _steam_roots() -> list[Path]:
    candidates: list[Path] = _registry_steam_roots()
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
        "it in .env. Steam libraries are read from the Windows registry, %PROGRAMFILES%, "
        "%PROGRAMFILES(X86)% and STEAM_PATH. "
        f"Searched: {searched}"
    )


def find_game_assembly(explicit: str | Path | None = None) -> Path:
    candidate = (
        Path(explicit).expanduser().resolve()
        if explicit
        else find_game_root() / GAME_DATA_DIRECTORY_NAME / "sts2.dll"
    )
    if not candidate.is_file():
        raise DiscoveryError(f"STS2 assembly not found: {candidate}")
    return candidate


def expected_dotnet_version() -> str:
    configuration = json.loads((REPOSITORY_ROOT / "global.json").read_text(encoding="utf-8"))
    return str(configuration["sdk"]["version"])


def _dotnet_has_expected_sdk(executable: Path) -> bool:
    expected = expected_dotnet_version()
    try:
        result = subprocess.run(
            [str(executable), "--list-sdks"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and any(
        line.strip().startswith(f"{expected} ") for line in result.stdout.splitlines()
    )


def find_dotnet(explicit: str | Path | None = None) -> Path:
    expected = expected_dotnet_version()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_file():
            raise DiscoveryError(f"Dotnet executable not found: {candidate}")
        if not _dotnet_has_expected_sdk(candidate):
            raise DiscoveryError(f"Configured dotnet does not provide SDK {expected}: {candidate}")
        return candidate

    resolved = shutil.which("dotnet")
    if resolved:
        candidate = Path(resolved).resolve()
        if _dotnet_has_expected_sdk(candidate):
            return candidate

    exe_name = "dotnet.exe" if os.name == "nt" else "dotnet"
    bundled = REPOSITORY_ROOT / ".tools" / "dotnet9" / exe_name
    if bundled.is_file() and _dotnet_has_expected_sdk(bundled):
        return bundled.resolve()

    raise DiscoveryError(f".NET SDK {expected} was not found. Run `pwsh ./dev.ps1 setup`.")


def find_host_assembly(explicit: str | Path | None = None) -> Path:
    override = explicit or os.environ.get("STS2_NATIVE_HOST")
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise DiscoveryError(f"Host assembly not found: {candidate}")

    release_dll = (
        REPOSITORY_ROOT
        / "src"
        / "Sts2.NativeSim.Host"
        / "bin"
        / "Release"
        / "net9.0"
        / "Sts2.NativeSim.Host.dll"
    )
    if release_dll.is_file():
        return release_dll.resolve()

    debug_dll = (
        REPOSITORY_ROOT
        / "src"
        / "Sts2.NativeSim.Host"
        / "bin"
        / "Debug"
        / "net9.0"
        / "Sts2.NativeSim.Host.dll"
    )
    if debug_dll.is_file():
        return debug_dll.resolve()

    release_exe = (
        REPOSITORY_ROOT
        / "src"
        / "Sts2.NativeSim.Host"
        / "bin"
        / "Release"
        / "net9.0"
        / "Sts2.NativeSim.Host.exe"
    )
    if release_exe.is_file():
        return release_exe.resolve()

    raise DiscoveryError("Sts2.NativeSim.Host was not built. Run `pwsh ./dev.ps1 build`.")


def _is_supported_godot(executable: Path) -> bool:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    version = (result.stdout or result.stderr).strip().lower()
    if version.startswith(GODOT_VERSION) and "mono" in version:
        return True
    # The non-console Windows build may not attach captured stdout. Its official
    # versioned filename is still an exact distribution identity.
    name = executable.name.lower()
    return name in {
        "godot_v4.5.1-stable_mono_win64.exe",
        "godot_v4.5.1-stable_mono_win64_console.exe",
    }


def find_godot(explicit: str | Path | None = None) -> Path:
    override = explicit or os.environ.get("GODOT")
    if override:
        candidate = Path(override).expanduser().resolve()
        if not candidate.is_file():
            raise DiscoveryError(f"Godot executable not found: {candidate}")
        if not _is_supported_godot(candidate):
            raise DiscoveryError(f"Configured Godot is not {GODOT_VERSION} .NET/Mono: {candidate}")
        return candidate

    names = (
        "godot",
        "godot4",
        "Godot_v4.5.1-stable_mono_win64_console.exe",
        "Godot_v4.5.1-stable_mono_win64.exe",
    )
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            candidate = Path(resolved).resolve()
            if _is_supported_godot(candidate):
                return candidate

    tool_root = REPOSITORY_ROOT / ".tools" / "godot-4.5.1-mono"
    if tool_root.exists():
        for name in names[2:]:
            match = next(tool_root.rglob(name), None)
            if match and _is_supported_godot(match):
                return match.resolve()

    raise DiscoveryError(
        f"Godot {GODOT_VERSION} .NET/Mono was not found. Run `pwsh ./dev.ps1 setup` or set GODOT."
    )


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


_load_dot_env()
