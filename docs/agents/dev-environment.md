# Dev environment: Windows work on this repository

What to run, and the one requirement a build has on this host.

## What to run

```powershell
pwsh scripts/bootstrap.ps1                  # first time: toolchain, Python env, host build, doctor
pwsh scripts/doctor.ps1 -Deep               # validate the game and toolchain, hash the build, start a worker
pwsh scripts/build-persistent-server.ps1    # rebuild Host; add -WithGodot for the Godot worker host
pwsh scripts/test-public-tree.ps1           # the public-tree gate, as CI runs it
python -m pytest tests -q                    # offline tests
```

- `build-persistent-server.ps1` defaults to `Release`, which is what the pure .NET host uses. The Godot
  worker runs the project's **Debug** configuration instead, so a Core change built only with the default
  leaves the worker answering from stale assemblies — with no error, just the old behaviour. Pass
  `-Configuration Debug` when the next step starts a worker through `doctor.ps1 -Deep` or a Python
  `*_acceptance.py`: `doctor.ps1` builds nothing, and `bootstrap.ps1` builds `Release` only. (The PowerShell
  Godot scripts — `test-godot-determinism.ps1` and its siblings — build Debug themselves.)
- The Godot worker host is opt-in: `-WithGodot`, built in `-GodotConfiguration` (default `Debug`), and a
  failure there fails the script. Building it by default produced an artifact no worker reads, and hid
  its own failure while doing it.
- Local overrides — `STS2_GAME_ROOT`, `GODOT`, `STS2_SANDBOX_ROOT` — belong in a gitignored `.env`
  (`.env.example` is the template). Loading is fill-only: a variable already set always wins.
- `.env` is read by the PowerShell layer (`scripts/common.ps1`). The Python CLI does not read it, so
  reach the CLI through a script — `scripts/doctor.ps1` — rather than from a bare shell.
- `scripts/common.ps1` supplies the repository-local SDK: `Invoke-DivineDotnet` is the one `dotnet`
  entry point every script uses, and no command here needs an exported environment block.

## A build needs an unconfined host

MSBuild's worker nodes and the Roslyn compiler server reach each other over **named pipes**, and a file
sandbox refuses them. There, a build that crosses a `ProjectReference` fails with no error text at all —
the reference is evaluated through the `MSBuild` task, and the summary says only:

```
生成失败。
    0 个警告
    0 个错误
```

(`0 Warning(s) / 0 Error(s)` on an English SDK.) A single project survives; a project that *references*
another does not, and neither does `python -m pytest`, whose temporary directories are created with
`mode=0o700` and refused the same way. So build and test with the file sandbox off — in a DSH session,
escalate to `danger-full-access` — and `Invoke-DivineDotnet` prints that remedy when it sees a build fail
without an error.

Measured here, one `Core` change built through `Host`: **2.2–3.5 s** unconfined, against 4.7 s best case
and 20–29 s typical under a file sandbox, where the same build fails outright unless it is forced
single-node.

## Repository defects and their status

**Steam-root discovery is still narrow.** `paths._steam_roots()` derives its candidates from
`%PROGRAMFILES%`, `%PROGRAMFILES(X86)%` and `STEAM_PATH`, and does read each candidate's
`libraryfolders.vdf`; what it never does is read the registry's `SteamPath`, so a Steam installation
that is not below one of those variables is invisible. The failure says so and names `STS2_GAME_ROOT`.
Repairing discovery belongs to the single-discovery-policy work recorded as out of scope in
`.scratch/act1-combat1-scenarios/spec.md`; set `STS2_GAME_ROOT` (or put it in `.env`) here.

## Host facts that are not defects

**Godot picks the wrong .NET runtime unless it is told.** Left alone, the host rolls the worker forward
to the machine's newest runtime and Harmony reports `CoreCLR version 10.0.12 is not supported`; pinning
`DOTNET_ROLL_FORWARD=LatestPatch` instead lands on 8.x and the project assembly fails to load
(`System.Runtime, Version=9.0.0.0`). `NativeWorker` sets `DOTNET_ROOT`, `DOTNET_ROOT_X64` and `PATH` from
a repo-local `.tools\dotnet9` and pins `DOTNET_ROLL_FORWARD=Major`, which is why the install location
matters rather than an environment tweak at each call site.

**`Sts2.NativeSim.Host --server` cannot drive the simulator.** `InstallSaveMock` reaches
`Godot.OS.GetCmdlineArgs()`, which needs the Godot native runtime, so it crashes with `0xC0000005`; the
Godot worker is the real path.

Versions in play: .NET SDK 9.0.318 (repo-local), .NET runtime 9.0.20, Godot 4.5.1 mono, shipped
assembly `sts2.dll` sha256 `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`.
