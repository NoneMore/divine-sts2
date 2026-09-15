# 01: Configurable sandbox root for the full-app bridge

**What to build:** A machine whose shipped-game install and local app-data live on different drives can prepare a full-app sandbox without copying the install. Path discovery gains a sandbox root that can be named explicitly and through an environment override, defaulting to a location on the game install's own volume so the bridge's hard links succeed. With that in place, preparing a sandbox consumes no install-sized copy, and the oracle stops being silently machine-specific.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] The sandbox root can be set explicitly and through an environment variable; with neither set, it defaults to a location on the same volume as the discovered game install.
- [x] Preparing a full-app sandbox for a game install on a secondary Steam library hard-links the install rather than copying it, and the prepared sandbox consumes no copy of the install.
- [x] The location that was used is reported, so a hard-link failure names the volume it tried instead of silently copying.
- [x] Game-root, assembly, host and Godot discovery are otherwise unchanged, including their existing explicit and environment overrides.

## Comments

**2026-09-15 — implemented.**

- `paths.find_sandbox_root()` resolves the sandbox root from an explicit argument, then
  `STS2_SANDBOX_ROOT`, then a location beside the discovered install, on its own volume;
  `paths.volume_root()` names a volume for the check and for messages. Without a discoverable install the
  previous `%LOCALAPPDATA%` location is kept, because there is no install to hard-link. The old
  `default_sandbox_root()` name is gone rather than kept as an alias: its default changed meaning, so a
  caller relying on the old one would silently get a different location.
- Install sharing moved to `python/sts2_native_sim/full_app_sandbox.py`: `share_install()` hard-links the
  install's top-level files and junctions its directories, and reports what it shared (`SandboxShare`). The
  `shutil.copy2` fallback for install files is gone, so a cross-volume link raises `SandboxPreparationError`
  naming both volumes and the fix rather than filling a drive.
- `FullAppClientConfig.sandbox_root` defaults to the volume of the game root that config names — the
  ticket's cross-drive case — so a caller who passes `game_root` explicitly (as `densify_community_runs.py`
  does) is never sent to another volume's default.
- `FullAppBridgeClient.prepare_sandbox()` returns a `SandboxLayout` whose `describe()` names the worker
  directory, its volume, the root, the install and the link/junction counts;
  `full_app_bridge_acceptance.py` prints it per worker and records it as `sandbox_root` in the report.
- Offline tests: `tests/test_sandbox_root.py` (explicit, environment, default-on-install-volume, fallback,
  unchanged game-root/assembly overrides) and `tests/test_sandbox.py` (hard links not copies, junctions not
  copies, idempotence, cross-volume failure message, end-to-end layout reporting). 22 tests pass.
- **Observed** on this machine — a shipped install on a secondary Steam library volume (`F:`) with
  app-data on the system volume (`C:`): the default root resolved beside the install
  (`<library>\steamapps\common\divine-sts2\full-app-sandboxes`); `SlayTheSpire2.exe` (894 MB) and
  `SlayTheSpire2.pck` (1.77 GB) shared the install's inode with `st_nlink == 2`;
  `controller_config` and `data_sts2_windows_x86_64` were junctions; `C:` free space was unchanged at
  11.68 GB before and after; with the root forced onto `C:` preparation refused with `[WinError 17]`
  wrapped in `SandboxPreparationError` naming `F:\` and `C:\`, and left nothing behind.
- Left alone deliberately: repairing Steam-root discovery, and the ~11 GB of copied sandboxes the old
  fallback left in `%LOCALAPPDATA%\divine-sts2\full-app-sandboxes` (the ticket's motivating damage).
