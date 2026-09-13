# Repository instructions

## Project boundaries

This repository provides build-pinned, deterministic, headless research tooling for Slay the Spire 2. Keep mechanical fidelity, execution breadth, policy quality, and advisor/product capability as separate claims. Evidence for one axis does not establish another.
The Slay the Spire 2 source is located at `E:\Home\projects\sts2-src`.

The public repository is source-first. Do not add game binaries or resources, local saves, private session data, community runs, training shards, datasets without documented redistribution permission, model checkpoints without model cards, or generated research output.

Execute shipped native game mechanics rather than reimplementing individual cards in NativeSim. Suppress presentation only, keep suppression seams explicit, fail loudly on unsupported states or build mismatches, and never manipulate the visible game or desktop during headless research.

## Evidence and maintained documentation

Use evidence in this order when sources disagree:

1. Build-pinned machine-readable artifacts and exact replay outputs.
2. Tests and benchmarks reproducible from the current tree.
3. `docs/project-status-and-review-guide.md` and focused implementation reports.
4. `docs/architectural-guardrails.md` for durable research and architecture invariants.
5. Roadmaps, proposals, estimates, and historical discussion.

Read `docs/project-status-and-review-guide.md` before reviewing project capability, changing milestone status, or making architectural claims. Read `docs/architectural-guardrails.md` before changing search, training, reward, value, promotion, or simulation architecture. `docs/README.md` indexes the documentation set and states which document owns which claim; place new durable knowledge in that canonical home instead of creating a parallel account.

Do not copy volatile status, benchmark numbers, build identifiers, or file inventories into this file. Update the owning maintained document whenever a milestone, architectural decision, evidence boundary, or externally stated capability changes materially. Record large architectural decisions in the relevant local design or status document; opening an external issue is not required.

Treat shadow-simulator output as explicitly non-authoritative. Keep simulator certification independent from model promotion, and do not claim certification beyond exact real-game differential checkpoints.

## Implementation expectations

Preserve deterministic and fail-loud behavior at advertised boundaries. Tests requiring the game must fail closed when the installed build is unsupported.

For policy or model work:

- Offline agreement is necessary evidence, not a promotion result.
- Promotion requires reproducible native evaluation on identical or fresh declared seed sets, with error or cap rates, per-character results where relevant, and the exact game build.
- Preserve rejected experiments and their reasons in an appropriate local document or small manifest without committing prohibited generated artifacts.

Keep changes scoped to the requested outcome. When a task requires a large architectural choice, implement it when authorized by the task and document the decision and consequences locally.

## Validation

Run validation proportional to the change and report the commands and results. Start with the narrowest relevant tests.

For broad changes or work intended to be pull-request ready, run:

```powershell
python -m compileall -q python tests
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --ignore-glob='pytest-cache-files-*'
pwsh scripts/test-public-tree.ps1
```

Build affected C# projects when C# code or shared build configuration changes. Run game-dependent, differential, rollout, or benchmark checks only when relevant and when the required local game installation and pinned build are available; otherwise report that limitation rather than weakening or bypassing the check.

In a sandboxed session that may only write inside the checkout, keep engine and .NET CLI state inside it: Godot needs a writable `user://` directory (without one it aborts before serving a request), the .NET CLI needs a writable home, and MSBuild needs in-process project-reference builds. `.env` carries those redirects and switches (see `.env.example` for the keys and why they exist). They reach a process only through the loaders — the Python entry points and the PowerShell scripts that dot-source `scripts/common.ps1` — so prefer `pwsh scripts/*.ps1` over bare `dotnet`/`godot` invocations. Keep the pytest cache switches shown above on every invocation: a confined session cannot complete pytest's atomic cache write, and the unreadable `pytest-cache-files-*` directories it leaves behind then break later collection and even `git status`.

The `dotnet` on `PATH` is not the pinned toolchain: the repository pins the SDK through `global.json` and `.tools\dotnet9`, so a bare `dotnet` can resolve to a machine SDK the pin refuses and fail before any build starts — use the executable the loaders select. Installing a matching SDK or engine globally does not remove the confinement problem either, because confinement constrains where a process may write, not where its executable lives: a globally installed engine still needs the `.env` redirects to obtain a writable `user://` directory.

The `python` on `PATH` is not the repository interpreter either. The `sts2_native_sim` package lives under `python/` and is installed editable into this checkout's `.venv` (the README setup, equivalently `scripts/bootstrap.ps1` run from the activated environment), so an interpreter that is not that venv cannot import the package at all. Run `pytest` and every other command that imports the package through `.venv\Scripts\python.exe`. Do not trust a passing bare `python -m pytest -q`: under the interpreter on `PATH` it can still collect and pass because the no-argument collection path happens to put `python/` on `sys.path`, while the same command with an explicit test path or directory fails to import the package — a false green that hides a missing environment instead of reporting it. The `python/*.py` acceptance and benchmark entry points add `python/` to `sys.path` themselves and therefore run under either interpreter.

A task is complete when the requested change is present, relevant validation passes, maintained status or design documentation reflects any material decision or claim change, and no prohibited local or generated artifacts have been introduced.
