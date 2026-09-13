# E5 differential run cost and full-application process reuse evaluation

> **Role / status:** Dated evaluation report (2026-09-13). It records the measured cost model of the E5
> authority-gate runner, a concurrency calibration on one developer machine, the defects and the one
> corrected claim found while measuring, and a **source-level** feasibility assessment of serving more
> than one run start from a single shipped-application process. It certifies nothing, changes no runner
> behaviour, and does not authorize a bridge change: the reuse option stays unproven until an in-process
> equivalence check runs.

## 1. Question

`docs/first-combat-scene-generation-plan.md` E5 requires both manifests to be re-run on the fixed
comparator (39 targeted entries, 100 breadth entries). At the tested default of two workers that is
roughly 26 minutes of wall time. The decision-relevant question is therefore: where does that time go,
what can be removed without weakening an evidence claim, and is the fixed per-entry cost a property of
the shipped application or of the bridge?

Everything below was measured on one machine: AMD Ryzen 7 3700X (8 cores / 16 threads), 32 GB RAM,
pinned build `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314` (`assembly_sha256 A1F9E653…`,
`pck_sha256 42520EB8…`). Raw measurements are the git-ignored artifacts
`artifacts/perf-probe/probe_entry_timing.json`, `probe_worker_memory.json`, `probe_worker_memory2.json`
and `artifacts/perf-probe/w{2,4,6}/breadth.json`, produced by `artifacts/perf-probe/*.py` and by
`scripts/run-e5-differential.ps1 -Mode breadth -BreadthLimit 8 -Workers {2,4,6} -SkipBuild`.

## 2. Measured cost model for one entry

| Component | root stop | Evidence |
| :--- | ---: | :--- |
| shipped process launch: sandbox preparation, spawn, port file, socket | 1.26 s | `launch_total_incl_prepare`; sandbox preparation itself is only 0.10 s cold / 0.03 s warm |
| **shipped `start_run` RPC: engine boot → main-menu autoplay driver → run start → first decision boundary** | **12.87 s** | `run_entry_root_rpc_seconds_by_method.start_run` |
| shipped `step` RPC (root stop takes 3) | 2.11 s | 0.70 s per step; an endpoint entry takes ~9 steps ≈ 6.3 s |
| fast-path `neow_run_reset` | 0.53 s | |
| fast-path Godot host construction (per entry in breadth mode) | 2.48 s | `native_worker_construct` |
| `observe` + `legal_actions` RPC for the whole entry | 0.006 s | 6 observations, 7 action reads |
| `close` | 0.10 s | |
| **serial cost per entry** | **≈19.8 s root / ≈26.0 s endpoint** | root from `run_entry_root_total` + host construction; endpoint from 8 entries / 2 workers = 104.0 s |
| shipped process working set after `start_run` | 1088 MB | |

The `start_run` figure is **not** dominated by the build-identity hash. A controlled comparison on two
independent processes: `hello` (which forces the 2.8 GB assembly+PCK SHA-256) 4.52 s followed by
`start_run` 7.63 s = **12.15 s to the first boundary**, versus `start_run` alone **12.87 s to the first
boundary** when nothing forced the hash. The background prime hides the hashing, so caching the build
identity is a low-value optimisation and is not proposed here.

In a full `both` run the shipped side is ~139 entries × the fixed ~13 s, i.e. ~1.8 ks of the ~3.1 ks of
serial work; the remainder is stepping (~24 % of an endpoint entry) plus fast-path resets. That fixed
cost is what any serious throughput work has to attack.

## 3. Hypotheses excluded by measurement

- **Sandbox preparation is not a bottleneck.** Cold 0.097 s, warm 0.029 s (symlinks, junctions, mod
  package copy, settings write). The targeted mode's unique sandbox id per sampled root costs nothing.
- **Redundant RPC round trips are not a bottleneck.** `run_entry` reads `observe()` and
  `legal_actions()` twice per boundary (once at the loop head, once inside `_consume_full_wrappers`),
  and `step` already returns both. The whole entry spends 6 ms in those RPCs; the duplicated reads and
  the observation payload size are irrelevant.
- **`close`/teardown is not a bottleneck** (0.10 s), and the fast-path side is not a bottleneck either
  (0.53 s reset + ~0 ms per RPC).

## 4. Targeted-mode enumeration

`compare_root_sample` enumerates each fixture once, inside the same worker thread as that fixture's
three game entries: `EnumerationLimits(max_actions_per_branch=16, max_roots=512, max_expansions=1024)`.
One measured fixture (81 roots) took **15.75 s**; the E4 root gate records 8–340 roots per fixture, so
most fixtures are cheaper and the largest is comparable to this measurement. Across 13 fixtures this is
on the order of 100 s of serial work, or roughly 5–10 % of the targeted run. It is parallel across the
two pool threads but serialised against that fixture's game entries, so it delays the first entry of
each fixture rather than the run as a whole.

## 5. Concurrency calibration and the desktop-dialog incident

The same 8-entry endpoint workload (breadth seeds `E5BREADTH000`–`007`):

| Workers | Wall time | Speed-up vs 2 | Per-entry |
| ---: | ---: | ---: | ---: |
| 2 | 104.0 s | 1.00× | 13.0 s |
| 4 | 60.7 s | 1.71× | 7.6 s |
| 6 | 58.0 s | 1.79× | 7.2 s |

Effective concurrency saturates near 3.3–3.4 (8 cores, 2.8 GB of page-cache-backed hashing reads per
process start, one Godot host per worker). All 8 entries matched at every worker count.

During or after the multi-worker runs the **`crashpad_handler.exe` desktop error dialogs**
(`unknown software exception (0x80000003)`) appeared, and two orphaned handler processes remained
(started 19:50:59 and 19:51:12). They were killed. The shipped process is spawned by
`python/sts2_native_sim/full_app_client.py:156` with a plain `subprocess.Popen`: it does **not** inherit
the `SEM_NOGPFAULTERRORBOX` / `SEM_FAILCRITICALERRORS` error modes or `CREATE_NO_WINDOW` that
`python/sts2_native_sim/client.py:47-63` applies to Godot workers, so any shipped-side fault surfaces as
a desktop dialog instead of a reported failure. That both blocks fail-loud behaviour and conflicts with
the repository rule against manipulating the visible desktop.

Maintainer decision (2026-09-13): **do not raise concurrency**; four workers are known to be
unreliable and two workers are already sometimes unstable. Concurrency is therefore treated as fixed at
the tested default, and the remaining options must reduce per-entry cost instead.

## 6. Defects found while measuring

1. **Sandbox-id collision.** `python/first_combat_differential_acceptance.py:141` builds the targeted
   worker id as `fixture_index * 8 + index` for `index < 8` and `fixture_index + index` otherwise. For
   `-RootsPerFixture > 8` two entries can resolve to the same id (e.g. (0,16), (1,15) and (2,14) all map
   to 16) and therefore share one sandbox directory: same userdata, same `bridge_port.txt`, same log
   file. Defaults (`3` roots) never reach it, so this is a latent isolation loss rather than a current
   failure.
2. **Mismatched worker defaults.** The runner's `--workers` default is 4
   (`python/first_combat_differential_acceptance.py:165`) while the one-click script passes 2 and
   documents 2 as the tested default.
3. **No error-dialog suppression for the shipped process** (see §5).
4. **`NativeWorker.memory_bytes` under-reports by ~30×.** It reads the process it spawned
   (`Godot_v4.5.1-stable_mono_win64_console.exe`, 5.7 MB working set) rather than the engine child the
   console launcher starts (`Godot_v4.5.1-stable_mono_win64.exe`, 168 MB). The in-repo note that a fresh
   worker is ~2.1 GB is not reproducible with this helper.

## 7. Corrected claim: one run start per process

`docs/persistent-environment-evidence.md` (and the runner docstrings and script comment) state that
"the shipped game serves exactly one run start per process". Source review of the pinned build shows
that this is a constraint of the current bridge, not a property of the shipped application:

| Evidence | Location |
| :--- | :--- |
| The shipped autoplay driver quits the process when its run ends — the actual reason one process serves one run | decompiled `MegaCrit.Sts2.Core.AutoSlay.AutoSlayer.RunAsync` `finally { QuitGame(_exitCode) }` |
| The same shipped driver already handles "a run is in progress": it clicks Abandon Run, confirms, then starts a new run from the main menu | `AutoSlayer.PlayMainMenuAsync` |
| The shipped run teardown exists and is complete: `NGame.ReturnToMainMenu()` → `RunManager.CleanUp()` (`CombatManager.Reset(graceful)`, `CardSelectCmd.Reset()`, `ActionQueueSet.Reset()`, synchroniser disposal, UI container clears, `LocalContext.NetId = null`, `State = null`, `ShouldSave = false`) | decompiled `NGame.ReturnToMainMenu`, `RunManager.CleanUp`; this is the same cleanup `docs/persistent-environment.md:161` needed for the reconstructed worker |
| The production run-start seam is directly callable without menu or lobby clicks: `NGame.StartNewSingleplayerRun(character, shouldSave, acts, modifiers, seed, mode, ascension)` → `RunState.CreateForNewRun` + `Player.CreateForNewRun` + `SetUpNewSingleplayer` + `StartRun` | decompiled `NGame.StartNewSingleplayerRun`; the reconstructed `neow_run_reset` already models exactly this seam |
| In-process multi-run is already proven on the reconstructed side | `PersistentNativeCombatEnvironment` serves many run starts per Godot process after `CombatManager.Reset(graceful: true)` |

Consequence: the fresh-process-per-entry measurement remains a valid and conservative choice, but it is
a **choice**, and the documented reason for it is wrong. That correction is recorded here and in the
bridge specification; it does not by itself claim that a bridge-driven reuse reproduces identical runs.

## 8. What a bridge-driven reuse would require

- **Bridge-owned run lifecycle.** Today the bridge waits for the main menu once and calls
  `AutoSlayer.Start`; the driver owns the room loop and exits the process at run end. Reuse needs the
  bridge to own the loop: release any parked coordinator wait, tear the run down
  (`NGame.ReturnToMainMenu()` / `RunManager.CleanUp()`), start the next run through
  `NGame.StartNewSingleplayerRun`, and wait for the first decision boundary again.
- **Release the parked coordinator task.** `FullAppBridgeServer.WaitForCoordinatorActionAsync` awaits a
  `TaskCompletionSource` that does **not** observe the driver's cancellation token, so a cancelled
  driver leaves a live continuation parked on the old run. Teardown must complete that pending task
  explicitly; otherwise a stale continuation competes with the next run's boundaries.
- **Reset the bridge's own per-entry state**: `ActionHistory`, `StateHashHistory`, `_choiceOrdinal`,
  `PendingChoice`, `_fusedCardRewardClaim`, `IsRunStarted` / `_initialBoundaryTcs`, and the per-entry
  `EmitCombatCompleteBoundary` flag.
- **Isolate the profile.** Either start every run with `shouldSave: false` (`RunManager.OnEnded`
  persists progress only under `if (ShouldSave)`) or re-install the pinned progress snapshot before each
  run start — preferably both.
- **Keep the evidence claim honest.** The runner must record whether an entry ran in a fresh process or
  in a reused one, and the E5 authority gate needs a fresh-vs-reused equivalence result before a reused
  report can stand as evidence.

## 9. Isolation and determinism analysis (source level)

- Act 1 world generation consumes `UnlockState` = (revealed epochs, encounters seen, `NumberOfRuns`).
  Every `NumberOfRuns` dependency in the pinned build is a **zero test**, never a count weight
  (`Overgrowth` room ordering, `UnknownMapPointOdds`, `RewardsSet`, `LastingCandy`). The bridge pins
  every epoch revealed and every encounter seen before the first run, so the dependency is saturated
  from the first run onwards: a second run in the same process sees the same unlock state.
- Per-run RNG, deck, relic grab bag and odds are rebuilt per run from the explicit seed
  (`RunState.CreateForNewRun` / `CreateShared`, per-run `RelicGrabBag`), so nothing in the compared root
  projection is carried over by design.
- Residual risk is therefore **not** the profile but scene/static/bridge-protocol state, mid-combat
  abandon, and the parked coordinator task — all of which are falsifiable by measurement rather than by
  reading.

## 10. Expected gain (estimate, not measurement)

If the engine boot, main-menu/character-select asset loading and autoplay menu-click flow are removed
while world generation (0.53 s standalone) and stepping are kept, a reused-process entry should land at
roughly **5–8 s root / 9–12 s endpoint** instead of 19.8 s / 26 s, i.e. the full `both` run at the
unchanged two workers moves from ~26 minutes to roughly **8–10 minutes**, and process creations drop
from 139 to 2–3 — removing the churn that the crashes cluster around. These numbers are estimates and
must be replaced by measurement before any claim is made.

## 11. Risks and falsification plan

| # | Risk | Falsification |
| :--- | :--- | :--- |
| R1 | Cross-run leakage changes the compared root | Run the same entry set in fresh-process and reused-process modes and compare per-entry `status`, `boundaries`, root projection, run RNG counters and endpoint classification; the 13 targeted blessings are a natural canary because each asserts its named outcome |
| R2 | `stop=root` / `combat_complete` abandon mid-combat, not at run end | Exercise `RunManager.CleanUp()` mid-combat and prove the next `SetUpCombat` succeeds (the stale-`CombatState` failure mode the reconstructed worker hit) |
| R3 | Parked coordinator continuation survives teardown | Assert the pending task is completed and no stale handler observes the next run's boundaries |
| R4 | Bridge per-entry state not reset | Explicit reset list plus an assertion that `history`/`state_hashes` start empty per entry |
| R5 | The evidence claim silently weakens | Runner records fresh vs reused per entry; the authority gate requires the equivalence result, and the maintained docs are updated in the same change |

## 12. Proposed spike

- **S0 (prerequisite):** give the shipped process the error-mode/`CREATE_NO_WINDOW` suppression the
  Godot worker already has, so a spike failure reports instead of opening a desktop dialog.
- **S1 (no claim change):** bridge-owned run start and room loop with **one process per entry**
  (`ReturnToMainMenu`/`CleanUp` + direct `StartNewSingleplayerRun`). The measured difference is the value
  of the menu/asset/click path alone and changes no evidence statement.
- **S2 (claim change):** reuse the process across entries with the §8 resets, then run the R1
  equivalence check and report throughput.
- **Stop conditions:** any fresh-vs-reused difference, any unexplained projection/hash drift, or a
  crash rate that does not improve → return to fresh-process mode and keep only the S1 gain.

## 13. Open decisions (2026-09-13)

- Raising workers is rejected by the maintainer; concurrency stays at the tested default of 2.
- Reducing the targeted `--trajectory` coverage (endpoint only where the plan requires it) is acceptable
  to the maintainer but not essential; it is a ~1 minute change at two workers and an evidence-scope
  decision, not a throughput fix.
- S0/S1/S2 are **not yet authorized**. S0 is a defect fix worth doing regardless; S1 and S2 are a bridge
  implementation project and need explicit authority.

## 14. Provenance and limitations

Measurements are single-machine and single-build, with no repetition beyond the ones stated; the
per-entry numbers come from one instrumented entry plus the recorded 8-entry runs, not from a
distribution over the full manifest. The reuse gain in §10 is an estimate derived from component
timings, not a measured result. The feasibility analysis in §7–§9 is source-level: it establishes that
the current constraint is implementation-level and that the shipped seams exist, and it does not
establish that a bridge-driven second run start reproduces the first run's projection. The crash
dialogs in §5 were observed but not attributed to a specific run or worker count.
