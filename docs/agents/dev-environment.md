# Dev environment: sandboxed Windows work on this repo

This repository adapts itself to a Windows host whose file sandbox permits writes inside the
repository only, whose user profile is not writable, and whose proxy refuses the download transports
`curl` and `Invoke-WebRequest` accept. The adaptations live in `scripts/common.ps1`,
`python/sts2_native_sim/paths.py` and `NativeWorker`, each conditional on a probe, so a host without
those restrictions behaves exactly as it did. This file says what to run, which repository defects
exist, and what the host refuses.

## What to run

```powershell
pwsh scripts/bootstrap.ps1                  # first time: toolchain, Python env, host build, doctor
pwsh scripts/doctor.ps1 -Deep               # validate the game and toolchain, hash the build, start a worker
pwsh scripts/build-persistent-server.ps1    # rebuild Host and GodotHost
pwsh scripts/test-public-tree.ps1           # the public-tree gate, as CI runs it
python -m pytest tests -q                    # offline tests (see "pytest needs a writable temp root")
```

- `build-persistent-server.ps1` defaults to `Release`, which is what the pure .NET host uses. The Godot
  worker runs the project's **Debug** configuration instead, so a Core change built only with the default
  leaves the worker answering from stale assemblies — with no error, just the old behaviour. Pass
  `-Configuration Debug` when the next step starts a worker through `doctor.ps1 -Deep` or a Python
  `*_acceptance.py`: `doctor.ps1` builds nothing, and `bootstrap.ps1` builds `Release` only. (The PowerShell
  Godot scripts — `test-godot-determinism.ps1` and its siblings — build Debug themselves.)

- Local overrides — `STS2_GAME_ROOT`, `GODOT`, `STS2_SANDBOX_ROOT`, SDK state — belong in a gitignored
  `.env` (`.env.example` is the template). Loading is fill-only: a variable already set always wins.
- `.env` is read by the PowerShell layer (`scripts/common.ps1`). The Python CLI does not read it, so
  reach the CLI through a script — `scripts/doctor.ps1` — rather than from a bare shell.
- `scripts/common.ps1` owns host adaptation, and `Invoke-DivineDotnet` is the one `dotnet` entry point
  every script uses. No command here needs an exported environment block.

## Repository defects and their status

**The public-tree gate used to fail on the tree it gates.** Its single `git grep` matched a hardcoded
game path in `Directory.Build.props` and in a smoke-test project file, and — once the B1 finding in
`docs/architecture-review.md` quoted the command and its matches — that document too, so CI was red on
a pristine `main`. The two scans now have different scopes: a machine-specific path is forbidden
outside tracked markdown, while a secret token is forbidden everywhere, because a credential in prose
is still a leak (ADR-0004). Both hardcoded paths are gone: `GameDataDir` comes from `STS2_GAME_ROOT`
alone, and a project that references the shipped assemblies declares `RequiresGameData`, which fails
with `STS2_GAME_ROOT is not set` instead of a missing-reference error. `Protocol` and `Core` build
without the variable, which is what CI does.

**Steam-root discovery is still narrow.** `paths._steam_roots()` derives its candidates from
`%PROGRAMFILES%`, `%PROGRAMFILES(X86)%` and `STEAM_PATH`, and does read each candidate's
`libraryfolders.vdf`; what it never does is read the registry's `SteamPath`, so a Steam installation
that is not below one of those variables is invisible. The failure says so and names `STS2_GAME_ROOT`.
Repairing discovery belongs to the single-discovery-policy work recorded as out of scope in
`.scratch/act1-combat1-scenarios/spec.md`; set `STS2_GAME_ROOT` (or put it in `.env`) here.

## What this host refuses, and what happens instead

**The user profile is not writable.** `dotnet` would write first-run state under `%USERPROFILE%` and
fail with `UnauthorizedAccessException` before any build output. When a probe finds that location
refused, the script layer keeps SDK and package state under `.tools\dotnet-home` and
`.tools\nuget-packages` instead. The probe writes and removes one file: never `tempfile`/`mkdtemp`,
whose directories are created with `mode=0o700`, the mode this class of sandbox refuses even for a
location where ordinary files are fine.

**Godot dies headless before it starts.** The worker needs a writable `user://`, which maps under
`%APPDATA%`; refused, it reports `Failed to open 'user://logs/...'` and then `signal 11`.
`NativeWorker` probes `%APPDATA%` and, only when it is refused, redirects `APPDATA`, `LOCALAPPDATA`,
`TEMP` and `TMP` into `.tools\tmp\native-worker\...`, saying so once on stderr. Callers no longer
export that block; only `GODOT` and a game root remain theirs to supply.

**The proxy refuses `curl` and `Invoke-WebRequest`.** `curl` fails with
`schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`, `Invoke-WebRequest` with
`Authentication failed`, while the proxy itself is reachable. `Save-DivineDownload` tries `curl`
(resumable), then `Invoke-WebRequest`, then Python `urllib`, which honours `HTTP_PROXY`/`HTTPS_PROXY`
and names those variables when all three fail. `install-dotnet-9.ps1` passes `-ProxyAddress` on.

**The SDK cannot resolve its workload-locator directories.** `dotnet build` prints a summary of
`0 个警告 / 0 个错误` and exits 1, with the reason visible only under `-v diag`:

```
error MSB4276: The default SDK resolver failed to resolve SDK
"Microsoft.NET.SDK.WorkloadAutoImportPropsLocator" because directory "<sdk>\Sdks\...\Sdk" does not exist.
```

Building one project survives it; a project that *references* another fails, because the reference is
evaluated through the `MSBuild` task. `dotnet run` fails the same way and passes `-m:1` nowhere, so the
scripts build through the helper first and then run with `--no-build`. The helper adds `-m:1` only when
the locator directories are missing and prints why; a fix that keeps node reuse is still open.

**The vulnerability audit fails the build.** `NU1900` — the audit cannot reach `api.nuget.org` through
the proxy — becomes an error because `Directory.Build.props` sets `TreatWarningsAsErrors`, and
`--no-restore` does not help because the warning is replayed from the cached restore. Pass
`-p:NuGetAudit=false` explicitly — `pwsh scripts/build-persistent-server.ps1 -DisableNuGetAudit`
does it for the two host projects. This is deliberately not automatic (ADR-0005): it weakens every
build, and probing reachability is neither cheap nor reliable.

**pytest needs a writable temp root.** Measured, not inferred: pytest creates every temporary directory
with `mode=0o700` (`_pytest/tmpdir.py:139,158`, `_pytest/pathlib.py:232`) and this sandbox refuses a
directory created that way even to the process that created it, so every `tmp_path` test fails at setup
and session cleanup fails again. An in-repo `--basetemp` does not help — the same `mkdir` is used for it — so run
the suite where the file policy allows it; tests that only touch files they create themselves are
unaffected. A directory made with a plain `mkdir` in the host's temporary area is writable and
removable here, so a test that needs a writable root probes for exactly that and falls back to the
gitignored `artifacts/` tree only where the probe is refused — `tests/test_scenarios.py`'s
`_corpus_area` is that probe, and ADR-0005 is why it asks rather than assumes. Leftover
`.tools\tmp\pytest-*` directories cannot be listed or deleted from inside the sandbox.

**Godot picks the wrong .NET runtime.** Left alone, the host rolls the worker forward to the machine's
newest runtime and Harmony reports `CoreCLR version 10.0.12 is not supported`; pinning
`DOTNET_ROLL_FORWARD=LatestPatch` instead lands on 8.x and the project assembly fails to load
(`System.Runtime, Version=9.0.0.0`). `NativeWorker` sets `DOTNET_ROOT`, `DOTNET_ROOT_X64` and `PATH`
from a repo-local `.tools\dotnet9` and pins `DOTNET_ROLL_FORWARD=Major`, which is why the install
location matters rather than an environment tweak at each call site.

**`dotnet --info` throws.** `Win32Exception (5)` from `ProcessExtensions.GetParentProcessId` — the
sandbox denies `OpenProcess` on the parent. Noise; building and running are unaffected.

**`Sts2.NativeSim.Host --server` cannot drive the simulator.** `InstallSaveMock` reaches
`Godot.OS.GetCmdlineArgs()`, which needs the Godot native runtime, so it crashes with `0xC0000005`; the
Godot worker is the real path.

Versions in play: .NET SDK 9.0.318 (repo-local), .NET runtime 9.0.20, Godot 4.5.1 mono, shipped
assembly `sts2.dll` sha256 `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`.
