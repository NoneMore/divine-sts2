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

Read `docs/project-status-and-review-guide.md` before reviewing project capability, changing milestone status, or making architectural claims. Read `docs/architectural-guardrails.md` before changing search, training, reward, value, promotion, or simulation architecture.

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
python -m pytest -q
pwsh scripts/test-public-tree.ps1
```

Build affected C# projects when C# code or shared build configuration changes. Run game-dependent, differential, rollout, or benchmark checks only when relevant and when the required local game installation and pinned build are available; otherwise report that limitation rather than weakening or bypassing the check.

A task is complete when the requested change is present, relevant validation passes, maintained status or design documentation reflects any material decision or claim change, and no prohibited local or generated artifacts have been introduced.
