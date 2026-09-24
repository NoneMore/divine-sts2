# 04: Decide whether the Ancient-choice restore can skip reconstruction

**What to build:** The measured answer to one question, which decides whether the largest single cost in scenario generation is removable. Restoring the checkpoint taken when a run entered the Ancient room costs about **215 ms** per call — 46.9% of generation time on one worker, and at least **41%** of a batch's wall clock. A run-mode branch holds no combat snapshot, so the restore falls through to rebuilding the run and its map and replaying action history; but the same code also contains a resident-prefix fast path that reports its own elapsed time as zero when it hits. This ticket delivers which of the two is happening for the Ancient-entry checkpoint, and therefore whether the reconstruction is avoidable — the fact the throughput gate's "removing it is worth at least 1.5×" condition is waiting on.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] For the restores in the small reference request, it is measured how often the resident-prefix fast path is taken, stated as a count of the eight.
- [x] The per-restore cost is attributed to named parts of the restore — fast-path hit, run rebuild, map rebuild, history replay — by timing those parts, not by inference from the total.
- [x] The verdict is stated as exactly one of two outcomes: the reconstruction is avoidable and removing it is worth at least the gate's 1.5×; or it is not avoidable, in which case the gate fails and the optimization is dropped with its reasons recorded in the throughput diagnosis.
- [x] If it is avoidable, the narrowest change that would make it so is named, together with the acceptance that already gates it — the native differential and the byte-identical corpus comparison — leaving the implementation to a ticket written at that point.
- [x] Every timing used here is external to a corpus: no duration enters a shard or a summary, per ADR-0008.

## Comments

**判定：重建是真的，而且可避免 —— 门槛 (ii) 通过，值得做。** 证据与最窄改动记在
`docs/research/act1-first-combat-scenario-generator-throughput.md` 的"待查的那件事：已测"一节，
实现留给本票判定之后写出的 `06-snapshot-run-mode-checkpoints.md`。

补测（基线 HEAD `0432993`）给 native 侧加了开关式逐部件计时（`STS2_RESTORE_PROFILE=1`，默认关闭，只随该次
`restore` 的 `transition` 回到调用方），并用新增的 `python/experiments/scenario_restore_profile.py`
驱动参考请求 A 三轮：

- **快路径命中 0 次**：三轮各 8 次 `restore`（共 24 次）全部走 `ReconstructAsync`，每次重放的历史长度都是 1；
  resident-prefix 比较本身中位 0.0006 ms —— 快路径的问题从来不是"命中太贵"，而是根本不命中。
- **开销是重建不是重放**：worker 自报合计 4932.9 ms —— `map_rebuild_ms`（`RunManager.Reset` +
  `GenerateRooms` + `GenerateMap`）**95.3%**、`replay_ms` **3.7%**、`run_rebuild_ms` **0.9%**、
  `capture_ms` 与 resident 检查合计 0.07%、未命名残差 0.06%。每次 `restore` 中位 **163.4 ms**、均值
  **205.5 ms**（RPC 墙钟中位 164.2 / 均值 209.1；24 次合计 5.017 s）；worker 之外只占 1.7%。
- **最窄改动**：把 combat 分支已有的 checkpoint 快照扩到 run-mode 分支 —— 在取 checkpoint 处捕获 run 状态、
  在 `RestoreAsync` 里应用到活着的 run 上，而不是 `Construct` + `InitializeRunMap` + 重放；shipped game 的
  save/load 路径（`SetUpSavedSingleplayer` / `SerializableActMap`）是它最省新表面的落点。
- **验收两道门都跑过**：`tests/acceptance/scenario_handle_reuse_acceptance.py` 通过（6 element / 18 行 /
  12 次 `restore` 与 native fork 参考一致）；同一请求在 `STS2_RESTORE_PROFILE` 开与关下写出的
  `worker-00.jsonl.gz` 与 `summary.json` 的 SHA-256 完全相同 —— 计时确实不进 corpus（驱动本来也不读
  `transition`，所以这条证明的是"开着开关的批量与关着时逐字节无法区分"）。

