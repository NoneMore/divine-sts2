# divine-sts2

[![.NET 9](https://img.shields.io/badge/.NET-9.0-512BD4?logo=dotnet&logoColor=white)](https://dotnet.microsoft.com/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Throughput](https://img.shields.io/badge/Throughput-1%2C514%2B%20dec%2Fsec-success)](#benchmarks)
[![Stability](https://img.shields.io/badge/Stability-100%25%20Zero--Crash-brightgreen)](#benchmarks)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

High-throughput, deterministic, headless reinforcement learning and MCTS execution environment for **Slay the Spire 2**.

Executes game mechanics directly from your local Steam installation inside isolated, presentation-suppressed .NET 9 workers. Contains zero copyrighted assets, game binaries, or proprietary art.

Every run uses one progression-complete baseline. Character, seed, and Ascension remain configurable,
while profile progression never narrows cards, relics, potions, events, Acts, Ancients, or encounter
ordering. The simulator models those effects directly; each isolated full-app sandbox materializes and
validates deterministic progress through the shipped game's APIs. It never touches the player's real
profile or synthesizes achievements, career totals, or multiplayer session state. A ready full-app
`hello` reports `progression_policy`, the canonical `profile_fingerprint`, PID, bound port, and game
build; `start_run` is unavailable while that baseline is initializing.

---

## Benchmarks

Continuous 100-second sustained stress benchmark across 20 isolated native workers:

| Metric | Measured Value |
| :--- | :--- |
| **Sustained Throughput** | **1,514.8 decisions / sec** |
| **Combat Completion Rate** | **3,140.9 combats / min** (5,245 total) |
| **Native Decisions Evaluated** | **151,776 decisions** |
| **Unmanaged Crashes / Aborts** | **0 (100% Stability)** |
| **Worker Memory Footprint** | **~221 MB / worker** (~4.4 GB total for 20 workers) |

---

## Requirements

* **OS**: Windows 10 / 11 (x64)
* **Game**: Legally installed copy of Slay the Spire 2 via Steam
* **Shell**: PowerShell 7 (`pwsh`)
* **Python environment manager**: [`uv`](https://docs.astral.sh/uv/)

`uv` installs the repository's Python 3.12 development environment from `.python-version`. For .NET
and Godot, the project first reuses a compatible system installation. `setup` downloads an exact
checkout-local fallback under `.tools/` only when the required tool is missing.

---

## Quickstart

```powershell
git clone https://github.com/NoneMore/divine-sts2.git
cd divine-sts2
pwsh ./dev.ps1 setup
```

That is the complete native setup: locked Python dependencies, verified .NET and Godot tools, Release
host, Debug Godot worker, and a deep environment check. Existing compatible system tools are reused.

For everyday development:

```powershell
pwsh ./dev.ps1 check
```

`check` is the same source gate GitHub Actions runs. Human contributors, automation, and coding agents
use the same commands; there is no alternate sandbox-specific development mode. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the development contract.

---

## Usage

### 1. Diagnostics & Environment Verification

Verify assembly compatibility, SHA-256 signatures, and worker startup:

```powershell
pwsh ./dev.ps1 doctor -Json
```

### 2. High-Throughput 20-Worker Benchmark

Run the sustained multi-worker soak benchmark:

```powershell
uv run --frozen python python/tools/soak_test_20_workers.py
```

### 3. Parallel Rollout Farm

Generate parallel game trajectories across headless workers:

```powershell
uv run --frozen python python/tools/native_rollout_farm.py --workers 6 --episodes 100 --ascension 1 --summary-only
```

### 4. Generated Scenario Corpus

Record reproducible act-1 opening scenarios into deterministic corpus shards:

```powershell
uv run --frozen divine-sts2 scenario --character IRONCLAD --seed A1B2C3D4E5 --workers 1 --output-dir artifacts/scenarios/quickstart
```

### 5. Certify full-app process reuse

Build the native hosts, then run the dedicated shipped-game gate from a checkout with
`STS2_GAME_ROOT` configured or discoverable:

```powershell
pwsh ./dev.ps1 build
uv run --frozen python -m tests.acceptance.certify_full_app_reuse
```

It runs sixteen independent fresh menu starts, then seventeen entries in one reusable process. The
last entry repeats the first scenario. Complete evidence goes to the ignored
`artifacts/reuse-certification/report.json`; a passing gate writes the compact
`certifications/full-app-reuse.json` for commit. Ordinary parity runs never write that certificate.

---

## Gymnasium Vector Environment

Standard vectorized RL environment interface with action masking and state restore handles:

```python
from sts2_native_sim import NativeWorkerPool, extract_agent_observation
from sts2_native_gym import Sts2NativeVectorEnv

with Sts2NativeVectorEnv(workers=4, ascension=1) as env:
    obs, info = env.reset(seed=42)
    for _ in range(100):
        actions = [legals[0] for legals in info["legal_action_ids"]]
        obs, rewards, terminations, truncations, info = env.step(actions)
        if any(terminations):
            break
```

---

## Configuration

The runtime auto-detects standard Steam installations, including Steam's Windows registry location and
configured library folders. For a custom install, define `STS2_GAME_ROOT` in the gitignored `.env`:

```ini
STS2_GAME_ROOT=D:\SteamLibrary\steamapps\common\Slay the Spire 2
```

Environment discovery is implemented once in Python and is used by both Python and PowerShell entry
points. The repository-local `.env` has fill-only semantics: an environment variable already set by
the caller always wins.

Full-app sandboxes are prepared on the game install's own volume, because each sandbox hard-links the
install instead of copying it and a hard link cannot cross volumes. Set `STS2_SANDBOX_ROOT` only to
place them somewhere else on that same volume:

```ini
STS2_SANDBOX_ROOT=D:\SteamLibrary\steamapps\common\divine-sts2\full-app-sandboxes
```

Tool and package-manager caches use their normal user-level locations. The checkout-local `.tools/`
directory is only a disposable fallback for required runtime tools that are not already available on
the host; runtime code does not assume tools live there.

---

## Troubleshooting

| Error | Root Cause | Resolution |
| :--- | :--- | :--- |
| `uv was not found on PATH` | Missing Python environment manager | Install `uv`, then rerun `pwsh ./dev.ps1 setup`. |
| `Slay the Spire 2 was not found` | Steam install could not be discovered | Set `STS2_GAME_ROOT` in `.env`. |
| `Unsupported game build` | Game DLL/PCK hash mismatch | Verify the game installation matches the supported build. |
| Required `.NET SDK` was not found | Pinned SDK is missing | Run `pwsh ./dev.ps1 setup`. |
| `worker_poisoned` | Unmanaged task abort | Pool auto-recycles worker; restart the farm if persistent. |

---

## Architecture and internal tools

See [`docs/architecture.md`](docs/architecture.md) for the implemented module boundaries and
accepted ADRs. [`docs/tooling.md`](docs/tooling.md) describes maintained internal tools,
experiments, the AutoTrace smoke workflow, and replacements for removed edge utilities.

---

## Legal

`divine-sts2` is an independent research project and is not affiliated with or endorsed by Mega Crit. Users must provide their own legally obtained copy of Slay the Spire 2. Distributed under the [MIT License](LICENSE).
