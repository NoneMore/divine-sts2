# Sandboxed-host hardening

## Problem Statement

`docs/agents/dev-environment.md` records thirteen symptoms hit on a Windows host whose file sandbox
permits writes inside the repository only, whose toolchain was absent, and whose proxy refuses
`curl`/`Invoke-WebRequest` downloads. It states its own limitation: "None of it is a repo defect
unless marked as such." The result is that every agent and contributor on such a host re-derives the
same workarounds from prose — and two of the recorded items *are* repository defects:

- `scripts/test-public-tree.ps1` fails on a pristine `main`. Its `git grep` for machine-specific
  paths matches `Directory.Build.props`, a smoke-test project file, and — after the B1 finding was
  written up — `docs/architecture-review.md` itself, so the review document now trips the gate it
  documents. CI runs this script (`.github/workflows/ci.yml:33-35`), so CI is red.
- Game-root discovery reads Steam libraries only under `%PROGRAMFILES%`, `%PROGRAMFILES(X86)%` and
  `STEAM_PATH` (`python/sts2_native_sim/paths.py:22-44`, duplicated in `scripts/common.ps1:32-43`).
  Nothing consults the registry's `SteamPath`, so an install whose Steam directory is not at the
  environment variable's path is invisible and the failure does not say why. Repairing discovery is
  deliberately out of scope (see below); the failure message is not.

The document also misdescribes two mechanisms: `_steam_roots()` *does* read `libraryfolders.vdf`
(the real gap is the missing registry lookup), and `NativeWorker` already pins
`DOTNET_ROLL_FORWARD=Major` (`python/sts2_native_sim/client.py:113`), unlike the caller-side env
block the doc presents as the fix.

## Solution

Move adaptation out of prose and into the repository's shared entry points, conditioned on a probe so
that a standard host behaves exactly as before:

- `scripts/common.ps1` becomes the one script-layer choke point: a single `dotnet` entry point, a
  fill-only `.env` loader, and a download helper with a fallback chain. Both installers use it.
- `NativeWorker` redirects the Godot worker's user-facing directories into the repository only when
  the real ones are not writable.
- The public-tree gate splits its two scans so that documentation may describe a leak; the two
  hardcoded game paths disappear and a missing `STS2_GAME_ROOT` becomes an explicit error.
- `docs/agents/dev-environment.md` becomes a short, present-tense guide to commands and causes rather
  than a session log.

## Implementation Decisions

- **Adaptation is conditional and shared** (ADR-0005): probe the condition, change nothing when it is
  absent, and put the change in a shared entry point — never in global build configuration. The
  sibling-`.tools` fallback in `paths.find_dotnet()`, `paths.find_godot()` and `client.py` is deleted:
  a borrowed toolchain is precisely the thing that disappears mid-session.
- **`NuGetAudit` stays explicit.** Disabling the vulnerability audit weakens every build, and probing
  reachability of `nuget.org` is slow and unreliable, so `-p:NuGetAudit=false` remains a documented
  flag for a documented situation rather than a detection.
- **`-m:1` is applied only when the SDK cannot resolve its workload-locator directories.** A
  parallel-build fix that does not also slow every other host is still open (see below).
- **The gate's two scans get different scopes** (ADR-0004): machine paths outside markdown, secret
  tokens everywhere.
- **`Directory.Build.props` derives `GameDataDir` from `$(STS2_GAME_ROOT)` only.** Game-dependent
  projects declare `RequiresGameData` and fail with a message naming the variable.
- **Documentation may not name a machine path.** The rule that caused the gate to fail also binds the
  documents written here: cite "a secondary Steam library", never a drive-qualified path.

## Testing Decisions

- `pwsh scripts/test-public-tree.ps1` exits 0 on this tree with no manually exported environment
  variables — it is the gate, the CI step, and the regression test for both scans.
- `pwsh scripts/build-persistent-server.ps1 -Configuration Release` builds `Host` and `GodotHost`
  through the new entry point.
- `python -m pytest tests -q` passes 24 tests. On this host it must run with a wider file permission:
  pytest creates every temporary directory with `mode=0o700` (`_pytest/tmpdir.py:139,158`,
  `_pytest/pathlib.py:232`) and the sandbox denies access to directories created that way, even to
  the process that created them. An in-repo `--basetemp` does not help; this was measured.
- `python -m sts2_native_sim.cli doctor --deep` passes with only `.env` (gitignored) supplying
  `STS2_GAME_ROOT`/`GODOT`.
- Offline Python tests cover the new behaviour directly where it is pure: the user-directory probe,
  the `.env` loader's fill-only rule, and the discovery failure message.

## Out of Scope

- **Repairing Steam-root discovery.** `.scratch/act1-combat1-scenarios/spec.md:148` already parks it
  with "the existing single-discovery-policy work", which `docs/architecture-review.md:683` describes
  as making `paths.py` the single discovery policy with the PowerShell layer as a thin caller.
  Patching a registry lookup into the two current implementations would be rework for that effort.
- **Making pytest work inside the restricted sandbox.** Monkeypatching pytest's temporary-directory
  mode to accommodate one sandbox makes every other environment carry the workaround.
- **`Sts2.NativeSim.Host --server`.** It needs the Godot native runtime by design; the Godot worker
  remains the real path.

## Known issues not fixed here

- **Automated parallel builds.** MSB4276 is absorbed by `-m:1`, but the underlying SDK defect (missing
  workload-locator SDK directories) is unrepaired, and a single-node build is a slowdown imposed on
  every build on an affected host. A real fix — repairing or reinstalling the SDK, or a targeted
  workaround that keeps node reuse — is still open.
- **Steam-root discovery** (above), including the duplicated implementation in `scripts/common.ps1`.
- **pytest's `0o700` temporary directories** (above).
- **`dotnet --info` raises `Win32Exception (5)`** because the sandbox denies `OpenProcess` on the
  parent process. Noise only.

## Tickets

| # | Ticket | Blocked by |
|---|---|---|
| 01 | `issues/01-sandbox-aware-script-layer.md` — `common.ps1` entry point, `.env` loader, download fallback | — |
| 02 | `issues/02-sandbox-aware-native-worker.md` — user-directory redirect, single-repository toolchain, actionable discovery failure | 01 |
| 03 | `issues/03-public-tree-gate-and-hardcoded-defaults.md` — gate scan split, `GameDataDir` defaults | 01 |
| 04 | `issues/04-rewrite-dev-environment-doc.md` — rewrite the document and its referrers | 01, 02, 03 |

## Further Notes

The document this work replaces was written from one machine's session. Anything it recorded that is
still true belongs in one of three places: a probe in `scripts/common.ps1` or `paths.py`, a test under
`tests/`, or a short entry in `docs/agents/dev-environment.md`. An entry that only narrates what once
happened should not survive the rewrite.
