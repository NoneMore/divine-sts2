# Documentation index

This directory holds the maintained engineering knowledge for the project: governing invariants, dated status and evidence records, environment and protocol contracts, and the plans and reports behind them.

Start with [project-status-and-review-guide.md](project-status-and-review-guide.md) for current capability and evidence precedence, and [architectural-guardrails.md](architectural-guardrails.md) before changing search, training, reward, value, promotion, or simulation architecture. [AGENTS.md](../AGENTS.md) holds the repository-level rules that govern all of this, including the prohibition on committing generated research output.

## Reading order by question

| Question | Read |
| :--- | :--- |
| What is the project's current capability, and what is actually proven? | [project-status-and-review-guide.md](project-status-and-review-guide.md) |
| What invariants must any new architecture obey? | [architectural-guardrails.md](architectural-guardrails.md) |
| Which game build is pinned, and what compatibility is claimed? | [version-compatibility.md](version-compatibility.md) |
| How do I run the native environment, and what does its protocol guarantee? | [persistent-environment.md](persistent-environment.md) |
| What was verified about that environment, and how fast is it? | [persistent-environment-evidence.md](persistent-environment-evidence.md) |
| How is state serialized and hashed? | [state-hashing.md](state-hashing.md) |
| How does the shipped-application bridge work? | [full-application-control-bridge.md](full-application-control-bridge.md) |
| Where does the E5 differential's run time go, and can one shipped process serve several run starts? | [e5-differential-run-cost-and-process-reuse-report.md](e5-differential-run-cost-and-process-reuse-report.md) |
| How do I generate runs and training data, and what has been rejected? | [native-rollout-farm.md](native-rollout-farm.md) |
| What is a differential trace, and how is certification scoped? | [differential-trace-format.md](differential-trace-format.md), [trace-exporter.md](trace-exporter.md), [isolated-autotrace.md](isolated-autotrace.md) |
| What work is planned or in flight? | [first-combat-scene-generation-plan.md](first-combat-scene-generation-plan.md), [a1-policy-recovery-plan.md](a1-policy-recovery-plan.md), [holistic-solver-roadmap.md](holistic-solver-roadmap.md) |
| Why does the environment look like this? | [phase-1-feasibility-report.md](phase-1-feasibility-report.md), [phase-1b-headless-godot-report.md](phase-1b-headless-godot-report.md) |

## Canonical ownership

Each durable claim has one home. Update that home instead of restating the claim elsewhere.

| Document | Owns | Role / lifecycle |
| :--- | :--- | :--- |
| [project-status-and-review-guide.md](project-status-and-review-guide.md) | Current capability on the four axes, evidence precedence, external-proposal decisions, active milestone order, claims discipline | Maintained; refresh whenever a milestone or externally stated capability changes |
| [architectural-guardrails.md](architectural-guardrails.md) | Durable research principles and architecture invariants with their verification gates | Maintained; changes require deliberate architectural authority |
| [version-compatibility.md](version-compatibility.md) | The pinned build fingerprint and the (absent) cross-build compatibility claim | Maintained; update on every build pin |
| [state-hashing.md](state-hashing.md) | Canonical state bytes and hashing rules | Draft, explicitly non-certifying until differential traces fix the field inventory |
| [persistent-environment.md](persistent-environment.md) | `reconstructed_native` contract: authority model, worker/process model, reset and branch protocol, reset modes, choice seams, run-start (Neow) contract, presentation-suppression inventory | Maintained contract |
| [persistent-environment-evidence.md](persistent-environment-evidence.md) | Dated verification evidence, fault injections, recorded stale expectations, measured performance for that environment | Maintained evidence log; supersede rather than silently edit results |
| [full-application-control-bridge.md](full-application-control-bridge.md) | `full_application_native` sandboxing, RPC protocol, suppression seams | Dated specification/report; its GO verdict and benchmarks are historical, not a current certification |
| [e5-differential-run-cost-and-process-reuse-report.md](e5-differential-run-cost-and-process-reuse-report.md) | Measured cost model of the E5 differential runner, concurrency calibration on one machine, and the source-level assessment of serving several run starts from one shipped-application process | Dated evaluation; input to a decision, not a capability claim |
| [native-rollout-farm.md](native-rollout-farm.md) | Rollout farm capability and throughput, compile/train pipeline, native critic and value-model experiment record, promotion gates | Maintained |
| [differential-trace-format.md](differential-trace-format.md) | Trace file format, comparator modes, campaign aggregation and its non-global certification scope | Maintained specification |
| [trace-exporter.md](trace-exporter.md) | Read-only shipped-game exporter, its coverage, safety gates, and install procedure | Maintained specification |
| [isolated-autotrace.md](isolated-autotrace.md) | Opt-in AutoTrace driver and launcher contract, sandbox isolation, capture hygiene | Maintained specification |
| [first-combat-scene-generation-plan.md](first-combat-scene-generation-plan.md) | The E0–E7 first-combat corpus program: units, gates, handoffs, re-plan triggers | Active plan; coordination state, retire when its gates complete |
| [first-combat-e0-launch-contract-report.md](first-combat-e0-launch-contract-report.md) | E0 probe evidence and the confirmed Neow launch entry contract | Dated report; evidence is closed, contract is durable in the environment document |
| [first-combat-neow-investigation-report.md](first-combat-neow-investigation-report.md) | The upstream design investigation behind the first-combat program | Dated investigation; input to the plan, not current truth |
| [a1-policy-recovery-plan.md](a1-policy-recovery-plan.md) | Policy-quality recovery decision, operating loop, and A1 promotion gates | Active plan; corpus-generation sequencing is owned by the first-combat plan |
| [holistic-solver-roadmap.md](holistic-solver-roadmap.md) | Phase-level target, deliverables, and promotion gates; the external-simulator constraint | Roadmap; intended work, controlled by the status record when they conflict |
| [phase-1-feasibility-report.md](phase-1-feasibility-report.md) | The plain-console negative result and dependency inventory that justified engine hosting | Historical report; explicitly superseded by Phase 1b |
| [phase-1b-headless-godot-report.md](phase-1b-headless-godot-report.md) | The headless-Godot feasibility result that selected the current architecture | Historical report; still non-certifying for ML training |
| [mechanic-coverage.csv](mechanic-coverage.csv) | Machine-readable mechanic coverage matrix consumed by the differential harness | Data; update only from recorded evidence |

Generated research output lives under `artifacts/`, which is git-ignored. Documents may name artifact paths as provenance, but the artifacts themselves are never committed.

## Conventions

- The directory is intentionally flat. Keep lowercase kebab-case filenames and topic-oriented names; if a document is moved or renamed, update every inbound reference, including the two Python docstring references (`python/run_room_entry_acceptance.py`, `python/sts2_native_sim/first_combat.py`) and any external links.
- Durable documents state their role and — when a reader could confuse target state with current state — an explicit status. Dated evidence keeps its date; current capability claims belong to the status record.
- Most documents are written in English; the first-combat plan and its E0 report are in Chinese. Preserve a document's existing language when editing it, and keep identifiers, build hashes, and error names verbatim.
- Do not copy volatile status, benchmark numbers, build identifiers, or file inventories into `AGENTS.md`.

## Retired or unresolvable references

- `docs/shadow-simulator-audit.md` was retired in the repository cleanup commit `d6371e0`. Its durable conclusion (the external Python simulator is optional, unlicensed, non-authoritative, and never a label source) is recorded in [holistic-solver-roadmap.md](holistic-solver-roadmap.md); the underlying audit artifact path `artifacts/shadow-simulator-audit.json` is git-ignored generated output.
- `docs/research/sts1-prior-art-and-transfer-strategy.md` was referenced by older revisions of the status record and the guardrails but was never committed. The seven research principles it informed are fixed in [architectural-guardrails.md](architectural-guardrails.md) §0, and the external proposal decisions are in the status record.
- `artifacts/combat-v2-training/phase-3c-final-report.md`, previously cited for the Combat V2 "Category C" result, is private development evidence that is not reproducible from the public clone. The status record discloses that limitation; treat those numbers accordingly.
