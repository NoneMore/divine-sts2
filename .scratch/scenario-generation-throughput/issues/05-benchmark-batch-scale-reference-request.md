# 05: Benchmark the batch-scale reference request

**What to build:** The maintained benchmark stops reporting only the request that misleads. It drives four elements and reports about **1.8 rows per second**, of which 39% is worker startup and whose per-element cost is **2.5 times** the steady state; the batch reference request, at 512 elements over eight workers, measures **37.2 rows per second**. This ticket makes both reference requests measurable on demand, reporting the numbers a throughput claim actually needs: element throughput as the headline rate, rows per second beside it, and the success ratio and worker replacement count with them.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The benchmark runs both reference requests, each with a fixed, documented dimension set and seed list.
- [ ] Each run reports element throughput as the headline rate with rows per second beside it, plus the success ratio and the worker replacement count.
- [ ] A run refuses an output directory that already holds a corpus, so a resumed batch cannot be mistaken for a full-generation measurement.
- [ ] The invocation and the numbers it produces are recorded in the throughput diagnosis at `docs/research/act1-first-combat-scenario-generator-throughput.md`, and agree with the numbers already there within the run-to-run spread that document states.
