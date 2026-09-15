# Dev environment: sandboxed Windows work on this repo

Notes from a session implementing `.scratch/act1-combat1-scenarios` tickets on a Windows host where:

- the file sandbox permits writes **inside the repository only** — anything under the user profile
  (`%APPDATA%`, `%TEMP%`, `%USERPROFILE%\.dotnet`) or another drive is denied;
- the machine had no repo-local toolchain (`.tools/dotnet9`, `.tools/godot-4.5.1-mono` were absent);
- outbound HTTPS goes through a local proxy (`HTTP_PROXY` / `HTTPS_PROXY`).

Everything below was hit for real in that session. Each entry is symptom → cause → what worked.
None of it is a repo defect unless marked as such.

## Build

### 1. `dotnet build` reports "0 errors" and still fails

**Symptom.** `dotnet build <project>` prints a summary of `0 个警告 / 0 个错误` and exits 1, with no
error text. Only `-v diag` reveals it:

```
error MSB4276: The default SDK resolver failed to resolve SDK
"Microsoft.NET.SDK.WorkloadAutoImportPropsLocator" because directory
"<sdk>\Sdks\Microsoft.NET.SDK.WorkloadAutoImportPropsLocator\Sdk" does not exist.
```

**Cause.** This machine's .NET 9 SDK is missing the two workload-locator SDK directories
(`Microsoft.NET.SDK.WorkloadAutoImportPropsLocator`, `Microsoft.NET.SDK.WorkloadManifestTargetsLocator`).
Building one project directly survives it, because `Microsoft.DotNet.MSBuildWorkloadSdkResolver` then
resolves the locator to nothing and the failure is absorbed. A project that *references* another
project evaluates the reference through the `MSBuild` task in `_GetProjectReferenceTargetFrameworkProperties`;
inside that child evaluation the same failure is fatal. So a leaf project builds and its consumer
does not.

**What worked.** Build single-node: `dotnet build <project> -m:1`. Verified by narrowing: an empty
probe project builds → `Sts2.NativeSim.Protocol` builds → a probe referencing it builds → a probe
referencing `Core` fails → adding `-m:1` succeeds. A freshly downloaded 9.0.318 SDK has the same gap,
so this is the machine, not the download.

### 2. NuGet vulnerability audit fails the build

**Symptom.** `error NU1900: 获取包漏洞数据时出错: 无法加载源 https://api.nuget.org/v3/index.json` — restore
cannot reach nuget.org through the proxy, and `Directory.Build.props` sets
`TreatWarningsAsErrors`, so the audit warning becomes an error. `--no-restore` does not help: the
warning is replayed from the cached restore result.

**What worked.** `-p:NuGetAudit=false` (packages themselves are already in the local package cache).

### 3. `dotnet` cannot configure itself

**Symptom.** `System.UnauthorizedAccessException: Access to the path '<profile>\.dotnet' is denied`
before any build output appears.

**Cause.** First-run configuration writes under `$HOME`, which the sandbox refuses.

**What worked.** The overrides `.env.example` already documents: `DOTNET_CLI_HOME=<repo>\.tools\dotnet-home`
and `NUGET_PACKAGES=<repo>\.tools\nuget-packages`. Worth reading `.env.example` before inventing a fix.

### 4. `dotnet --info` throws

`System.ComponentModel.Win32Exception (5): 拒绝访问` from `ProcessExtensions.GetParentProcessId` —
the sandbox denies `OpenProcess` on the parent. Noise; it does not affect building or running.

## Toolchain installs and downloads

### 5. Pure PowerShell downloads fail behind a local proxy

**Symptom.** `curl` fails with `(35) schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`;
`Invoke-WebRequest` fails with `Authentication failed, see inner exception`. The proxy itself is
reachable (`HTTP/1.1 200 Connection established`). Therefore `scripts/install-godot-4.5.1.ps1` and
`scripts/install-dotnet-9.ps1` — both curl/IWR-based — cannot complete on this machine.

**What worked.** Download with Python (`urllib.request` honours `HTTP_PROXY`/`HTTPS_PROXY`) from the
repo's virtualenv, then unpack with `zipfile`. Godot 4.5.1 mono (~100 MB) and the .NET 9 SDK
(~300 MB) both came down this way. Extract Godot to `.tools/godot-4.5.1-mono/` so
`paths.find_godot()` finds it, and .NET to `.tools/dotnet9/` so `paths.find_dotnet()` finds it —
`client.py` then sets `DOTNET_ROOT` for the native worker automatically.

### 6. Toolchains that are not in the repo, and toolchains that vanish

`.tools/` held only `dotnet-home` and `nuget-packages`. A sibling checkout's `.tools/` (with `.NET 9`
and Godot) and a Godot zip elsewhere on the machine were present at the start of the session and
**disappeared mid-session** (disk reclaim), so borrowing them is not a durable plan: install into
this repo's `.tools/` instead. `.tools/` is gitignored, so none of it can be committed by accident.

## Running the native simulator

### 7. The pure .NET host cannot drive the simulator

`Sts2.NativeSim.Host --server` crashes with `0xC0000005`: `InstallSaveMock` reaches
`Godot.OS.GetCmdlineArgs()`, which needs the Godot native runtime. `--server` is therefore not a
substitute for the Godot worker; real checks need Godot 4.5.1 mono and `python/sts2_native_sim/client.py`'s
`NativeWorker`.

### 8. Godot dies headless before it starts

**Symptom.** `CrashHandlerException: Program crashed with signal 11`, preceded by
`ERROR: Failed to open 'user://logs/godot<timestamp>.log'`.

**Cause.** Godot writes its user data under `%APPDATA%`, which the sandbox refuses.

**What worked.** Point the whole user-facing environment into the repo before launching:

```powershell
$env:APPDATA = "$repo\.tools\tmp\appdata"
$env:LOCALAPPDATA = "$repo\.tools\tmp\appdata"
$env:TEMP = "$repo\.tools\tmp\temp"; $env:TMP = $env:TEMP
```

### 9. Godot picks the wrong .NET runtime

**Symptom A.** `System.PlatformNotSupportedException: CoreCLR version 10.0.12 is not supported` from
Harmony — the host rolled forward to the machine's newest runtime instead of 9.x.

**Symptom B.** Pinning `DOTNET_ROLL_FORWARD=LatestPatch` instead lands on the 8.x runtime and the
project assembly fails to load: `Could not load file or assembly 'System.Runtime, Version=9.0.0.0'`.

**What worked.** A repo-local .NET 9 under `.tools/dotnet9` (see 5). `client.py` then sets
`DOTNET_ROOT`, `DOTNET_ROOT_X64` and `PATH` to it for every worker, which is why the install location
matters rather than the solution being an env tweak at the call site.

## Tests

### 10. `pytest` cannot create its temporary directory

**Symptom.** 15 tests fail at setup with
`PermissionError: [WinError 5] ... '<profile>\AppData\Local\Temp\dsh-*\pytest-of-<user>'`. Redirecting
`--basetemp` into the repo still failed on the same class of denial, and pytest's session cleanup hit
it again over a `\\?\`-prefixed path.

**What worked.** Running the suite with the wider file permission the harness offers
(`danger-full-access`), after which all 24 tests passed. Inside the restricted sandbox, tests that
only touch files they create under the repo are fine; the failures were all `tmp_path`.

### 11. `python/act_variant_acceptance.py` needs the env block

Any script that starts a native worker needs `GODOT`, `STS2_GAME_ROOT` and the redirected user
directories from 8. `paths.find_godot()` finds `.tools/godot-4.5.1-mono` on its own once installed;
`STS2_GAME_ROOT` is still required on this machine (see 12).

## Pre-existing repo findings this session re-confirmed

### 12. Steam-root discovery cannot see the real library

`paths._steam_roots()` builds candidates from `%PROGRAMFILES(X86)%` / `%PROGRAMFILES%` / `STEAM_PATH`.
On this machine `%PROGRAMFILES(X86)%` is `C:\Program Files(X86)` — without the space — so the Steam
install and its `libraryfolders.vdf` are never read, and the game (in a secondary library) is not
found. `STS2_GAME_ROOT` is the workaround. Repairing discovery is already recorded as out of scope in
the feature spec.

### 13. The public-tree gate fails on the tree it gates

`scripts/test-public-tree.ps1` greps tracked files for machine-specific paths and throws on a match.
It already matched `Directory.Build.props` and a smoke test `.csproj` before any change in this
session, as `docs/architecture-review.md` (B1) records. Nothing added during this session introduced
a new instance: cite the install generically ("a secondary Steam library"), never a drive-qualified
path.

## Verified command set

```powershell
# 1. Build (both flags are machine workarounds, see 1 and 2)
$env:DOTNET_CLI_HOME = "<repo>\.tools\dotnet-home"
$env:NUGET_PACKAGES = "<repo>\.tools\nuget-packages"
<repo>\.tools\dotnet9\dotnet.exe build src\Sts2.NativeSim.GodotHost\Sts2.NativeSim.GodotHost.csproj `
    -c Debug -m:1 -p:NuGetAudit=false

# 2. Native acceptance against the shipped game (see 8 and 9)
$env:GODOT = "<repo>\.tools\godot-4.5.1-mono\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_mono_win64_console.exe"
$env:STS2_GAME_ROOT = "<installed game root>"
$env:APPDATA = "<repo>\.tools\tmp\appdata"; $env:LOCALAPPDATA = $env:APPDATA
$env:TEMP = "<repo>\.tools\tmp\temp"; $env:TMP = $env:TEMP
.venv\Scripts\python.exe python\act_variant_acceptance.py

# 3. Offline tests (see 10: needs the wider file permission in a sandboxed session)
.venv\Scripts\python.exe -m pytest tests -q
```

Versions in play: .NET SDK 9.0.318 (repo-local), .NET runtime 9.0.20, Godot 4.5.1 mono, shipped
assembly `sts2.dll` sha256 `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`.
