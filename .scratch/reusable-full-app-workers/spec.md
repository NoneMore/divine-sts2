# Reusable full-app workers

Status: ready-for-agent

## Problem Statement

Full-app validation currently starts and terminates one shipped-game process for every generated scenario. A complete parity run therefore cold-starts 16 processes, repeatedly fingerprints the same 1.77 GiB PCK, and spends minutes paying process and asset-loading costs that do not contribute additional oracle independence. The bridge cannot safely reuse a process today: it starts its driver only once, has no explicit end-of-run protocol, leaves run-scoped histories and pending decisions in process-wide state, and cannot prevent an abandoned continuation from entering the next run.

The existing full-app sandbox also starts from a fresh progress save while the simulator assumes complete content availability and pins discovery effects out of its state. That difference forces Act variants away from their run-seed selection and leaves some generated scenarios unreachable by the oracle. Process reuse must not preserve this mismatch or introduce a new one: progression and discovery need one project-wide baseline, and reused runs must remain field-for-field equivalent to independent fresh processes before reuse becomes authoritative.

## Solution

Adopt a progression-complete baseline for every simulator and full-app sandbox run, implemented by this project without depending on an external Workshop Mod. A full-app sandbox materializes deterministic completed progress once and validates it on later launches; the simulator represents the same gameplay effects directly and does not expose progression or discovery as run inputs.

Add a general reusable full-app worker lifecycle and make field-by-field parity its first adopter. A launch-scoped reuse process executes one menu-started control entry followed by warm direct-start entries, with every run explicitly ended through a fail-closed teardown that cleans the shipped run, rejects stale continuations, waits for the old driver, and resets bridge state. Reuse becomes parity's default only for a machine-readable certification that compares the complete fresh and reused entry sets on the current game build and finishes with a same-process sentinel repetition.

## User Stories

1. As a maintainer, I want a complete parity run to start one shipped-game process instead of sixteen, so that validation spends its time comparing scenarios rather than repeatedly booting the game.
2. As a maintainer, I want one shipped-game process to execute multiple independent runs, so that loaded game resources and the per-process build fingerprint are reused safely.
3. As a maintainer, I want process reuse implemented as a general full-app worker lifecycle, so that lifecycle correctness is not hidden inside one acceptance script.
4. As a parity user, I want reuse to be the normal execution mode after certification, so that the performance improvement applies without remembering an optimization flag.
5. As a parity user, I want an explicit fresh mode, so that I can obtain an independent process-per-entry baseline and diagnose reuse failures.
6. As a parity user, I want an uncertified game build to reject reuse rather than silently fall back, so that I always know which lifecycle produced a result.
7. As a maintainer, I want each run to end through an explicit protocol operation, so that failure to clean one run cannot be confused with failure to start the next.
8. As a maintainer, I want a reusable worker to accept lifecycle operations only in valid states, so that overlapping clients or requests cannot corrupt process-wide bridge state.
9. As a maintainer, I want any unrecoverable lifecycle error to poison its process, so that an uncertain process is never returned to service.
10. As a validation user, I want a failed entry preserved as a failure without an automatic retry, so that lifecycle defects remain visible instead of being hidden by a replacement process.
11. As a validation user, I want later entries to continue on a replacement process after a worker failure, so that one failure does not erase diagnostic coverage for the remaining scenarios.
12. As a maintainer, I want a run to be endable at any stable decision boundary, so that the lifecycle is not coupled to the first-combat parity sample.
13. As a maintainer, I want stale continuations from an abandoned run rejected by generation, so that an old room or combat loop cannot act on the next run.
14. As a maintainer, I want teardown to wait for the abandoned driver to finish before starting another run, so that two shipped drivers never operate concurrently in one process.
15. As a maintainer, I want teardown evidence in the protocol response, so that a report explains why the worker was considered safe to reuse.
16. As a maintainer, I want an active worker to remain promptly closable even when teardown is broken, so that final process destruction cannot be blocked by reuse recovery.
17. As a maintainer, I want ownership recorded immediately after process creation, so that a failure during port discovery, connection, or handshake cannot leak a half-started game.
18. As a maintainer, I want the full Windows process tree owned and closed together, so that descendants cannot survive a poisoned worker or interfere with its replacement.
19. As a maintainer, I want a conservative maximum number of entries per process, so that reuse does not assume memory growth is bounded without evidence.
20. As a project user, I want every run to assume completed progression and discovery, so that progression state never narrows the content distribution or becomes an accidental scenario dimension.
21. As a simulator user, I want character, run seed, and Ascension to remain the meaningful run inputs, so that adopting a completed baseline does not remove legitimate run variation.
22. As a full-app validation user, I want all sandboxes to materialize the same progression-complete baseline, so that different acceptance tools do not operate under different profile semantics.
23. As a maintainer, I want completed progress implemented inside the project, so that validation does not depend on a Workshop installation, an external binary, or a version-bound prebuilt save.
24. As a maintainer, I want profile provisioning to be deterministic and idempotent, so that a reused sandbox is either known-good or rejected rather than silently repaired.
25. As a maintainer, I want the bridge to report ready only after the game build and completed profile are known, so that the first run cannot race profile initialization.
26. As a scenario author, I want Act variants selected from the run seed under an already-discovered profile, so that every generated scenario is reachable by the shipped-game oracle.
27. As a parity user, I want the former Act-variant probes compared as ordinary generated scenarios, so that all sixteen entries contribute field-level authority evidence.
28. As a maintainer, I want fresh entries to keep using the shipped menu/AutoSlayer path, so that direct warm starts are compared against an independent start path.
29. As a maintainer, I want the reusable process's first entry to use the menu path, so that the same process supplies a cold control before any direct warm start.
30. As a maintainer, I want the first scenario repeated after all warm entries, so that cumulative or order-dependent leakage is observable in the same process.
31. As a maintainer, I want profile invariance checked once across the complete certification sequence, so that certification detects persistent profile movement without adding per-entry overhead.
32. As a maintainer, I want reuse certification bound to the exact game and lifecycle contract, so that a game, bridge, profile-policy, or scenario-set change invalidates prior evidence.
33. As a maintainer, I want only the dedicated equivalence gate to issue certification, so that an ordinary reused run cannot certify itself.
34. As a maintainer, I want compact certification committed separately from the full evidence report, so that the repository has a machine-readable trust anchor without checking in large machine-specific artifacts.
35. As a performance investigator, I want reports to identify processes and warm entries and record lifecycle timings, so that repeated-start regressions are measurable rather than inferred from console behavior.
36. As a performance investigator, I want process count and fingerprint count to be the performance gate rather than elapsed seconds, so that normal machine-load variance does not make acceptance flaky.

## Implementation Decisions

### Progression-complete baseline

- Progression completion is a project-wide invariant, not a selectable run mode. Public run inputs do not gain unlock, discovery, epoch, tutorial, profile-completion, or completed/locked switches.
- The baseline completes all gameplay progression and discovery represented by the reference completion operation: cards, relics, potions, monsters, encounters, Acts, and events are discovered; epochs are obtained; character and multiplayer Ascension progression is complete; total progression unlocks and tutorials are complete; and the enemy/encounter statistic rows needed by the shipped game exist. Achievements, real career totals, existing run saves, the player's real profile, and multiplayer session state are not synthesized.
- Character, run seed, and requested Ascension remain per-run inputs. Preferred Ascension stored in progress must never override the requested value.
- The project implements this policy itself, using the inspected Workshop Mod only as behavioral reference. The Mod is not a runtime dependency, its binary is not copied, and no pre-generated save is treated as portable across game builds.
- The simulator models the effects of the progression-complete baseline directly. A full-app sandbox materializes equivalent isolated progress data through shipped-game APIs after progress has loaded.
- Provisioning is idempotent. A sandbox with no baseline progress is provisioned once; an existing sandbox is validated against the canonical semantic fingerprint. Drift fails closed rather than being silently overwritten.
- Every full-app validation tool receives this baseline, regardless of whether it uses fresh or reusable processes.
- Bridge readiness is gated on progress load and profile provisioning/validation. Before that point, the bridge reports `initializing` and rejects `start_run`; once ready, the handshake reports the progression policy, canonical profile fingerprint, process mode, PID, bound port, and game build.

### Reusable worker lifecycle

- The reusable worker is a general full-app client/bridge capability. Field-by-field parity is its only adopter in the first delivery; other acceptance runners continue to choose their current process lifecycle.
- Process mode is launch-scoped and has two values: `fresh` and `reuse`. The bridge reports its actual mode, and a client/configuration mismatch is rejected before any lifecycle state changes.
- Reuse-only Harmony seams are installed only for a reuse process. They suppress the shipped driver's final process exit, track its task, enable direct restart, and expose the parked coordinator wait needed for safe abandonment. Missing required seams make reuse unavailable rather than partially functional.
- The worker has a strict externally observable lifecycle: `launching → idle → running → ending → idle`, with terminal `poisoned` and `closed` states. Only `idle` accepts `start_run`; only `running` accepts run actions and `end_run`; `ending` accepts no new run; `poisoned` can only be closed. A second client or overlapping lifecycle request fails closed.
- Run completion is explicit. Starting a new run never implicitly tears down the previous run.
- The first run in a reuse process follows the existing shipped menu/AutoSlayer path. Every later run uses the direct shipped `StartNewSingleplayerRun` seam with saving disabled. Fresh mode uses a new process and the menu path for every entry.
- `end_run` is valid at any stable decision boundary where the bridge is waiting for a coordinator action. It is not limited to combat or natural run completion.
- Teardown increments the run generation, requests driver cancellation, invokes the minimal `RunManager.CleanUp()` path, releases any parked coordinator wait with an abandonment sentinel, rejects the resumed stale continuation by generation, waits for the old driver task, then resets run-scoped bridge state before returning to `idle`.
- The driver-task wait has a fixed 45-second deadline. A timeout fails `end_run`, poisons the worker, and causes the process owner to destroy the process; teardown never falls back to returning to the main menu.
- Run-scoped reset covers the pending action and initial-boundary completions, current observation and legal actions, action and state-hash histories, choice ordinals and pending choices, fused reward claims, phase/boundary bookkeeping, and any identity registry retaining the prior combat. A non-null state that cannot be safely discarded makes teardown fail rather than being silently cleared.
- The run generation guard is mandatory: code resumed from an abandoned generation must raise an abandonment result and must not observe or mutate the next run.
- `end_run` returns a teardown record containing the ended generation, ending decision phase, whether a parked wait was released, stale-continuation refusal count, driver exit/deadline result, reset-time history counts, final worker state, and teardown duration.
- `close` is final destruction, not recovery. If a run is active, the server may acknowledge close but does not need to complete `end_run`; the process owner guarantees termination of the process tree.

### Ownership, failure, and recycling

- A process owner records responsibility immediately after spawn, before port, TCP, `hello`, or profile readiness succeeds. Every partial-launch exception therefore has a cleanup path.
- On Windows, ownership uses a Job Object or equivalent kill-on-close mechanism so the game and all descendants are destroyed together. Socket and file cleanup do not substitute for process-tree ownership.
- An entry exception, connection loss, driver failure, illegal lifecycle transition, teardown failure, or process exit poisons the worker. The failed entry is recorded once and is never automatically retried.
- A poisoned worker is closed and discarded. The next unstarted entry may lazily create a replacement in the same worker lane and sandbox, after the sandbox's baseline profile is revalidated.
- The first release has one serial parity lane. Its ordinary maximum is 16 entries per process, configurable through internal worker configuration rather than exposed as a progression or gameplay option. Reaching the cap closes the healthy process and causes the next entry to use a replacement.
- The certification gate explicitly raises the cap to 17 so its sentinel remains in the same process. Ordinary parity remains capped at its complete 16-entry set.
- Additional parallel full-app lanes and RSS-triggered recycling are deferred. Working-set size is reported but is not a recycling threshold in this release.

### Parity adoption and reports

- The complete parity entry set contains 16 ordinary field-by-field comparisons. The two seeds formerly used only to measure the fresh-profile Act-variant bound become ordinary generated scenarios; the forced-variant constant and special probe result shape are removed.
- Certified builds default to `reuse`; callers can explicitly select `fresh`. Reuse never silently falls back to fresh.
- An uncertified build rejects default or explicit reuse with an actionable error. Explicit fresh execution remains available because it is the baseline needed to establish a new certification.
- A normal reused parity run starts one shipped-game process and executes all 16 entries in it. The game build/PCK fingerprint is computed once for that process.
- Each result records PID, process entry ordinal, whether the entry was warm, process mode, startup time, entry time, teardown time, and replacement count. The run summary records shipped-game processes started, maximum live process count, PCK bytes hashed, and total wall time.
- Performance acceptance is structural: one healthy reused parity run starts one shipped-game process, all 16 entries share its PID, and the PCK is fingerprinted once. No fixed elapsed-time threshold is imposed.

### Certification

- Reuse certification is machine-readable and committed. Its identity binds the game assembly SHA-256, PCK SHA-256, bridge lifecycle/protocol revision, progression-complete profile-policy revision, and parity scenario-set revision.
- Only a dedicated certification gate can create or update certification. An ordinary fresh or reused parity run is read-only with respect to certification.
- The gate executes the complete 16-entry set in fresh mode, then the same set in normal order in one reuse process, then repeats the first entry as entry 17 in that same process. Reverse-order execution is not required.
- The reused process begins with the menu path and uses direct start for entries 2 through 17. Every reused result, including the sentinel, is compared with its corresponding fresh menu-start result.
- Equivalence covers success/failure classification, every field in the existing parity projection, legal decision/boundary behavior used to reach the comparison point, an empty action history plus exactly the new run's initial hash at each start, game build, and lifecycle provenance. Cross-encoder state hashes remain incomparable and are not used for gameplay parity.
- The gate captures the canonical in-memory and persisted profile fingerprint at process readiness and compares it once after entry 17. Both must still equal the original progression-complete baseline, ignoring non-semantic metadata such as timestamps.
- Any fresh failure, reuse failure, mismatch, unexpected replacement, process-count violation, profile drift, or missing lifecycle evidence prevents certification.
- Successful certification writes a compact record containing the bound identity, pass time, and digest of the complete evidence report without machine-specific paths. The complete report remains an untracked artifact.
- A change to any certification identity component invalidates reuse until the dedicated gate succeeds again. This includes a shipped-game update even when the bridge still appears to run.

## Testing Decisions

- Tests assert behavior at public seams rather than private helper calls. The highest authority seam is the existing field-by-field parity command and report: fresh and reused execution feed the same projection/comparison contract, so there is no second definition of gameplay equivalence.
- A good test observes lifecycle state, RPC results, process ownership, parity output, and certification behavior. It does not assert which private method cleared a field or duplicate shipped-game rules in a test-only implementation.
- Offline protocol tests drive the bridge dispatch surface with scripted lifecycle collaborators and verify legal and illegal state transitions, single-client ownership, launch-mode mismatch rejection, explicit `end_run`, poisoning, and refusal of requests after poisoning.
- Offline teardown tests exercise the generation boundary: a parked action resumes as abandoned, cannot publish into the next generation, the old driver must finish before another start is accepted, and deadline expiry poisons the worker.
- Offline reset tests observe the next run through public history, observation, and legal-action RPCs: it begins with zero actions, exactly its own initial hash, no previous pending choice, and no prior card identity.
- Client-level tests use controlled subprocesses to verify ownership is established before handshake, partial launch is cleaned up, active close terminates promptly, descendants die with the owner, and a poisoned process is replaced only for a later entry. These tests follow the existing full-app client seam rather than reaching into process fields.
- Profile-policy tests project the canonical semantic fingerprint from a completed progress model, prove provisioning is idempotent, reject drift, ignore non-semantic metadata, and verify the requested character and Ascension still win over profile preferences.
- Handshake tests verify `initializing` before profile readiness, rejection of early `start_run`, and the ready response's game build, process mode, progression policy, and profile fingerprint.
- Parity report tests extend the existing offline report-contract coverage with process count, PID/ordinal/warm provenance, timings, replacement count, fingerprint bytes, mode, and certification identity. Report tests do not invent sample gameplay observations beyond the existing projection fixtures.
- Certification-policy tests verify that ordinary parity cannot write certification, identity drift rejects reuse, an uncertified build can still run explicit fresh mode, incomplete evidence cannot certify, and a compact certificate validates the digest of its full artifact report.
- The shipped-game acceptance gate is the decisive integration test. It runs 16 fresh menu-start processes, one 17-entry reusable process, compares every reused entry to its fresh counterpart, confirms the sentinel repeats the first result after all intervening entries, checks one PID and one PCK fingerprint for the reuse sequence, and performs the one end-to-end profile invariance comparison.
- Existing field-by-field parity acceptance is the prior art and remains the gameplay comparison seam. Existing full-app bridge/client acceptance provides launch, RPC, sandbox, and report conventions. The deprecated sibling implementation is feasibility evidence for teardown sequencing and failure containment, not an authority test and not code to copy wholesale.
- Builds and shipped-game tests follow the repository's documented Windows environment requirement and run with the file sandbox disabled because MSBuild requires named pipes.

## Out of Scope

- Parallel full-app lanes or a public `--game-workers` option. The first delivery deliberately proves one serial reusable process.
- Migrating card-select, combat-observation, full-act, or other acceptance runners to process reuse. They receive the progression-complete baseline but keep their existing lifecycle.
- Automatic retry of a failed entry, whether in the same process or a replacement.
- Implicit teardown inside `start_run`, teardown fallback to the main menu, or support for switching process mode after launch.
- Unlimited reuse, proof that process memory is globally bounded, or RSS-based recycling.
- Per-entry profile fingerprint comparisons in ordinary parity. Profile invariance is checked once across the certification sequence.
- A progression-locked simulator mode or any public profile/discovery configuration.
- Depending on, redistributing, or automatically installing the reference Workshop Mod.
- Synthesizing achievements, badges, real career totals, or multiplayer profile/session history.
- A shared simulator/full-app state hash. Gameplay parity remains a field-by-field comparison.
- A hard wall-time performance gate.
- Tickets or implementation sequencing; those are produced by the separate ticketing workflow.

## Further Notes

- The reference Mod's completion operation was inspected with `ilspycmd`. Its relevant behavior is the semantic construction of completed progress and its persisted save, not its main-menu button or UI visibility patches.
- Minimal `RunManager.CleanUp()` is deliberately preferred to returning to the main menu. Prior controlled measurements found both capable of starting a second run, while cleanup retained warm assets and was about 2.3 seconds faster per entry. The new certification, not those historical measurements, determines whether the adapted lifecycle is authoritative in this repository.
- Historical runner evidence reached 19 entries per process with front-loaded but non-zero memory growth. That supports a conservative 16-entry cap; it does not justify unlimited reuse.
- The first reused entry is a menu-start control, while warm entries use direct start. This makes the fresh oracle independent of the seam under test and ensures a direct-start error cannot be hidden by using direct start on both sides.
- The progression-complete baseline closes the old fresh-profile Act-variant bound. Act selection remains driven by the run seed because every Act is already discovered, which is why the former probes become ordinary parity scenarios.
