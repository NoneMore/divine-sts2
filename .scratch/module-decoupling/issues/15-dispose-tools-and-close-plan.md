# 15: Dispose edge tools and close the restructuring plan

**What to build:** Apply the evidence from ticket 01 to every edge tool, update current documentation,
and run the complete repository gates. A tool becomes maintained, internal, experimental or deleted;
ambiguous limbo is not an outcome.

**Blocked by:** 12, 13, 14.

**Status:** resolved

- [x] Maintained C# tools are in the solution/build and have a discoverable entry and minimum smoke.
- [x] Internal and experimental tools state their purpose and do not feed supported code backwards.
- [x] Deleted tools have documented replacements or evidence that their capability is no longer needed.
- [x] Architecture documentation points to the implemented modules and accepted ADRs.
- [x] Public-tree, offline, build, acceptance and relevant parity gates pass.
- [x] A corpus scenario can still be materialized and completed through the forward-only Combat episode interface.

## Answer

`Sts2.NativeSim.AutoTraceDriver` is now a solution project, while
`scripts/run-isolated-autotrace.ps1` remains its discoverable full-app build, packaging and exact-
replay smoke. The shared Protocol assembly is packaged as an internal dependency mod so both
FullAppBridge and TraceExporter load through the shipped game's declared mod dependency order.
Automated full-app and AutoTrace sandboxes force master, music, effects and ambience volumes to zero.

The four deletion candidates authorized by ticket 01 are gone: the broken MCTS example, the
duplicated benchmark, the assertion-free TraceExporter smoke project and the unconsumed reflection
probe. `docs/tooling.md` records their maintained replacements and the support promise for tools and
experiments. `docs/architecture.md` points to RunSession, Protocol, the Generated scenario/Combat
episode facade, ADR-0005 and ADR-0006; the README links both current guides.

The cleanup also exposed and repaired two integration gaps from the preceding protocol work: shipped-
game mods now load Protocol as a declared dependency, and non-combat FullApp observations no longer
attach the combat-only inventory stage block. The public-tree gate, complete Release solution build,
.NET tests, offline Python tests, deep doctor, real-worker scenario corpus acceptance and the complete
14-sample field parity run pass. The existing public-interface test materializes a Generated scenario
and completes its first combat solely through forward `CombatEpisode.step` calls.
