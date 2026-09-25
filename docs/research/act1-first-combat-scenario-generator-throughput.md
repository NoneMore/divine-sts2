# 第一战场景生成器的吞吐诊断

**测量日期：** 2026-09-25，`feat/first-combat-generator`（HEAD `193e51c`）。本文把**实测**与**推断**分开标出：标"实测"的数字来自本次运行，标"推断"的是由实测外推或由源码读出的结论，两者的可信度不同。原始产物在本机 gitignored 的 `artifacts/scenario-performance/` 下。文末另有一处**补测**：同日晚在 HEAD `0432993` 上测了 `restore` 的逐部件构成与快路径命中数，它把 Q13 的条件 (ii) 从悬置改为满足；那一节的数字同样标为实测。

## 结论

1. **记录中的基线在本机today 精确复现**（热 worker 中位 4.033 s / 2.975 行每秒，记录值 4.049 / 2.963），因此后续比较有可靠基准，不需要重新建立基线。
2. **但那个基线不代表批量成本。** 它的请求只有 4 个 element，被 worker 启动与首次驱动的预热吃掉大部分。实测同一 worker 在 64 个 element 上的稳态成本是 **0.406 s/element**，而 4-element 请求是 **1.008 s/element** —— 差 **2.5 倍**。参考请求 B（512 element / 8 worker）端到端 **41.3 s，即 12.4 element/秒、37.2 行/秒**，是参考请求 A 的 1 worker 行速率的 **20 倍**。
3. **按 spec 的规模，这个生成器已经够快。** spec 的第一刀是"a few thousand records"：3000 行按实测的 37.2 行/秒约 **81 秒**；就是 spec 列为 out of scope 的 10⁵ 行，线性外推约 **45 分钟**。真正的账不是"太慢"，而是**之前的数字测错了对象**。
4. **成本确实集中在 native 侧**：实测单 worker 稳态下 `restore` 占生成时间 **46.9%**、`run_reset` **31.3%**、`run_step` **21.3%**。**Q13 门槛的三个条件现在都满足**：条件 (i) 与 (iii) 由本次运行满足，条件 (ii) 由文末的补测回答——参考请求 A 的 8 次 `restore` 里 resident-prefix 快路径命中 **0 次**，每次 restore 中位 163 ms（均值 206 ms）中 **95.3% 是重建 run 的 act（Reset + 房间 + 地图）**，重放只占 **3.7%**。
5. **唯一存活下来的便宜改动是共享 PCK 指纹**：实测每 worker 省 **1.393 s**（启动的 54.7%）——占参考请求 A 的 **21%**，占参考请求 B 的 **3–7%**。机制早已存在（`NativeWorkerPool` 会测量一次并全池共享），只是 corpus 路径没接线。
6. **一个已实测的缺陷比任何微优化都重要**：种子 `200150` 的一个 element 花 **66.79 s** 并产 1 条失败行、换掉 1 个 worker——是正常 element 的 **164 倍**，单次代价约等于整个 512-element 批量的 **1.6 倍**。
7. **两条被证伪的假设**：`numpy`（经 `gym`）的导入开销可忽略（实测包导入 0.344 s、`pkg+gym` 0.337 s），此前把它当作内循环成本的说法不成立；以及"加 worker 就能线性加速"——参考请求 A 上 4 worker 相对 1 worker 只有 1.15 倍。

## 参考请求（写死）

两个尺度都固定下来，跨轮比较只在这两个请求上进行（`CONTEXT.md` 的 **Reference request**）。

| | 参考请求 A（内循环） | 参考请求 B（批量） |
| --- | --- | --- |
| 角色 | `IRONCLAD` | `IRONCLAD`, `DEFECT` |
| 进阶 | 0 | 0, 2 |
| 种子 | `A1B2C3D4E5`, `1`, `2`, `3` | `1` … `128` |
| element 数 | 4 | 512 |
| worker | 1 / 2 / 4（三种都测） | 8 |
| 压缩等级 | 3 | 3 |
| 预期行数 | 12 | 1536 |

A 与历史记录同形，用于对账；B 的每分片 64 个 element 足以摊薄启动，用于回答规模问题。

复现命令（`paths.py` 不读 `.env`，必须经 PowerShell 层）：

```powershell
# 参考请求 A，三轮，含分片字节同一断言
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/tools/benchmark_scenario_generation.py diag-20260925-r1 --rounds 3 --legacy-comparison'

# 参考请求 B：一次计时运行
pwsh -NoProfile -Command '. ./scripts/common.ps1; $s = foreach ($n in 1..128) { "--seed"; "$n" }; & ./.venv/Scripts/python.exe -m sts2_native_sim.cli scenario --character IRONCLAD --character DEFECT --ascension 0 --ascension 2 @s --workers 8 --compression 3 --output-dir artifacts/scenario-performance/diag-campaign-a1'

# 单 worker 稳态探针（漂移 + RPC 构成 + PCK 指纹对照）
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/experiments/scenario_diagnosis_probe.py --elements 64 --seeds-per-chunk 2 --out artifacts/scenario-performance/diag-probe.json'

# 补测：参考请求 A 的每次 restore 花在哪（worker 需先建成 Godot worker 读的 Debug 配置）
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/experiments/scenario_restore_profile.py --rounds 3 --out artifacts/scenario-performance/restore-profile.json'
```

## 环境复现（实测）

| 项目 | 本次 | 记录中的基线 |
| --- | --- | --- |
| `sts2.dll` SHA-256 | `A1F9E653…6D7A52` | 同 |
| `SlayTheSpire2.pck` SHA-256 | `42520EB8…D48587` | 同 |
| 游戏版本 | `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314` | 同 |
| OS / CPU / RAM | Win10 19045 / Ryzen 7 3700X 8 物理 16 逻辑 / 31.9 GiB | 同 |
| Python | 3.13.5 | 同 |
| Godot | 4.5.1 mono | 同 |
| GodotHost/Core 构建 | Debug 与 Release 均新于 `Main.cs`（21:33:03） | 不陈旧 |

游戏根与 sandbox 根同在 `F:` 卷，硬链接条件满足。唯一偏离：`src/Sts2.NativeSim.Host/bin/Debug` 的 Host 程序集（21:28:32）旧于 `Main.cs`，但 `find_host_assembly()` 优先 Release 且该 host 本就无法驱动模拟器，**在生成路径之外**。

## 参考请求 A：与记录对账（实测，三轮中位数）

| 项目 | 本次（reuse_handle） | 记录值 | 偏差 |
| --- | ---: | ---: | ---: |
| 热 worker 生成时间 | 4.033 s | 4.049 s | −0.4% |
| 行/秒 | 2.975 | 2.963 | +0.4% |
| `run_reset` ×4 | 1.109 s | 1.139 s | −2.6% |
| `restore` ×8 | 1.720 s | 1.715 s | +0.3% |
| `run_step` ×49 | 1.204 s | 1.187 s | +1.4% |
| worker 启动至 `hello` | 2.585 s | 2.466 s | +4.8% |
| corpus 1 worker | 6.574 s / 1.825 行每秒 | 6.578 s / 1.824 | 一致 |
| corpus 2 worker | 5.855 s / 2.049 | 5.843 s / 2.054 | 一致 |
| corpus 4 worker | 5.713 s / 2.100 | 5.534 s / 2.169 | +3.2% |

9 对（1/2/4 worker × 三轮）分片与 summary **全部字节同一**（`corpus_differential: byte_identical: true`）。[记录值](act1-first-combat-scenario-handle-reuse.md#L50-L63)。

**由 A 得到的结构（实测）：** 4 worker 相对 1 worker 只快 **1.15 倍**；按中位数，1 worker 6.574 s 中有 **2.585 s（39%）是启动**，剩下 3.99 s 里 reset+restore 占 2.83 s（71%）。四个 element 里首个占 2.17 s，其余 0.94 / 0.66 / 0.26 s —— **预热是主要成本**。

## 参考请求 B：批量吞吐（实测）

| 项目 | 运行 A | 运行 B |
| --- | ---: | ---: |
| 端到端墙钟 | 41.487 s | 41.033 s |
| scenario 行 | 1536 | 1536 |
| failure 行 | 0 | 0 |
| worker 替换 | 0 | 0 |
| 分片 | 8 / 8 complete | 8 / 8 complete |

按中位数 41.260 s：**12.41 element/秒**、**37.23 行/秒**、每 element **0.0806 s**、每行 **0.0269 s**。

**字节同一（实测）：** A 与 B 的 `summary.json` 与 8 个 `worker-NN.jsonl.gz` 共 **9 对文件 SHA-256 全部相同**。这同时验证了 ADR-0008 所依赖的性质在批量尺度上成立。

**推断（非实测）：** 单 worker 无争用时每 element 0.406 s，512 element 的串行计算量约 208 s；8 worker 理论下界 ≈ 26 s + 启动。实测 41.3 s 意味着 **8 路并发带来约 1.45 倍的单 element 膨胀**。这是由两个独立测量相除得到的推断，本次没有单独测量争用系数。

### 维护基准脚本复测（2026-09-25，HEAD `c83e81c` 加本工单改动）

**实测。** 在上表同一主机与游戏 build 上，运行维护的基准脚本三轮；它按上表固定维度与种子，用 gzip 等级 3，每轮先测 A 的 1/2/4 worker，再测 B 的 8 worker。每个配置、每轮都使用全新的 corpus 目录，脚本以完整 `generate_corpus` 调用的外层墙钟计时，结果写在 corpus 之外的 gitignored `artifacts/scenario-performance/results-ticket05-20260925-r3.json`。调用命令：

```powershell
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/tools/benchmark_scenario_generation.py ticket05-20260925-r3 --rounds 3'
```

| 请求 | worker | element/秒中位（主速率） | 行/秒中位 | 墙钟中位（范围） | 每轮成功/总行（成功率） | 每轮 worker 替换 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 0.617 | 1.851 | 6.482 s（6.281–6.566） | 12/12（100%） | 0 |
| A | 2 | 0.708 | 2.123 | 5.653 s（5.563–5.656） | 12/12（100%） | 0 |
| A | 4 | 0.739 | 2.218 | 5.411 s（5.326–5.413） | 12/12（100%） | 0 |
| B | 8 | **13.209** | **39.628** | 38.760 s（38.601–41.251） | 1536/1536（100%） | 0 |

成功率为 scenario 行数除以 scenario 与 failure 行数之和；element/秒的分子始终是请求声明的 element 数。每轮的速率、成功率和替换数都在输出 JSON 中，表中速率与墙钟取三轮中位数。

**与旧数据的差异。** 此前 A 的三轮墙钟范围分别是 1 worker **6.570–6.579 s**、2 worker **5.853–5.939 s**、4 worker **5.612–5.792 s**；这次 A 的三组中位数都比旧范围快。此前 B 的两次是 **41.033–41.487 s**；这次三轮中有一次 41.251 s 落在旧范围，另外两次约 38.6–38.8 s，更快。此前仅两次 B 测量不足以界定其波动范围。补做的一轮旧 `--legacy-comparison` 模式在同一主机上给出 A 的 `reuse_handle` 墙钟 **6.476 / 5.658 / 5.322 s**（1/2/4 worker），与本次新模式接近，也低于原记录；故偏差不能仅归因于新模式的代码路径。尚未隔离主机负载、缓存与此间代码变更对差异各自的影响，不把它宣称为性能提升。首次单轮新模式的 B 是 **41.225 s、12.420 element/秒、37.259 行/秒**，落在旧 B 两次范围内；原始结果保存在 `results-ticket05-20260925-r2.json`。重跑需使用新标签，因为脚本拒绝已有 corpus 目录，防止续跑被计作完整生成。

### B 的同机交替配对（2026-09-25，HEAD `9e7cda7`）

**实测。** 在固定 HEAD `9e7cda7` 之上仅给基准脚本增加选择 B 的参数；生成器和 CLI 路径未改动。为比较原手工/CLI B 路径与维护基准 B 路径，使用同一个 PowerShell 驱动，在每对内交替顺序执行；每次以新 Python 进程写入新目录，用同一进程外 `Stopwatch` 计完整命令（包括 Python 启动、生成、打印与退出）。CLI 命令保留上文的 `scenario --character IRONCLAD --character DEFECT --ascension 0 --ascension 2`、种子 `1`…`128`、`--workers 8 --compression 3`；基准命令以新增的 `--reference B` 只运行同一固定请求，不先跑 A。驱动调用如下，原始结果在 gitignored 的 `artifacts/scenario-performance/paired-paired20260925h9e7cda7.json`，逐命令输出在同名 `.log` 文件中：

```powershell
pwsh -NoProfile -File scripts/compare-scenario-reference-b.ps1 -RunId paired20260925h9e7cda7 -Pairs 3
```

| 配对 | 实际顺序 | CLI 进程外墙钟 | benchmark 进程外墙钟 | benchmark 比 CLI 多 | 每次结果 |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | CLI → benchmark | 42.334 s | 42.901 s | 0.567 s（1.3%） | 512 element；1536/1536 成功；0 替换 |
| 2 | benchmark → CLI | 39.670 s | 45.028 s | 5.358 s（13.5%） | 512 element；1536/1536 成功；0 替换 |
| 3 | CLI → benchmark | 39.090 s | 39.377 s | 0.287 s（0.7%） | 512 element；1536/1536 成功；0 替换 |

两条路径每对的 `summary.json` 与 8 个 gzip 分片 SHA-256 **9/9 全相同**；压缩等级均为 3，行顺序与内容也因此相同。基准自身的生成调用计时依次为 **42.349 / 44.428 / 38.863 s**，比进程外墙钟少约 0.5–0.6 s，故配对表统一使用进程外墙钟。第 1、3 对很接近，第 2 对有 **13.5%** 的离群差值；三对不足以把它归因于某个进程路径，也不能声称两条路径始终等速。它们至少证实了维护基准能在同一轮驱动与 CLI 字节相同的 B corpus，且两条路径在相邻运行中都可能落在旧 B 的 41.033–41.487 s 范围外。因此工单 05 的最终验收改为记录配对结果与差异，不再把历史两次 B 运行的窄范围当作硬门槛。

## 单 worker 稳态探针（实测，64 element / 8 块）

| 项目 | 值 |
| --- | ---: |
| 启动 | 2.559 s |
| 生成 | 25.982 s |
| 每 element | **0.406 s** |
| element/秒 | 2.463 |
| 行/秒 | 7.390 |
| 行 / 失败 | 192 / 0 |
| worker 存活 | 是 |
| `run_reset` | 64 次 / 8.141 s / **31.3%** |
| `restore` | 128 次 / 12.193 s / **46.9%** |
| `run_step` | 776 次 / 5.546 s / **21.3%** |

每块 8 个 element 的耗时依次为 **6.359, 3.063, 4.269, 1.762, 2.251, 1.659, 4.058, 2.563 s** —— 即每 element **0.21–0.79 s**，**没有单调预热收敛**。第 7 块（种子 13、14）比第 4 块慢一倍以上。因此"稳态"在此是分布而非常数：**element 成本随种子而变**（不同 Ancient 选项开出不同数量的嵌套提示，即不同 `run_step` 数）。这也是参考请求 B 只有两次运行的缘故——单次批量墙钟的可复现性尚未被更多轮次证实。

## 共享 PCK 指纹对照（实测）

| | 启动至 `hello` | `hello.pck_fingerprint` |
| --- | ---: | --- |
| 父进程先测量一次 | 1.752 s（一次性） | — |
| 把指纹交给 worker | **1.154 s** | `source: "pool"`, `bytes_hashed: 0` |
| 让 worker 自己算 | **2.547 s** | `source: "worker"`, `seconds: 1.381`, `bytes_hashed: 1901378340` |

**每 worker 省 1.393 s（启动的 54.7%）**，代价是父进程一次性 1.752 s。机制已存在于 [`NativeWorkerPool`](../../python/sts2_native_sim/client.py#L370-L393)（`workers > 1` 时测量一次并下传 hint），而 corpus 路径的默认工厂 [`scenarios.py:79`](../../python/sts2_native_sim/scenarios.py#L79) 造的是裸 `NativeWorker()`，未传 hint；[`_scenario_corpus.py:77-79`](../../python/sts2_native_sim/_scenario_corpus.py#L77-L79) 同理。

**推断：** 占参考请求 A 的 **21%**（1.393/6.574）；占参考请求 B 约 **3–7%**，因为 8 个 worker 的哈希本来就在并发中重叠。**不是**解决规模化问题的杠杆，但它是内循环最便宜的一步。

### 工单 01：corpus 批量共享 PCK 指纹（2026-09-25，基线 HEAD `a13ba39`）

**实测，单轮。** 在同一游戏 build 上先从改动前 HEAD 运行固定 A（1/2/4 worker）与 B（8 worker）请求，再用基准脚本的 `--fingerprint-comparison` 对同一请求交替运行旧的裸 worker 工厂（「旧路径」）和新的默认共享路径（「新路径」）。启动时间从每个 `NativeWorker()` 构造调用到 `hello` 返回；墙钟包含父进程的 PCK 测量、worker 启动、生成与 corpus 写入。每个配置的新旧 corpus，以及新 corpus 与改动前 HEAD 的 corpus，都对 `summary.json` 和所有压缩分片逐文件作 SHA-256 比较，**全部相同**。原始报告与产物保存在 gitignored 的 `artifacts/scenario-performance/results-ticket01-before-20260925.json`、`results-ticket01-comparison-20260925.json` 及其 corpus 目录。

| 请求 | worker | 改动前 HEAD 墙钟 | 旧路径墙钟 | 新路径墙钟 | 旧路径每 worker 启动中位（范围） | 新路径每 worker 启动中位（范围） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 6.655 s | 6.561 s | 6.565 s | 2.440 s | 2.417 s |
| A | 2 | 5.850 s | 5.654 s | 5.174 s | 2.551 s（2.547–2.555） | 1.144 s（1.137–1.150） |
| A | 4 | 5.341 s | 5.421 s | 4.921 s | 2.769 s（2.736–2.781） | 1.227 s（1.189–1.283） |
| B | 8 | 42.955 s | 41.137 s | 40.469 s | 3.313 s（3.283–3.348） | 1.460 s（1.440–1.491） |

新路径的 A/2、A/4、B/8 worker 均报告 `source: "pool"`、`bytes_hashed: 0`；旧路径每个 worker 均报告 `source: "worker"`、`bytes_hashed: 1901378340`。A/1 两条路径都让唯一 worker 自行计算，没有父进程测量。多 worker 的父进程指纹在启动分片前测量一次；离线测试用小型 PCK 和假 worker 断言这一次数以及向每个 worker 传递同一指纹。墙钟收益明显小于逐 worker 的启动差，因为旧路径的哈希并发重叠，而新路径包含一次父进程测量。单轮墙钟受运行抖动影响，不宜把这些差值当稳定加速比。

复现命令（在仓库根目录、通过 PowerShell 加载 `.env`）：

```powershell
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/tools/benchmark_scenario_generation.py <fresh-id> --rounds 1 --fingerprint-comparison'
```

## 已知超时缺陷（实测）

参考请求 B 之外单独复跑种子 `200150`（`IRONCLAD` / A0 / 1 worker）：

| 项目 | 值 |
| --- | ---: |
| 端到端墙钟 | **66.792 s** |
| scenario 行 / failure 行 | 2 / **1** |
| worker 替换 | **1** |
| 退出码 | 0 |

正常 element 为 0.406 s（单 worker 稳态），该 element **66.79 s，约 164 倍**。单次代价约等于整个 512-element 参考请求 B 的 **1.6 倍**。批处理仍以退出码 0 结束并把失败行写入分片，即**没有静默丢数据**；但 worker 被替换，且代价以超时（默认 `DIVINE_STS2_REQUEST_TIMEOUT=60`）计。

**发生率未知：** 参考请求 B 的 512 个 element（种子 1–128）为 0 失败，本次只确认了 1 个可复现种子。历史记录在[长批量试验](act1-first-combat-scenario-generator-memory.md#L55)中于第 150 个 element 遇到同一形态（`run_step` 60 s 超时，换新 worker 仍复现）。

### 种子 `200150` 的定位补测（2026-09-25，HEAD `e0948364`）

**实测。** 用全新 Godot worker 通过现有 `generate_rows` 驱动 `IRONCLAD` / A0 / `200150`，在每个 RPC 前后记录时间，并在客户端杀掉超时 worker **之前**读取 `process.poll()` 和 worker 的 stderr 尾部。前两个 Ancient 选项分别为 `GOLDEN_PEARL`、`NEOWS_TORMENT`，都进入首战并生成 scenario 行；第三个为 `LARGE_CAPSULE`，其 `choose_event` 在 0.010 s 内返回 `event_complete`，`leave_event` 在 0.001 s 内返回 `map_choice`，但首个 Monster 节点 `choose_map:0:1` 的 `run_step` 等待完整 60.0 s，最后生成 `stage: "first_combat"`、`kind: "request_timeout"`、`message: "run_step did not respond within 60.0 seconds"` 的 failure 行。该次探针从进程启动到失败行为 63.687 s，其中首战请求从 3.674 s 挂到 63.684 s；这不是新的 corpus 端到端基准，不能与上表的 66.792 s 混用。

超时即将触发客户端的 `_reap_process()` 时，`process.poll()` 为 `None`，即 worker **仍在运行但没有答复**；客户端随后杀掉它，`poll()` 变为退出码 1。worker 自己的 stderr 尾部只有 Godot 启动信息、迁移与语言加载信息，以及 `glam.png`、`energy_ironclad.tres` 两条资源缓存警告，没有异常、退出记录或入战进度。因而本次观测区分出「活着但沉默」，不能把客户端主动杀掉后的退出码误判为 worker 先崩溃。60 s 的等待也只能证明它没有在请求期限内完成，不能证明它永远不会完成。

**选择对照（实测）。** 同一 seed 的三个选项均被上次新 worker 运行选过。另开一个全新 worker，**只**取第三项，不经过前两项或 `restore`：`LARGE_CAPSULE` 正常返回 `event_complete`，打开的 Ancient 嵌套提示数为 0，离开房间后仍在 `choose_map:0:1` 卡住；10 s 的独立诊断期限内进程同样存活且日志无新异常。第三项在进战前持有 `BURNING_BLOOD`、`LARGE_CAPSULE`、`GAMBLING_CHIP`、`MERCURY_HOURGLASS`。故行为属于此 seed 的 **`LARGE_CAPSULE` 分支进入首战**，不是 Ancient offer 的生成、Ancient 嵌套提示或前两项遗留的 restore 状态。10 s 探针只作定位，不是建议的生产超时值。

**源码归因（由实测状态和代码推断，尚未以 native 堆栈证实）。** Shipped game 的 `GamblingChip.AfterPlayerTurnStart` 在第一回合调用 `CardSelectCmd.FromHandForDiscard`，等待一个卡牌选择。当前 [`EnterMapPointAsync`](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs) 直接 `await EnterRunMapCoordAsync`；后者进入 Monster 房间后直接 `await StartCombatInternal`。卡牌 selector 会建立待决选择及未完成的 `TaskCompletionSource`，但只有 [`StartTransitionAsync`](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs) 会在 native transition 与选择出现之间等待并把提示送回客户端。地图入战没有经过这层过渡协调，所以 `GAMBLING_CHIP` 的选择很可能使 `run_step` 一直等待，客户端只看见无响应。实测与这条路径吻合；具体停在 native 栈的哪一帧还未抓取。

**交给 [工单 03](../../.scratch/scenario-generation-throughput/issues/03-repair-first-combat-element-timeout.md) 的决定。** 采用 **native 侧过渡续接修复**：让地图入战的异步执行沿用现有 `StartTransitionAsync` / `ResumeChoiceAsync` 协议，在首回合遗物打开卡牌选择时返回可操作提示，并在选择后继续到稳定的战斗决策。随后由场景驱动明确处理这个首战提示及其可复现 recipe；若当前 row 格式无法忠实表达选择，就迅速生成该 Ancient 选项的 failure 行，保持 worker 可复用。**不**用全局短超时或盲重试掩盖这个确定性等待：短超时仍会杀 worker，重试会重复相同分支。fake worker 可离线验证生成器对「入战时出现卡牌提示」的 row/failure 行为与 worker 复用，但无法复现 shipped game 中 `GAMBLING_CHIP` 的异步等待；native 修复还需本 seed 的真机验收。观察到的发生率仍只有参考请求 B 的 **512/512 element 无失败**与请求外的 **1 个已知复现 element**，不能由此估计总体概率。

### 工单 03 的排除策略验收（2026-09-25）

工单 03 后来收敛为明确的排除策略，上段 native 续接建议是当时的诊断交接，不是本次实施方向。真机 `leave_event` 返回的**地图 observation 不含 relic inventory**；同一结果的 `scoring_features.relics` 列出 Ancient 结束后的完整持有集合，第三分支实测为 `BURNING_BLOOD`、`LARGE_CAPSULE`、`GAMBLING_CHIP`、`MERCURY_HOURGLASS`。生成器据此在发送第一战的地图节点动作前排除已知不支持的 `GAMBLING_CHIP`，写 `first_combat` / `unsupported_interactive_first_combat_relic` failure 行。没有缩短请求超时，也没有重试或改动 native 入战路径。

同一 Windows host 上，`IRONCLAD`、A0、run seed `200150`、单 worker 的端到端 corpus 结果：

| | 排除前（原基线） | 排除后（本票工作树） |
| --- | ---: | ---: |
| 墙钟 | **66.792 s** | **3.892 s** |
| scenario / failure 行 | 2 / 1（`request_timeout`） | 2 / 1（显式排除） |
| worker replacement | 1 | 0 |

墙钟约缩短 **17.2 倍**。排除后的单次运行由 [`scenario_interactive_relic_exclusion_acceptance.py`](../../tests/acceptance/scenario_interactive_relic_exclusion_acceptance.py) 通过 shipped game 的 corpus 公共接口验证；原基线是在较早的 `e0948364` 上测得，因此倍数是同机前后对照，不把两次 HEAD 之间的其他变更单独归因给本票。fake-worker 测试另行验证了间接授予遗物、后续 Ancient 选项与 element、零 replacement，以及相同请求的分片和 summary 字节同一。

## 成本归因：实测与推断的分界

**实测（单 worker、无争用、份额以生成为分母）：** `restore` 46.9%、`run_reset` 31.3%、`run_step` 21.3%，三者合计 99.5%。

**推断（把份额搬到参考请求 B）：** 启动按 A 的 2.585 s 计，占 B 的 41.26 s 的约 6%；生成因此约占 88–94%。据此 `restore` 约占 B 墙钟的 **41–44%**，`run_reset` 约 **28–29%**，`run_step` 约 **19–20%**。
**这条推断未经测量**：它假定三类 RPC 在 8 路争用下按同一比例变慢。若争用只打在某一类上，份额会移动。**但它有稳健的下界**：生成 ≥88% × `restore` 46.9% > **41%**，这一条不依赖比例假设，只依赖"生成占多数"。

由此，`restore` 与 `run_reset` **各自**都越过 Q13 门槛的 25%。

## Q13 门槛评估

| 条件 | 判定 | 依据 |
| --- | --- | --- |
| (i) 单一原因占批量墙钟 ≥25% | **满足** | `restore` ≥41%（稳健下界），`run_reset` ≈28–29%（推断） |
| (ii) 移除它可信地带来 ≥1.5× | **满足** | 补测证明那 ~200 ms 花在**重建**（95.3%）而不是重放（3.7%），且重建的是"一步之前还在同一进程里"的状态；最窄改动与验收见下。上界：仅去 `restore` 为 1/(1−0.42)=**1.72×** |
| (iii) 过字节同一 + 真机差分双门 | **可满足** | 本次 9 对分片/summary 字节同一；[`scenario_handle_reuse_acceptance.py`](../../tests/acceptance/scenario_handle_reuse_acceptance.py) 是现成的 native 差分 |

**结论（2026-09-25 补测后更新）：Q13 三个条件全部满足，"移除 `restore`"值得做。** 本文原来悬着的那一个事实已测——重建是真的，而且重建的正是重放解释不了的那部分开销；实现按此判定另开一张票。

### 待查的那件事：已测（2026-09-25 补测，基线 HEAD `0432993`，测的是本票改动的构建）

原问题只有两种答案，这一次补测把它分辨开：参考请求 A 的 8 次 `restore` 里快路径命中几次，以及那 ~215 ms 落在哪几个部件上。为此给 native 侧加了**开关式**逐部件计时（`STS2_RESTORE_PROFILE=1`，默认关闭；计时只随该次 `restore` 的 `transition` 回到调用方，不进任何 corpus），并用 [`python/experiments/scenario_restore_profile.py`](../../python/experiments/scenario_restore_profile.py) 驱动参考请求 A 三轮，逐次记录 RPC 墙钟与 worker 自报的部件耗时。分不清的归因不算数，所以每个数都来自打点，而不是由总数相减或推断。

**实测：命中 0/8。** 三轮各 8 次 `restore`，共 24 次，**resident-prefix 快路径命中 0 次**；每次重放的历史长度都是 **1**（进入 Ancient 房间的那一步 `choose_map`），即这 24 次全部走了 `ReconstructAsync`。

**实测：那 ~200 ms 是重建，不是重放。** 24 次 `restore` 的 worker 自报合计 4932.9 ms：

| 部件 | 合计 | 占比 | 单次（中位 / 最小–最大） |
| --- | ---: | ---: | ---: |
| `resident_check_ms`（resident-prefix 比较本身） | 0.5 ms | 0.01% | 0.0006 / 0.0004–0.16 |
| `run_rebuild_ms`（`Construct`：角色、牌组、遗物、run） | 44.1 ms | 0.9% | 1.40 / 1.20–4.41 |
| `map_rebuild_ms`（`InitializeRunMap` → `RunManager.Reset` + `GenerateRooms` + `GenerateMap`） | 4699.6 ms | **95.3%** | 154.6 / 37.6–379.1 |
| `replay_ms`（重放 checkpoint 的动作历史） | 182.8 ms | 3.7% | 7.38 / 6.83–9.29 |
| `capture_ms`（重建后的观察、合法动作与 hash） | 2.8 ms | 0.06% | 0.11 / 0.08–0.22 |
| 未被命名部件覆盖 | 3.1 ms | 0.06% | 0.006 / 0.004–0.99 |
| `total_ms`（每次 restore 的全部） | 4932.9 ms | 100% | 163.4 / 45.7–388.8 |

每 restore 的分布是偏的：总量除以 24 得**均值 205.5 ms**，而中位是 **163.4 ms**，两者都要读，不要拿一个当另一个。按 RPC 墙钟，单次 `restore` 为**中位 164.2 ms / 均值 209.1 ms**（46.5–401.0），24 次合计 **5.017 s**；worker 之外的部分（管道、协调器的投影与 hash）合计 **84.4 ms**，占 **1.7%**——协议开销不是成本，成本在 native 的重建里。本文件记录的参考请求 A `restore` ×8 = **1.720 s** 是三轮中位数，补测三轮各自为 **1.541 / 1.731 / 1.745 s**，与之吻合。

**判定：重建是真的，而且它重建的正是重放解释不了的那部分开销。** 原问题的第二种可能（"已经命中快路径，剩下的 215 ms 是重放本身不可省"）被两条实测排除：命中 0/8，重放占 3.7%。开销的 95.3% 是重跑这个 run 的 act——一个打点里的 `RunManager.Reset` + `GenerateRooms`（为**每个** act 抽事件与遭遇池）+ `GenerateMap`；三者没有被分开计时，所以这一条只能说"act 的重建占 95.3%"，不能说其中哪一段最多。同一个 element 里，act 因此被生成**三次**（一次 `run_reset` + 两次 `restore`），而三次生成的是同一个 run 的同一个 act。

**最窄的改动：把 combat 分支早就有的快照给 run-mode 分支。** `CaptureCombatSnapshot` 对 run-mode 的 recipe 直接返回 null（[`PersistentNativeCombatEnvironment.cs:3343-3348`](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L3343-L3348)），所以 run-mode 的 checkpoint 只能重建；而 combat 分支靠自己的快照跳过 `ReconstructAsync` 与重放（[`:649-682`](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L649-L682)）。两者的差就是这次测到的 ~200 ms：要恢复的状态一步之前还在同一进程里，重建只是把已经存在的东西再推导一遍。因此最窄的改动是让 `Branch` 的 checkpoint 也携带 run-mode 状态：在取 checkpoint 处捕获，在 `RestoreAsync` 里应用到活着的 run 上，而不是 `Construct` + `InitializeRunMap` + 重放，并照旧由 `ExpectedHash` 的分歧检查兜底。shipped game 自带这一类恢复路径（`SetUpSavedSingleplayer` / `SerializableActMap` 经 `SavedMapsToLoad` 重建 run 与地图，**不**重跑 `GenerateRooms`），是这条改动最省新表面的落点。

**验收：现成的两道门，补测都跑过。** [`scenario_handle_reuse_acceptance.py`](../../tests/acceptance/scenario_handle_reuse_acceptance.py) 是 native 差分（同 build 上逐行、逐编码字节等于 native fork 参考），补测通过：6 element / 18 行 / 12 次 `restore`，与参考计数一致。corpus 的字节同一（`corpus_differential: byte_identical: true`）是第二道：同一请求在 `STS2_RESTORE_PROFILE` 开与关下写出的 `worker-00.jsonl.gz` 与 `summary.json` 的 SHA-256 完全相同。这一条要说清它能证明什么：驱动从不读 `transition`（[`_scenario_driver.py:425`](../../python/sts2_native_sim/_scenario_driver.py#L425)），所以计时本来就没有进入行的路径，字节同一证明的是"开着开关跑出来的批量与关着时逐字节无法区分"，而不是"差点就漏进去了"。

### 工单 06：run-mode checkpoint 快照（2026-09-25，基线 HEAD `acd1ccf`）

**实测，参考请求 A，单 worker，三轮。** Ancient 入口的分支现在保存 shipped game 的 `SerializableRun`（含 `SerializableActMap`），恢复时走存档载入的 run/map 路径，不再运行 `GenerateRooms` 或重放动作；恢复后的 `ExpectedHash` 仍逐次检查，不匹配则回退到原来的重建和重放。快照仅用于本次生成器会保留的第一间 Ancient 房间入口；之后可能持有未序列化选择状态的事件分支继续走原路径。恢复时还需复制存档所共享的地图历史对象，并重绑牌组实例 ID，否则第一次分支运行会污染下一次恢复，或使首战行的编码字节变化。

同一探针 [`scenario_restore_profile.py`](../../python/experiments/scenario_restore_profile.py) 在外部生成器上计时，开 `STS2_RESTORE_PROFILE=1`，每轮 8 次 restore。`--capture-steps` 另在每步后读取 worker 诊断来归因快照捕获；其额外 RPC 不计入下表的无诊断生成时间。原始报告位于 gitignored `artifacts/scenario-performance/restore-profile-snapshot-final.json` 与 `restore-profile-snapshot-final-capture.json`。

| 参考请求 A，每轮 | 旧路径（工单 04） | 快照路径（工单 06） |
| --- | ---: | ---: |
| 热 worker 生成时间，三轮中位 | 4.049 s | 2.89 s（2.83 / 2.92 / 2.89） |
| 8 次 restore 的 RPC 墙钟，三轮中位 | 1.720 s | 0.139 s（0.141 / 0.139 / 0.131） |
| 每次 restore 的 worker 中位 / 均值 | 163.4 / 205.5 ms | 11.38 / 13.65 ms |
| 每次 restore 的 RPC 中位 / 均值 | 164.2 / 209.1 ms | 12.52 / 17.12 ms |
| 每轮 4 次快照捕获的 worker 成本 | 未付出 | 0.455 s（0.462 / 0.455 / 0.437） |

24 次 restore 的 worker 合计 **327.6 ms**：`snapshot_ms` 320.3 ms，`run_rebuild_ms` / `map_rebuild_ms` / `replay_ms` 均为 **0**，resident-prefix 命中仍为 **0/24**。相比旧路径每轮约 1.72 s 的 restore，新的约 0.139 s 节省约 **1.58 s**；每轮捕获增加约 **0.455 s**，净节省约 **1.13 s**。独立的完整生成时间中位下降 **1.16 s**，与逐项归因接近。这个前后对照复用了同一游戏 build 和固定请求，但不是交错运行的随机试验；净收益判定主要由 worker 对捕获和恢复的直接计时支持。

**验收。** `scenario_handle_reuse_acceptance.py` 通过，6 element / 18 行 / 12 restore，与原生 fork 参考逐行及编码字节相同；`scenario_record_acceptance.py --workers 1 --corpus ...` 通过已录制首战状态校验，并在同一构建、同一请求、同一 worker 数下两次写出字节相同的压缩分片和 summary。新增的 `run_checkpoint_snapshot_acceptance.py` 验证 Ancient checkpoint 的观察值、hash、合法选项相同，且返回 `snapshot_restore` / 0 个重放动作。

此项改动改变了 [ADR-0006](../adr/0006-model-run-decisions-as-one-active-state.md) 中“分支恢复继续重放”的既有决定：Ancient 入口快照现在先尝试原生存档载入，失败或 hash 不符时仍使用该 ADR 描述的重放路径。该决定的会话边界和不可序列化的嵌套选择续接保持不变。

## 建议

**建议做（与门槛无关，因为便宜且机制现成）：**

1. **把共享 PCK 指纹接到 corpus 路径**：在 `_native_worker` / `scenarios.py` 的默认工厂里，对整个批量测量一次 `PckFingerprint` 并下传。实测省 1.393 s/worker。离线测试用假 worker，不受影响；真机验收可用"分片字节同一"断言。
2. **先修超时缺陷再谈规模化**：单次 66.8 s 且换 worker，发生率未知。在它被理解之前，任何长批量（如 spec 的 10⁵ 行）的墙钟都不可预测。这属于缺陷诊断，不属于本方案。
3. **补上 run-mode checkpoint 的快照**：这是补测之后**唯一**越过 Q13 门槛的 native 改动——`restore` 占批量墙钟 ≥41%，而其中 95.3% 是重建一个一步之前还在进程里的 run（见上文"待查的那件事：已测"）。它比第 1 条贵得多，所以先用 native 差分与分片字节同一两道门把改动框住。

**建议不做：**

4. **不要为参考请求 A 优化。** 它的每 element 成本是稳态的 2.5 倍、是参考请求 B 每行成本的 20 倍；优化它等于优化预热。
5. **不追**已测掉的捷径：handle 复用（已做，+1.9%）、native batch RPC（1.03–1.05×）、以及完全绕过 shipped run 的 fast compiler（需 34×–101×，原型 2288 个叶字段只对上 6 个）。
6. **如果目标就是 spec 的"a few thousand records"，做到第 1、2 条即可停。** 实测 37.2 行/秒意味着 3000 行约 81 秒；第 3 条是给批量尺度上更快的余量，不是达标的前提。

**已被本次测量否证的假设：**

7. **`numpy`/`gym` 的导入时间开销**：实测 `pass` 0.053 s、`import sts2_native_sim` 0.344 s、`import sts2_native_sim.gym` 0.337 s、CLI 模块 0.524 s。gym 相对包本体**测不出额外时间成本**，故"懒加载 gym 能加快 CLI 启动"这条理由不成立。注意这只否证了**时间**：此前"父进程约 508 MiB 常驻来自 numpy"说的是**内存**，本文没有测量内存，该说法既未被证实也未被否证。

## 限制

- 参考请求 B 只有**两次**运行（41.487 / 41.033 s），不足以给出范围；参考请求 A 为三轮。
- 成本份额在**单 worker 无争用**下测得，搬到 8 worker 批量是推断，本文已标出稳健下界。
- 探针的每 element 漂移显示成本**随种子**变化（0.21–0.79 s）；本次未按 Ancient 选项数分层。
- 未做 CPU/内存 profiling，未测争用系数；`restore` 的快路径命中率与逐部件构成由文末补测回答（24 次全不命中），但补测只在单 worker、参考请求 A 上做，没有在 8 worker 争用下重测。
- `artifacts/scenario-performance/` 被 gitignore，原始 JSON 与 corpus 目录不在 checkout 内；可复现的结论以本文表格为准。
