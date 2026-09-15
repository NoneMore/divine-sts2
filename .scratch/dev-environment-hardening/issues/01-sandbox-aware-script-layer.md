# 01: A sandbox-aware script layer

**What to build:** `scripts/common.ps1` becomes the single place where an unusual Windows host is
adapted to, so that neither a contributor nor an agent has to re-derive the workarounds. It gains
three things: a `dotnet` entry point that keeps SDK and package state inside the repository when the
user profile is not writable and drops to a single build node when the SDK's workload-locator
directories are missing; a `.env` loader that only fills variables that are not already set; and a
download helper that falls back from `curl` to `Invoke-WebRequest` to Python `urllib` for hosts whose
proxy refuses the first two. Both installers dot-source the library, and every `dotnet` call site in
`scripts/` goes through the new entry point.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] `scripts/common.ps1` exports `DOTNET_CLI_HOME` and `NUGET_PACKAGES` into `<repo>\.tools\...`
      only when the user-profile location is not writable. The probe creates and removes its own
      scratch directory and leaves nothing behind on a host where the profile is writable.
- [x] The `dotnet` entry point appends `-m:1` only when
      `<sdk>\Sdks\Microsoft.NET.SDK.WorkloadAutoImportPropsLocator\Sdk` is missing, and prints why.
      It never adds `-p:NuGetAudit=false`: that stays an explicit, documented flag (ADR-0005).
- [x] `.env` is loaded when present, `.env.example` documents every variable it may set, and an
      already-set environment variable is never overwritten.
- [x] The download helper tries `curl` first (keeping its resumable `-C -` behaviour and `.part`
      file), then `Invoke-WebRequest`, then Python `urllib` — preferring
      `<repo>\.venv\Scripts\python.exe` and falling back to `python` on `PATH`. When every path
      fails, the message names the proxy variables that were honoured (`HTTP_PROXY`, `HTTPS_PROXY`,
      `NO_PROXY`).
- [x] `scripts/install-dotnet-9.ps1` and `scripts/install-godot-4.5.1.ps1` dot-source `common.ps1`
      and download through the helper; their install locations and Godot archive quarantine
      behaviour are unchanged.
- [x] All thirteen `dotnet` invocations across `scripts/` (build, run, and the two in
      `test-public-tree.ps1`) go through the entry point.
- [x] On this host, `pwsh scripts/test-public-tree.ps1` completes both builds with no manually
      exported `DOTNET_CLI_HOME`/`NUGET_PACKAGES` — the script previously died at its first build with
      `Access to the path '<profile>\.dotnet' is denied`.

## Comments

**2026-09-15 — implemented.**

- `Import-DivineDotEnv` runs at the end of `common.ps1`, so every script that dot-sources the library
  inherits it. Repository-relative values (`DOTNET_CLI_HOME=.\.tools\dotnet-home` as `.env.example`
  shows) resolve against the repository rather than the caller's working directory, and a variable
  that is already set is left alone.
- `Initialize-DivineDotnetEnvironment` and `Test-DivinePathWritable` probe rather than query
  permissions. Measured on this host: `USERPROFILE` (`E:\Home`) is refused, the probe leaves no
  `.divine-write-probe-*` directory behind, and `DOTNET_CLI_HOME`/`NUGET_PACKAGES` then point under
  `.tools`.
- `Test-DivineWorkloadLocatorMissing` caches its answer per process and is consulted only for
  `build`/`restore`/`msbuild`. **`run` is deliberately excluded**: `dotnet run` builds implicitly
  through a path that ignores `-m:1` and still fails with MSB4276, which is why `benchmark-rng.ps1`
  now builds first and then runs with `--no-build`, like `run-feasibility.ps1` already did.
- Two PowerShell argument rules cost real debugging and are documented in the helper: a bare
  `-p:Name=Value` is split into two arguments and a bare `--` is eaten, so callers quote both
  (`"-p:GameDataDir=$gameData"`, `'--'`); and the helper must stay a *simple* function, because a
  `[Parameter()]` attribute makes it an advanced function whose common parameters collide with
  dotnet's switches (`-p:` was rejected as an ambiguous `-ProgressAction`/`-PipelineVariable`).
- `Save-DivineDownload` was exercised end to end: with `HTTPS_PROXY=http://127.0.0.1:12305`, `curl`
  failed with `(35) schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS` and the file
  still arrived (76 676 bytes), through a later transport in the chain.
- Added `scripts/doctor.ps1` as the fast-path entry for `doctor`: `.env` is applied by the PowerShell
  layer, and the Python CLI does not read it, so this is how a repository-local override reaches the
  CLI without being exported by hand.
- `build-persistent-server.ps1` gained `-DisableNuGetAudit` (adds `-p:NuGetAudit=false`). A
  `[string[]]` passthrough was rejected: `pwsh -File` re-parses arguments, so a value beginning with
  `-` cannot survive it. With the switch, `Host` and `GodotHost` both build here (0 warnings, 0
  errors); without it, `GodotHost` still fails on `NU1900`, which is the intended explicitness
  (ADR-0005).
- Not re-run: a fresh toolchain install. Both installers were already satisfied on this host, so
  their download path is verified by inspection plus the shared helper's end-to-end test above.
