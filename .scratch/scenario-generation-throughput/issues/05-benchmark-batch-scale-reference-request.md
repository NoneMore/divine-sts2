# 05: Benchmark the batch-scale reference request

**What to build:** The maintained benchmark stops reporting only the request that misleads. It drives four elements and reports about **1.8 rows per second**, of which 39% is worker startup and whose per-element cost is **2.5 times** the steady state; the batch reference request, at 512 elements over eight workers, measures **37.2 rows per second**. This ticket makes both reference requests measurable on demand, reporting the numbers a throughput claim actually needs: element throughput as the headline rate, rows per second beside it, and the success ratio and worker replacement count with them.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] The benchmark runs both reference requests, each with a fixed, documented dimension set and seed list.
- [x] Each run reports element throughput as the headline rate with rows per second beside it, plus the success ratio and the worker replacement count.
- [x] A run refuses an output directory that already holds a corpus, so a resumed batch cannot be mistaken for a full-generation measurement.
- [ ] The invocation and the numbers it produces are recorded in the throughput diagnosis at `docs/research/act1-first-combat-scenario-generator-throughput.md`, and agree with the numbers already there within the run-to-run spread that document states.

## Comments

2026-09-25：维护基准已默认测 A（1/2/4 worker）与 B（8 worker），报告 element/秒、行/秒、成功率和替换数，并在计时前拒绝已有输出。三轮实机复测、首次单轮复测及旧模式对照已写入吞吐诊断；完整离线测试 277 passed。最后一项仍未满足：A 的新三轮中位墙钟均快于原记录的逐轮范围，B 的三轮中只有一轮落在原两次范围内。旧模式在当前主机上也更快，差异来源未隔离，因此未把偏差称为性能提升，也未将本票标为 `done`。
