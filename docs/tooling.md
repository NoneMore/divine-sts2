# Tool support and disposition

The detailed consumer evidence is retained in the
[supported-surface audit](../.scratch/module-decoupling/supported-surfaces-audit.md). This page is
the current guide to what each support area means and where to start.

## Maintained and internal tools

Installed commands and the two compatibility launchers documented in the README are supported
interfaces. `python/tools/` contains maintained internal generation, diagnosis, benchmark, trace,
and training workflows; their command lines are not compatibility promises. They depend on
`sts2_native_sim`, never the reverse. Representative entry points are:

- `latency_benchmark.py`, for separated resident, reset, restore, search, and protocol timings;
- `native_rollout_farm.py` and `soak_test_20_workers.py`, behind the documented compatibility
  launchers;
- `differential_replay.py`, `trace_inventory.py`, and `schedule_autotrace_campaign.py`, for exact
  shipped-game trace capture and replay;
- the native-value tools, for provenance-gated corpus, scoring, evaluation, and tuning workflows.

The maintained C# `AutoTraceDriver` is listed in `Sts2.NativeSim.sln`. It is an internal opt-in mod
that drives bounded shipped-game combats for `TraceExporter`; it is not a simulator library.
`scripts/run-isolated-autotrace.ps1` is its discoverable build, packaging, isolated-launch, and
exact-replay smoke entry:

```powershell
pwsh scripts/run-isolated-autotrace.ps1 -Seed A1B2C3D4E5 -CombatCount 1
```

That smoke requires a legally installed shipped game and creates an isolated full-app sandbox.
Automated full-app sandboxes force all four game volume settings to zero, so acceptance and AutoTrace
runs do not emit music, effects, or ambience through the host audio device.

## Experiments

`python/experiments/` contains research programs and archived learned-policy work. They have no
compatibility promise and may require private corpora, model checkpoints, or the `train` optional
dependency. Some preserve approaches whose original neural stack was deleted; those files are
research history and are not advertised as runnable. Experiments may consume supported modules and
internal artifacts, but supported code does not import them.

## Removed edges and replacements

- `tests/Sts2.NativeSim.TraceExporterSmoke` was only a reflection dump with no assertion or exit
  contract. The `--trace-exporter-smoke` host modes remain the focused TraceExporter smoke, and the
  AutoTrace script above covers the end-to-end full-app path.
- `tools/Sts2.NativeSim.ApiProbe` had no consumer or simulator assertion. Decompiled sibling source
  and ordinary assembly inspection provide its generic reflection capability when needed.
- `python/benchmark.py` duplicated restore-plus-step timing. `python/tools/latency_benchmark.py`
  reports that boundary explicitly, while `comprehensive_benchmark.py` owns the combined report.
- `examples/02_mcts_search.py` called a nonexistent search signature. The maintained
  `NativeSearchCoordinator` behavior is exercised by
  `tests/acceptance/search_coordinator_acceptance.py`; no broken public example replaces it.
