# Contributing

`divine-sts2` has one Windows development workflow for people, automation, and coding agents. The
commands below are the source of truth; do not introduce a second environment for a particular runner.

## Host requirements

- Windows 10 or 11 x64.
- PowerShell 7 (`pwsh`).
- `uv` on `PATH`. `uv` installs the repository's Python 3.12 environment from `.python-version`.
- A legally installed Steam copy of Slay the Spire 2 for native builds and integration checks.

The setup command reuses compatible system installations of the pinned .NET SDK and Godot when they
exist. Missing tools are downloaded under `.tools/` as a disposable fallback. Package-manager caches
stay in their normal user-level locations; they are not redirected into the checkout.

This repository expects an ordinary Windows development host. MSBuild, Roslyn, Godot, pytest, and the
game bridge may create child processes, temporary files, sockets, and named pipes. Sandboxed runners
must permit those normal host capabilities. The project does not maintain alternative commands or
degraded build settings for a sandbox.

## First setup

```powershell
git clone https://github.com/NoneMore/divine-sts2.git
cd divine-sts2
pwsh ./dev.ps1 setup
```

`setup` performs the complete native setup: Python dependency sync, verification (or fallback
installation) of the exact .NET SDK from `global.json` and Godot 4.5.1 .NET, the Release host, the
Debug Godot worker, and a deep doctor run.

Local overrides belong in the gitignored `.env`; copy `.env.example` only when auto-discovery is not
enough.

## Everyday commands

```powershell
pwsh ./dev.ps1 sync       # reproduce the locked Python development environment
pwsh ./dev.ps1 check      # the same source gate CI runs
pwsh ./dev.ps1 test       # Python tests
pwsh ./dev.ps1 build      # rebuild Release host + Debug Godot worker
pwsh ./dev.ps1 doctor     # validate the local game/toolchain and start a worker
```

Run project commands through the locked environment without activating a virtualenv:

```powershell
uv run --frozen divine-sts2 scenario --character IRONCLAD --seed A1B2C3D4E5 --workers 1 --output-dir artifacts/scenarios/dev
uv run --frozen python -m tests.acceptance.certify_full_app_reuse
```

## CI parity

GitHub Actions installs `uv` and the SDK declared by `global.json`, then runs:

```powershell
pwsh ./dev.ps1 sync
pwsh ./dev.ps1 check
```

CI does not run game-dependent integration checks because the shipped game is not present there. The
`check` command itself is identical locally and in CI.

## Pull requests

Before opening a pull request, run `pwsh ./dev.ps1 check`. For changes that touch native game
integration, also run `pwsh ./dev.ps1 build` and `pwsh ./dev.ps1 doctor`.

The public repository is source-first. Never commit game binaries/resources, local saves, private
session data, unreviewed datasets, model checkpoints without their required documentation, or generated
research output.

## Tool ownership

The repository owns version declarations and orchestration, not a private developer machine. `uv`,
`global.json`, and the Godot version contract decide what is acceptable; compatible system tools are
preferred. `.tools/` may be deleted at any time and recreated by `pwsh ./dev.ps1 setup` when a fallback
is needed. Runtime call sites must use shared discovery rather than depend directly on a `.tools/...`
path; only the discovery/fallback layer knows that location.
