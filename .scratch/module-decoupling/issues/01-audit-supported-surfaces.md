# 01: Audit supported surfaces and protect research inputs

**What to build:** Classify every documented Python entry point and edge C# tool by consumer,
runability, unique capability and maintenance cost. Correct public documentation that advertises broken
learned/neural commands, and explicitly protect scenario generation, scenario acceptance, worker,
scoring and forward-step capabilities needed by later combat research.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] Every current entry is classified as supported command, internal tool, experiment or deletion candidate.
- [x] A deletion candidate has no uninvestigated consumer or unique capability.
- [x] Broken neural/learned paths are removed from public promises without reconstructing their model stack.
- [x] The audit records the disposition required for AutoTraceDriver, TraceExporterSmoke and ApiProbe.
- [x] No production code or tool is moved in this ticket.

## Answer

The completed audit is [`supported-surfaces-audit.md`](../supported-surfaces-audit.md). It classifies
all 83 current top-level Python entries and the three edge C# tools, records verified consumers and
replacement capabilities for every deletion candidate, and protects the scenario, acceptance,
worker, scoring, forward-step and exact-trace surfaces required by later combat research. `README.md`
now points users at the formal scenario command instead of the deleted neural model stack.
