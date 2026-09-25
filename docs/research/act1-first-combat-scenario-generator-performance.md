# 第一战场景生成器的性能开销

> 本文是 `2083a109` 版本的历史测量；该版本每个 Ancient 选项都 reset 一次。
> 当前生成器已改为每个元素 reset 一次、其余选项 restore，并复用进入 Ancient
> 时返回的 `state_handle`。当前实测与旧新 native 差分见
> [handle 复用测量](act1-first-combat-scenario-handle-reuse.md)。

**调查版本：** `2083a1097ce736e0a726cb350d70adc0d9435931`（2026-09-24）。本文把源码可确定的成本、已有测量和本次实测分开；耗时归因均需以本次实测为准。

## 结论

生成器的重复工作单位是 **一个 Ancient 选项，而不是一个种子**：对同一角色、进阶和种子，首个选项完整驱动一次，此后每个选项又从 `run_reset` 开始驱动一次。每次成功驱动至少有 **1 次 reset + 4 次 step**（进入 Ancient、选选项、离开事件、进入首战），嵌套选择再增加 step。因此，若一个元素提供 `k` 个选项，最低是 `k` 次 reset 与 `4k` 次 step；这是由调用路径推得的下界，不是测量值。每次 reset 又在原生环境中显式调用阻塞、压缩式 Gen2 GC，所以 GC、重建 run/map、每个决策的状态捕获，以及 Python↔Godot JSON 往返都是重复成本。[选项循环](../../python/sts2_native_sim/_scenario_driver.py#L357-L385)、[驱动步骤](../../python/sts2_native_sim/_scenario_driver.py#L415-L476)、[嵌套步骤](../../python/sts2_native_sim/ancient.py#L114-L140)、[reset 与 GC](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L205-L244)。

## 调用链和成本模型

1. CLI 将角色、进阶、种子展开为笛卡尔积；默认 1 个 worker、gzip 级别 3。`generate_corpus` 按元素连续分片，以线程并行运行待写的分片；每个非空分片启动一个独立、持久的 Godot native worker。[CLI 参数](../../python/sts2_native_sim/cli.py#L125-L174)、[展开](../../python/sts2_native_sim/_scenario_generation.py#L31-L41)、[并行与 worker](../../python/sts2_native_sim/_scenario_corpus.py#L32-L79)、[分片](../../python/sts2_native_sim/_scenario_corpus.py#L92-L112)。
2. 每个 worker 初始化时检查游戏 assembly 和 PCK 指纹；场景 CLI 创建的是独立 `NativeWorker()`，没有给它传 pool 的共享 PCK hint。因此非空分片数增加时，冷启动与 PCK 指纹工作也会增加；PCK hint 命中与否可从 worker 的 `hello.pck_fingerprint` 判断。[独立 worker](../../python/sts2_native_sim/scenarios.py#L68-L81)、[客户端启动和 hello](../../python/sts2_native_sim/client.py#L80-L109)、[指纹读取](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L91-L111)、[hint 校验与回退哈希](../../src/Sts2.NativeSim.Core/NativePckFingerprint.cs#L42-L77)。
3. 一个选项的 `run_reset` 通过 JSON 行协议进入 GodotHost、`NativeRunCoordinator`、`PersistentNativeCombatEnvironment.RunReset`。原生 reset 清理状态、强制 GC、构建 run、初始化地图，然后捕获初始决策。[Python RPC](../../python/sts2_native_sim/client.py#L179-L241)、[Godot 分派](../../src/Sts2.NativeSim.GodotHost/Main.cs#L201-L230)、[协调器](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs#L119-L145)、[环境 reset](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L212-L244)。
4. 每次 `run_step` 都通过同一 JSON RPC 往返；原生适配器重算投影 hash 以检查一致性，协调器又为响应计算状态 hash、生成分支 handle。Python 端还为 reset 输入做深拷贝、维护动作历史。由此推断，`transition.elapsed_ms` 不能单独代表 Python 调用的完整 wall time：协调器的 Stopwatch 在 `Project` 前已停止，且不包含 Python JSON 编解码和管道传输。[客户端协议和记录](../../python/sts2_native_sim/client.py#L179-L228)、[客户端 reset/step](../../python/sts2_native_sim/client.py#L235-L283)、[适配器 hash](../../src/Sts2.NativeSim.Core/RunSession/NativeRunAdapter.cs#L70-L92)、[协调器计时与投影](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs#L174-L202)、[状态 hash/handle](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs#L268-L343)。
5. 成功行把完整 combat observation 深拷贝到记录，并递归扫描是否包含 float；随后按声明顺序 JSON 编码，逐行写入 gzip 分片。每分片还做原子替换和 summary 写入。记录越大，这些 Python、压缩与磁盘成本越高；源码只能证明它们存在，不能证明它们是主热点。[建行](../../python/sts2_native_sim/_scenario_driver.py#L580-L605)、[编码](../../python/sts2_native_sim/_scenario_codec.py#L58-L106)、[float 扫描](../../python/sts2_native_sim/_scenario_codec.py#L127-L145)、[逐行写入](../../python/sts2_native_sim/_scenario_corpus.py#L147-L182)、[gzip writer](../../python/sts2_native_sim/_scenario_store.py#L179-L202)。

可用以下模型解释总 wall time，其中 `E` 为非空元素数、`K_i` 为第 `i` 个元素的 Ancient 选项数、`N_ij` 为第 `j` 个选项的嵌套 step 数：`RPC 数下界 = Σ_iΣ_j(5 + N_ij)`，`run_reset 次数 = Σ_i K_i`。首个驱动若未读到 Ancient 选项，只产出一个失败行；已读到选项后，后续选项即使失败也继续驱动。[首个驱动与后续选项](../../python/sts2_native_sim/_scenario_driver.py#L357-L398)、[固定步骤](../../python/sts2_native_sim/_scenario_driver.py#L421-L463)、[嵌套步骤](../../python/sts2_native_sim/ancient.py#L129-L140)。

## 现有测量能说明什么

仓库已有一组 **实机 parity** 测量：16 个样本在复用模式下总 wall time 81.60 秒，native pool 只哈希一次 PCK；这是 shipped-game 校验的端到端时间，包含实机进程和字段比对，不能直接当作本生成器的速度。该笔记也说明单个独立 `NativeWorker` 仍自行哈希 PCK。[实机校验测量](shipped-game-validation-process-performance.md#2026-09-24-后续验证)。

当前生成器的 summary 记录成功/失败行数、元素数、worker 数、压缩等级和 worker 替换数，但不记录启动、reset、step、编码或总 wall time。因此必须对完整调用作外层计时，并用成功行数及失败行数确认吞吐量的分母。[summary 结构](../../python/sts2_native_sim/_scenario_corpus.py#L210-L248)、[CLI 输出](../../python/sts2_native_sim/cli.py#L159-L182)。

## 本次同机实测

2026-09-24 在同一 Windows 10 build 19045 主机（8 物理核/16 逻辑核、31.9 GiB RAM、Python 3.13.5）、同一游戏 build 上连续测 3 轮。游戏 assembly SHA-256 以 `A1F9E653` 开头、PCK SHA-256 以 `42520EB8` 开头，和仓库的[先前实机记录](../research/simulator-vs-shipped-game-parity-verification.md)一致。请求固定为 `IRONCLAD × Ascension 0 × {A1B2C3D4E5, 1, 2, 3}`，gzip 级别 3；每种子提供 3 个 Ancient 选项，四种子共生成 12 个成功行、0 个失败行。每轮先单独启动一个 `NativeWorker`，在这个 worker 上按种子顺序调用 `generate_rows`，以 `time.perf_counter()` 测外层耗时，并包装 `worker.request()` 汇总 `run_reset`/`run_step` 的 Python 侧 RPC wall time；随后为 1、2、4 worker 的完整 `generate_corpus` 各使用新的输出目录。源码入口见[测量脚本](../../python/tools/benchmark_scenario_generation.py)；三轮原始结果见[第 1 轮](../../artifacts/scenario-performance/results.json)、[第 2 轮](../../artifacts/scenario-performance/results-r2.json)、[第 3 轮](../../artifacts/scenario-performance/results-r3.json)。这些 `artifacts/` 文件被 git 忽略，表内数值和方法写在本文以保留结论。

| 项目 | 三轮中位数 | 三轮范围 |
| --- | ---: | ---: |
| 单个新 native worker 启动至 `hello` 完成 | 2.466 秒 | 2.466–2.508 秒 |
| 同 worker 生成 4 元素、12 行（不含启动/关闭） | 3.901 秒 | 3.840–4.217 秒 |
| 其中 12 次 `run_reset` RPC 合计 | 2.674 秒 | 2.618–3.040 秒 |
| 其中 57 次 `run_step` RPC 合计 | 1.215 秒 | 1.170–1.221 秒 |
| 完整 corpus，1 worker | 6.563 秒 | 6.563–6.842 秒 |
| 完整 corpus，2 workers | 5.745 秒 | 5.651–5.844 秒 |
| 完整 corpus，4 workers | 5.330 秒 | 5.315–5.424 秒 |

| 轮次 | 启动 | `generate_rows` | reset RPC | step RPC | corpus 1/2/4 workers |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.466 | 3.901 | 2.674 | 1.221 | 6.842 / 5.844 / 5.424 |
| 2 | 2.508 | 3.840 | 2.618 | 1.215 | 6.563 / 5.745 / 5.330 |
| 3 | 2.466 | 4.217 | 3.040 | 1.170 | 6.563 / 5.651 / 5.315 |

本表单位均为秒；它将 gitignored 原始 JSON 的主要耗时保存在受跟踪文档中。[逐轮测量脚本](../../python/tools/benchmark_scenario_generation.py)。

另一次独立的 `NativeWorker().hello()` 读取到 `pck_fingerprint = {source: "worker", seconds: 1.3410061, bytes_hashed: 1901378340}`，即该 worker 对约 1.90 GB PCK 自行哈希，耗时 1.34 秒。它不属于上表三轮，不能拿 1.34 秒直接从三轮 startup 中相减作为精确阶段归因；`source`、`seconds` 和 `bytes_hashed` 是原生 `hello` 明确报告的字段。[hello 字段](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L104-L112)、[哈希计时](../../src/Sts2.NativeSim.Core/NativePckFingerprint.cs#L74-L77)。

在同一 worker 的 `generate_rows` 段，`run_reset` RPC 占每轮外层时间的 **68.2%–72.1%**，`run_step` 占 **27.8%–31.6%**；二者合计几乎覆盖全部生成时间。以三轮中位数算，一次 reset RPC 约 223 毫秒，一次 step RPC 约 21 毫秒，但两者分布明显不均，不应把均值当作典型请求延迟。固定顺序测试中首个种子耗时 **2.004–2.145 秒**，后三种子各 **0.298–0.998 秒**。[三轮逐种子数据](../../artifacts/scenario-performance/results.json)、[第 2 轮](../../artifacts/scenario-performance/results-r2.json)、[第 3 轮](../../artifacts/scenario-performance/results-r3.json)。

另做一次反序辅助检查：在新 worker 上按 `3, 2, 1, A1B2C3D4E5` 顺序调用，启动 2.483 秒，各元素依次 **1.307、1.487、0.487、0.556 秒**，每个仍产 3 个成功行。这是当次控制台记录，未另存结果文件。原先在首位的 `A1B2C3D4E5` 移到末位后只用 0.556 秒，说明固定顺序中的首元素劣势不能归因于该种子本身；该反序结果只有一轮，不计入上表统计。测试未分离 JIT、游戏模型惰性初始化、GC、文件缓存等因素，故也无法确定预热效应的具体机制。

按三轮中位数，2 workers 比 1 worker 的端到端时间少 **12.5%**，4 workers 少 **18.8%**；4 workers 的吞吐量约 **2.25 行/秒**，1 worker 约 **1.83 行/秒**，加速为 **1.23 倍**，远小于 worker 数的 4 倍。三种配置每轮都为 12 成功、0 失败、0 worker 替换，因而差异不是少写记录所致。这些只是四元素小批量、固定顺序运行各三次的同机结果；更多 worker 同时承担各自的启动和 PCK 指纹成本，而实验未独立计量每个 corpus worker 的启动、PCK hash、CPU 或 I/O。[完整 corpus 原始结果](../../artifacts/scenario-performance/results.json)、[第 2 轮](../../artifacts/scenario-performance/results-r2.json)、[第 3 轮](../../artifacts/scenario-performance/results-r3.json)、[独立 worker 构造](../../python/sts2_native_sim/_scenario_corpus.py#L64-L79)。

### 复现与限制

在已按[开发环境说明](../agents/dev-environment.md)配置好游戏、Godot 和 Python 的主机上，于项目根目录运行受跟踪的[基准脚本](../../python/tools/benchmark_scenario_generation.py)：

```powershell
python python/tools/benchmark_scenario_generation.py r4 --rounds 3 --legacy-comparison
```

脚本加 `--legacy-comparison` 后先新建一个 `NativeWorker` 并计时启动，再在同一 worker 上按四个种子分别调用 `generate_rows`，用 `time.perf_counter()` 包装 `worker.request` 记录 `run_reset`/`run_step` wall time；随后按 1、2、4 workers 的顺序运行 `generate_corpus`。运行三次时改用 `r4`、`r5`、`r6` 等新标签，分别生成全新 `corpus-*-<标签>` 目录与 `results-<标签>.json`，再对三轮取中位数及范围。同一标签重跑会被脚本拒绝，以免把续跑计作完整生成耗时；本次三轮原始 JSON 只存于本机 gitignored `artifacts/`，仓库 checkout 不包含它们。[脚本](../../python/tools/benchmark_scenario_generation.py)、[续跑条件](../../python/sts2_native_sim/_scenario_store.py#L103-L133)。

此次 `run_reset`/`run_step` 是 Python RPC wall time，包含 JSON 编解码和管道往返，不能据此把 68%–72% 全归于 GC 或游戏构建。worker 启动时间也包含 Godot 进程启动、原生环境初始化与 `hello`，不能仅归于 PCK hash。完整 corpus 的时间还包含 worker 启动/关闭、行编码、压缩和 summary 写入，且其 1/2/4 worker 测试始终按该顺序进行；本次没有随机化顺序，没有隔离系统负载，也没有 CPU/内存 profiling。没有使用客户端的 `worker_memory_bytes`，因此本文不报告内存开销。[RPC 计时边界](../../python/sts2_native_sim/client.py#L179-L228)、[worker 初始化](../../python/sts2_native_sim/client.py#L80-L109)、[corpus 边界](../../python/sts2_native_sim/_scenario_corpus.py#L32-L74)。
