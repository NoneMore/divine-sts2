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
ENV_FILE_NAME = ".env"

# Windows always defines these two variables, so the normal "a real environment variable
# wins over the file" rule would make `.env` unable to redirect them. A sandboxed session
# may only write inside the checkout, while Godot needs a writable `user://` directory and
# the full-application sandbox root derives from `LOCALAPPDATA`; both are therefore
# explicitly overridable from the file when the file names them. Every other key keeps
# process precedence, so CI and explicit shell exports still win.
ENV_FILE_OVERRIDE_KEYS: frozenset[str] = frozenset({"APPDATA", "LOCALAPPDATA"})

_ENV_FILE_LOADED = False


class DiscoveryError(FileNotFoundError):
    """Raised when a required local dependency cannot be discovered."""


def parse_env_file(text: str) -> dict[str, str]:
    """Parse `KEY=VALUE` overrides, ignoring blank lines and `#` comments."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env_file(path: str | Path | None = None) -> list[str]:
    """Apply repository `.env` overrides to `os.environ`.

    A real process environment variable always wins over the file, so CI and
    explicit shell exports keep precedence. The two Windows-managed keys in
    `ENV_FILE_OVERRIDE_KEYS` are the documented exception, because they are
    always defined and would otherwise be impossible to redirect. Returns the
    names applied.
    """
    global _ENV_FILE_LOADED
    default_file = path is None
    target = REPOSITORY_ROOT / ENV_FILE_NAME if default_file else Path(path)
    if default_file:
        if _ENV_FILE_LOADED:
            return []
        _ENV_FILE_LOADED = True
    if not target.is_file():
        return []
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    applied: list[str] = []
    for key, value in parse_env_file(text).items():
        if os.environ.get(key) and key not in ENV_FILE_OVERRIDE_KEYS:
            continue
        os.environ[key] = value
        applied.append(key)
    return applied


def _environment(name: str) -> str | None:
    """Read a configuration variable after repository `.env` defaults are applied."""
    load_env_file()
    value = os.environ.get(name)
    return value or None


def _registry_steam_roots() -> list[Path]:
    """Steam libraries registered with Windows, including non-default drives."""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows only module.
        return []

    lookups = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    )
    roots: list[Path] = []
    for hive, key_path, value_name in lookups:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            # Steam records SteamPath with forward slashes.
            roots.append(Path(value.strip().replace("/", "\\")))
    return roots


def _steam_roots() -> list[Path]:
    candidates: list[Path] = []
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Steam")
    steam_path = _environment("STEAM_PATH")
    if steam_path:
        candidates.insert(0, Path(steam_path))
    candidates.extend(_registry_steam_roots())

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
    override = explicit or _environment("STS2_GAME_ROOT")
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
        f"Slay the Spire 2 was not found. Set STS2_GAME_ROOT in the environment or in {REPOSITORY_ROOT / ENV_FILE_NAME} "
        f"to the installed game directory. Searched: {searched}"
    )


def find_game_assembly(explicit: str | Path | None = None) -> Path:
    override = explicit or _environment("STS2_ASSEMBLY")
    candidate = Path(override).expanduser().resolve() if override else find_game_root() / GAME_DATA_DIRECTORY_NAME / "sts2.dll"
    if not candidate.is_file():
        raise DiscoveryError(f"STS2 assembly not found: {candidate}")
    return candidate


def find_dotnet(explicit: str | Path | None = None) -> Path:
    override = explicit or _environment("DOTNET")
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise DiscoveryError(f"Dotnet executable not found: {candidate}")

    exe_name = "dotnet.exe" if os.name == "nt" else "dotnet"
    candidates = [
        REPOSITORY_ROOT / ".tools" / "dotnet9" / exe_name,
        REPOSITORY_ROOT.parent / ".tools" / "dotnet9" / exe_name,
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()

    resolved = shutil.which("dotnet")
    if resolved:
        return Path(resolved).resolve()
    raise DiscoveryError(".NET 9 SDK was not found. Run scripts/install-dotnet-9.ps1 or set DOTNET.")


def find_host_assembly(explicit: str | Path | None = None) -> Path:
    override = explicit or _environment("STS2_NATIVE_HOST")
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
    override = explicit or _environment("GODOT")
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise DiscoveryError(f"Godot executable not found: {candidate}")

    tool_roots = [
        REPOSITORY_ROOT / ".tools" / "godot-4.5.1-mono",
        REPOSITORY_ROOT.parent / ".tools" / "godot-4.5.1-mono",
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


def default_sandbox_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return base / "divine-sts2" / "full-app-sandboxes"
