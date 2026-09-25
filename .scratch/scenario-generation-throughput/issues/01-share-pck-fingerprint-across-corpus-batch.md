# 01: Share the PCK fingerprint across a corpus batch

**What to build:** A scenario corpus batch measures the game's resource-pack digest once, in the parent process, and hands it to every worker the batch starts, so that no worker re-hashes the 1.9 GB pack on its own. The pool path already measures a digest once and shares it; the corpus path builds a bare worker per shard and pays for the hash again in each — measured at **1.393 s per worker**, 54.7% of that worker's startup and about 21% of the small reference request's end-to-end wall. A batch's output must not change at all: the same request with the same worker count still writes byte-identical shards, because only where the digest comes from changes.

Both reference requests, their seed sets and the measured numbers are in the throughput diagnosis at `docs/research/act1-first-combat-scenario-generator-throughput.md`.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] A batch with more than one non-empty shard measures the resource-pack digest once in the parent and passes it to each worker, and each worker reports that its fingerprint came from the parent rather than from its own hash — no bytes hashed by the worker.
- [x] A batch with a single worker does not pay a parent measurement it cannot share.
- [x] The sharing policy is exercised offline through the corpus's worker-factory seam against a fake worker, so the behaviour is covered without a game installed.
- [x] Both reference requests write shards and a summary that are byte-identical to a corpus generated from the commit before this change, for the same request and worker count.
- [x] Per-worker startup and end-to-end wall for both reference requests are measured before and after, and recorded beside the numbers in the throughput diagnosis.

## Comments

2026-09-25：在基线 HEAD `a13ba39` 上先生成 A（1/2/4 worker）与 B（8 worker）的 corpus，再以旧裸 worker 工厂和新默认共享路径做同请求配对。全部配置的 summary 与压缩分片同配对旧路径、改动前 HEAD 的产物逐字节一致。A/2、A/4、B/8 的所有真机 worker 均报告 `source: "pool"` 和 `bytes_hashed: 0`；A/1 保持 worker 自行计算。逐 worker 启动及端到端墙钟已记在吞吐诊断，原始报告在 gitignored 的 `artifacts/scenario-performance/`。离线测试以小型 PCK 和假 worker 验证父进程仅测一次及单非空分片不测；完整测试 `281 passed`。
