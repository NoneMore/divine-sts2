# 02: A native worker that adapts to a read-only user profile

**What to build:** Every Python entry point that starts a Godot worker currently has to be handed a
four-line PowerShell block redirecting `APPDATA`, `LOCALAPPDATA`, `TEMP` and `TMP`, or Godot dies
headless with `Failed to open 'user://logs/...'` followed by `signal 11`. `NativeWorker` instead
redirects those directories itself, but only when the real ones cannot be written, so a normal host
sees no change. Discovery also stops borrowing a sibling checkout's toolchain, and a failed game-root
search explains what it looked for instead of only what it wanted.

**Blocked by:** 01 (the `.env` loader is what lets `doctor` run here without an exported env block).

**Status:** done

- [x] `NativeWorker._start()` probes the user-data location and, only when it is not writable,
      redirects `APPDATA`, `LOCALAPPDATA`, `TEMP` and `TMP` into
      `<repo>\.tools\tmp\native-worker\...`, creating the directories it needs.
- [x] A redirect is reported once on the worker's stderr so a caller can see where Godot's user data
      went; when nothing is redirected, nothing is printed.
- [x] A test under `tests/` covers the probe's decision on a writable location (no redirect, no
      environment mutation) and the redirect's target layout.
- [x] `paths.find_dotnet()`, `paths.find_godot()` and `client.py` no longer fall back to
      `<parent>\.tools`: a repository looks only inside its own `.tools`.
- [x] `paths.find_game_root()`'s failure message names `STS2_GAME_ROOT` and states that Steam
      libraries are read from `%PROGRAMFILES%`, `%PROGRAMFILES(X86)%` and `STEAM_PATH` only, with no
      registry lookup.
- [x] `python -m sts2_native_sim.cli doctor --deep` passes on this host with only `.env` supplying
      `STS2_GAME_ROOT` and `GODOT` — no manually exported user-directory variables.

## Comments

**2026-09-15 — implemented.**

- The probe lives in `paths.is_directory_writable()` and `paths.native_worker_user_directory_overrides()`.
  It deliberately does **not** use `tempfile`/`mkdtemp`: those create a directory with `mode=0o700`,
  which this class of sandbox refuses even where ordinary files are fine. The first implementation used
  `tempfile.TemporaryDirectory` and therefore reported genuinely writable locations as unwritable —
  caught by probing this host, where `.tools\tmp\probe-ok` accepted a file but rejected the `0o700`
  directory. It now writes and removes one file of its own.
- The redirect triggers on `%APPDATA%` alone being absent or refused, which keeps non-Windows hosts
  (no `APPDATA`) untouched without an `os.name` branch.
- Verified with a real worker: `pwsh scripts/doctor.ps1 -Deep -Json` returned `"ok": true` (exit 0)
  with `game_root`/`godot` coming only from `.env`, and the worker printed
  `[sts2_native_sim] The user profile is not writable; the worker's user data goes to
  <repo>\.tools\tmp\native-worker\appdata.` before `worker_hello` succeeded, so the redirect works for
  a shipped Godot 4.5.1 worker and not just in the probe.
- `tests/test_dev_environment.py` covers: a writable directory is accepted and left empty; a refused
  one is reported; a writable `%APPDATA%` produces no overrides; a refused one produces all four names
  pointing into the redirect root with the directories created; no `%APPDATA%` produces no overrides;
  the discovery message names `STS2_GAME_ROOT` and `STEAM_PATH`; and the `.env` loader fills only
  unset variables (via `pwsh`, skipped when it is unavailable). Suite total: 31 passed.
- The sibling-`.tools` fallback is gone from `paths.find_dotnet()`, `paths.find_godot()` and
  `NativeWorker._start()`; `python/sts2_native_sim/client.py` still resolves only its own repository.
