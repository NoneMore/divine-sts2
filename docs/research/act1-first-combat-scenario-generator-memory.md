# 第一战场景生成器的空间开销与并发容量

**调查日期：**2026-09-24。对象是当前 `generate_corpus` 路径：Python 将请求分片，每个非空分片启动一个 Godot native worker，按 Ancient 选项生成首战场景并逐行写入 gzip。本文的容量判断先给出源码所能证明的上界与限制；具体机器可承载的 worker 数仍须用同一游戏 build、同一批量在目标机器测峰值。[corpus 调度](../../python/sts2_native_sim/_scenario_corpus.py#L32-L79)、[分片与写入](../../python/sts2_native_sim/_scenario_corpus.py#L92-L184)。

## 结论

**并发 worker 数决定主要的容量级别，但单 worker 长批量占用也会上升。** 每个非空待写分片有一个独立的 Godot 进程、游戏运行时和当前 run；一个元素的选项记录在 Python 中暂存为列表，然后逐行编码写入 gzip。worker 结束时关闭。`--workers` 并不提供单进程内并行；实际并发进程数是非空、尚未完成分片数的上界，至多为 `min(workers, 元素数)`。本机实测 32 worker 可同时生成 384 个成功场景，但单 worker 从启动到完成 128 个元素，私有提交内存由 93 MiB 增至 151 MiB；不能声称 worker 的长期占用恒定。[worker 构造](../../python/sts2_native_sim/_scenario_corpus.py#L64-L79)、[分片](../../python/sts2_native_sim/_scenario_corpus.py#L92-L112)、[逐元素写入和关闭](../../python/sts2_native_sim/_scenario_corpus.py#L147-L184)、[实测方法](../../python/tools/benchmark_scenario_memory.py)。

**这台 32 GiB、8 物理核主机已验证 32 worker 短批量可运行，尚未验证更大规模或长期稳态。** 每个 worker 都加载 PCK 资源包，并单独加载游戏程序集；`PersistentNativeCombatEnvironment` 是进程单例，GodotHost 的 RPC 循环一次处理一条请求，协调器也有串行信号量。由此可以确认横向扩容必须增加进程；但程序集/资源映射有多少物理页能跨进程共享，不能从这些源码推成固定 MB 数。实测给出的 32 worker 数字也不能直接迁移到不同主机或更长分片。[资源包加载及 worker 生命周期](../../src/Sts2.NativeSim.GodotHost/Main.cs#L20-L50)、[游戏程序集加载](../../src/Sts2.NativeSim.Core/NativeAssemblyContext.cs#L12-L20)、[进程单例](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L91-L101)、[RPC 循环](../../src/Sts2.NativeSim.GodotHost/Main.cs#L201-L259)、[协调器串行](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs#L19-L25)、[实测方法](../../python/tools/benchmark_scenario_memory.py)。

## 内存与生命周期模型

| 层级 | 存活对象及增长方式 | 证据 |
| --- | --- | --- |
| Python 主进程，请求级 | `ScenarioRequest` 保存输入序列；`_elements` 预先展开全部 `角色 × 进阶 × 种子`；`_Corpus` 再复制元素列表、为所有分片保存元素索引，并在 summary 中再次列出索引。因此元数据为 **O(E + W)**，`E` 为元素数、`W` 为声明的 worker 数；这并非纯流式输入。超大种子列表可能先耗尽 Python 内存或生成庞大 manifest，即使只开一个 worker。[请求元组](../../python/sts2_native_sim/_scenario_model.py#L197-L214)、[笛卡尔积展开](../../python/sts2_native_sim/_scenario_generation.py#L31-L41)、[分片索引](../../python/sts2_native_sim/_scenario_corpus.py#L92-L112)、[corpus 状态与 summary](../../python/sts2_native_sim/_scenario_corpus.py#L123-L141)。 |
| Python 分片线程，worker 级 | 一个非空分片持有一个 `NativeWorker`、两个管道读取线程、stdout 队列、至多 100 条 stderr 日志，以及最近状态 handle 的动作历史。handle cache 的默认上限为 8192 项，**跨 reset 不清空**，但容量封顶；第一战的动作历史较短，不能把 8192 项误读为 8192 份游戏状态。[客户端进程与缓存](../../python/sts2_native_sim/client.py#L80-L103)、[管道读取](../../python/sts2_native_sim/client.py#L136-L161)、[reset 和 handle 缓存](../../python/sts2_native_sim/client.py#L264-L266)、[LRU 上限](../../python/sts2_native_sim/client.py#L310-L313)。 |
| Python 分片线程，元素级 | `_rows_for_element` 为一个元素的全部 Ancient 选项构建 `rows` 列表；caller 随后逐行 JSON 编码并写入 gzip。单个 worker **不会在内存中积累整个 shard 的 observation**。直接调用 `generate_rows` 则把所有元素的行留在返回列表中，内存随总行数增长。[元素行列表](../../python/sts2_native_sim/_scenario_driver.py#L357-L390)、[逐行写 shard](../../python/sts2_native_sim/_scenario_corpus.py#L164-L182)、[gzip writer](../../python/sts2_native_sim/_scenario_store.py#L178-L202)、[`generate_rows` 汇集](../../python/sts2_native_sim/_scenario_generation.py#L16-L29)。 |
| native worker，当前 run | 环境保留当前 run/player/combat 对象及 ID 字典。reset 会清理 branch、ID 映射、历史等，并执行阻塞压缩式 Gen2 GC，然后构建新的 run/map。GC 只回收不可达对象；不能据此保证进程 working set 回到启动值。[环境字段](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L23-L51)、[reset](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L212-L244)、[GC 语义](https://learn.microsoft.com/en-us/dotnet/api/system.gc.collect)。 |
| native worker，分支 | 环境和协调器各有默认 8192 项的 LRU branch 表；协调器的每个 branch 存完整动作历史和 checkpoint，环境 branch 也存完整历史。当前 **run-mode** 的 `CaptureCombatSnapshot()` 直接返回 `null`，所以第一战场景的 handle 不会按选项持有完整 combat 快照；恢复 Ancient offer 会重建并重放。两层表均在下一次 reset 清空。[环境 branch 上限与记录](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L23-L29)、[branch 存储](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L3292-L3310)、[run-mode 无快照](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L3321-L3326)、[协调器 branch 上限与记录](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs#L13-L25)、[协调器 reset](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs#L138-L145)、[恢复重放](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L669-L791)。 |

按源码，可把峰值写成 `主进程的 O(E+W) 元数据 + 并发 worker 数 × (Godot/.NET/游戏基线 + 当前 run + 有界 branch/协议缓存) + 输出缓冲`。这只是结构模型，**不能从 O 记号计算可启动的 worker 数**。首战 observation 在 native 响应、Python 解码对象、成功 row 的深拷贝、JSON 行编码之间存在短时重叠，故应测包括进入 combat 与写入时刻的峰值，而非只测启动后 idle。[首战 response 与 row 深拷贝](../../python/sts2_native_sim/_scenario_driver.py#L475-L490)、[记录复制](../../python/sts2_native_sim/_scenario_driver.py#L593-L617)、[JSON RPC](../../python/sts2_native_sim/client.py#L179-L228)、[逐行写入](../../python/sts2_native_sim/_scenario_corpus.py#L164-L173)。

有一个值得在长批量曲线上留意的时序细节：`ResetState` 的强制 GC 发生在 `Construct` 之前；旧 `_run` 字段直到 `Construct` 中创建新 run 才被覆盖，`RunManager.State` 的旧引用也在更后面才清理。因此该次 GC 本身并不能证明上一元素的整个对象图已被回收；是否造成持续增长要看后续 GC 与实测，不能从代码断定泄漏。[reset 次序](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L212-L244)、[旧 run 替换与 manager 清理](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L851-L915)、[GC 不收集仍可达对象](https://learn.microsoft.com/en-us/dotnet/api/system.gc.collect)。

## 共享、复制和测量口径

worker 互相隔离的是可变游戏状态：Python 的 `NativeWorker` 各启一个进程，原生环境又明确只允许每进程一个实例。PCK 指纹的 SHA-256 用 1 MiB `FileStream` 顺序哈希，**指纹计算本身不把整个 PCK 读入托管堆**；但 Godot 的 `LoadResourcePack` 如何映射或缓存资源，仍须实测。当前 corpus 默认直接建 `NativeWorker()`，没有传 pool 的 PCK hint，所以每个新 worker 都会自行哈希 PCK；这是启动 I/O/CPU 成本，并非 `PCK 文件大小 × worker 数` 的已证实常驻内存。[独立进程](../../python/sts2_native_sim/client.py#L80-L92)、[进程单例](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L91-L101)、[hash stream](../../src/Sts2.NativeSim.Core/ReflectionTools.cs#L20-L25)、[PCK 指纹](../../src/Sts2.NativeSim.Core/NativePckFingerprint.cs#L42-L77)、[PCK 加载](../../src/Sts2.NativeSim.GodotHost/Main.cs#L34-L36)、[corpus 默认 worker](../../python/sts2_native_sim/_scenario_corpus.py#L75-L79)。

客户端的 `memory_bytes` 返回的是 Win32 `GetProcessMemoryInfo` 的 `WorkingSetSize`，只覆盖单个 Godot 子进程。Microsoft 文档说明 working set 包含共享页和私有页，所以简单相加多个 worker 的 working set 会重复计算共享驻留页；应同时记录每个进程的 `PrivateMemorySize64`、总物理内存压力、父 Python 进程，以及启动、首战峰值和长批量稳态。[客户端实现](../../python/sts2_native_sim/client.py#L329-L343)、[Microsoft WorkingSet64](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process.workingset64)、[Microsoft PrivateMemorySize64](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process.privatememorysize64)。这里的测量建议是根据这些口径作出的推论；working set 不等于独占物理内存，private bytes 也不是物理驻留量。

## 对大规模并发的判断

1. **大批量、有限并发：结构上可行，但常驻内存不应视为恒定。** corpus 行是逐元素写入，已完成场景不会全部留在 Python 分片线程内存；native run 在下个元素 reset。128 元素实测仍观察到 worker 内存增长，因此长分片需要另设内存/运行时长监控；总元素数 `E` 也须控制在主进程可承受的 manifest 大小内。[分片写入](../../python/sts2_native_sim/_scenario_corpus.py#L164-L184)、[reset 清理](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L212-L244)、[预展开](../../python/sts2_native_sim/_scenario_generation.py#L31-L41)、[实测方法](../../python/tools/benchmark_scenario_memory.py)。
2. **几十个 worker 同时运行：本机短批量已通过。** 1、4、8、16、32 worker 各处理每 worker 4 个元素时，全部成功；32 worker 的进程树私有提交内存采样峰值约 3.33 GiB，父进程加 worker 合计约 3.86 GiB。32 worker 的生成段吞吐为 23.3 行/秒，较 16 worker 的 18.0 行/秒只高约 29%，增加并发仍有收益但已明显递减。上述测量是独立轮次、不同种子集合的短批量，不是 corpus 端到端压缩输出基准，也不能证明 64/100 worker 的稳定性。[进程调度](../../python/sts2_native_sim/_scenario_corpus.py#L64-L79)、[实测方法](../../python/tools/benchmark_scenario_memory.py)。
3. **过量 `--workers` 还会放大主进程元数据与文件数量。** 空分片不启动 native worker，但仍建 shard 文件并进入 summary；因此 worker 数超过元素数不会增加计算并发，却增加 artifact/manifest 开销。[空分片约定](../../python/sts2_native_sim/_scenario_corpus.py#L92-L112)、[仅非空分片启动进程](../../python/sts2_native_sim/_scenario_corpus.py#L164-L167)、[summary 条目](../../python/sts2_native_sim/_scenario_corpus.py#L207-L238)。

## 本机实测

在 2026-09-24 的 Windows 主机（31.9 GiB RAM、8 物理核/16 逻辑核）上，使用当前游戏 build 与 [基准脚本](../../python/tools/benchmark_scenario_memory.py)。每个 worker 连续运行 4 个不同种子的 `generate_rows`，每种子产生 3 个成功场景；各并发档次顺序运行，32 worker 档次为另一次运行。脚本每 50 ms 采样 Python 的整个 Godot 子进程树，记录 Win32 private bytes 与 working set；启动完成及生成结束还逐 worker 取快照。进程树口径很重要：在本机，`NativeWorker.process` 指向的启动包装进程本身仅约 1.2 MiB private bytes，实际 Godot 运行在后代进程中。脚本源码保留了方法；原始 JSON 位于本机 gitignored 的 `artifacts/scenario-performance/memory-20260924-150534.json` 与 `memory-20260924-151132.json`。

| 并发 worker | 成功场景 | 并发启动时间 | 生成时间 | 生成段行/秒 | 启动后每 worker 私有提交中位数 | worker 私有提交采样峰值合计 | worker working set 采样峰值合计 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 12 | 2.49 s | 4.16 s | 2.9 | 92.6 MiB | 117 MiB | 225 MiB |
| 4 | 48 | 3.13 s | 5.59 s | 8.6 | 92.6 MiB | 449 MiB | 869 MiB |
| 8 | 96 | 4.67 s | 7.59 s | 12.6 | 92.6 MiB | 894 MiB | 1739 MiB |
| 16 | 192 | 7.47 s | 10.65 s | 18.0 | 93.0 MiB | 1753 MiB | 3438 MiB |
| 32 | 384 | 13.06 s | 16.48 s | 23.3 | 93.3 MiB | 3334 MiB | 6839 MiB |

32 worker 在生成结束时每 worker 的私有提交内存为 100.0–115.0 MiB（中位数 102.2 MiB）；Python 父进程从约 508 MiB 增到 523 MiB 私有提交，采样到的父子合计峰值为 3859 MiB。脚本读取的是 psutil 在 Windows 上的 `private` 与 `rss`（后者是 `wset` 的别名）；working set 的合计数会重复计入进程间共享页，不能直接当作实际物理 RAM 使用量；private bytes 是提交量，也不能直接当作常驻 RAM。[psutil 官方指标说明](https://psutil.readthedocs.io/stable/#psutil.Process.memory_info)、[Win32 指标语义](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process.privatememorysize64)、[working set 语义](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process.workingset64)、[测量实现](../../python/tools/benchmark_scenario_memory.py)。

父进程的约 508 MiB 启动私有提交并非全由场景请求造成：导入 `sts2_native_sim.scenarios` 会先执行包的 `__init__`，尝试导入 `gym`，从而加载 NumPy。隔离导入实验中 Python 基线为 8 MiB private / 15 MiB working set；导入 NumPy 后约 500 MiB private / 28 MiB working set；再导入 scenarios 后约 506 MiB private / 36 MiB working set。这个数字与 NumPy/其依赖的虚拟内存分配有关，不能解释成 500 MiB 物理内存。[包入口](../../python/sts2_native_sim/__init__.py#L1-L10)、[gym 的 NumPy 导入](../../python/sts2_native_sim/gym.py#L10)、[基准入口](../../python/tools/benchmark_scenario_memory.py)。

单个 worker 的长批量试验使用另一组连续种子，不累积返回的 rows：完成 0、1、4、16、64、128 个元素后，进程树私有提交分别为 **92.6、120.6、109.3、111.6、124.6、151.0 MiB**，working set 分别为 **183.5、225.6、215.9、219.7、237.7、266.3 MiB**。这说明前 128 元素未呈现稳定的平台，但不证明线性泄漏；JIT、GC 提交高水位、游戏缓存等尚未区分。原始 JSON 为本机 gitignored 的 `artifacts/scenario-performance/memory-20260924-150735.json`。[长批量测量入口](../../python/tools/benchmark_scenario_memory.py)、[reset 清理与 GC 时序](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L212-L244)。

试图延长到 256 元素的另一轮在第 150 个元素遇到 `run_step` 60 秒超时，worker 退出；将该种子 `200150` 放在**全新 worker** 上仍复现：两个场景成功，第三个在 `first_combat` 产生 `request_timeout` 失败行。因此这轮中断不能归因于长批量内存增长，也没有提供 256 元素的内存趋势。corpus 的 worker 退出处理会替换 worker 并继续后续元素，但失败行仍会保留。[客户端请求超时](../../python/sts2_native_sim/client.py#L179-L228)、[worker 替换](../../python/sts2_native_sim/_scenario_corpus.py#L147-L184)、[探针入口](../../python/tools/benchmark_scenario_memory.py)。

**实际容量判断：**这台主机可支持至少 32 个 worker 的短批量并发，内存没有成为本次实验的限制；按本机运行反馈，高并发时 CPU 已吃紧，32 worker 的启动和生成耗时也随并发显著增加。脚本没有采集 CPU 利用率。作为当前运行建议，先将 `--workers` 限制在 **4–8**，其余元素排队写入分片：本次生成段 4/8 worker 分别为 8.6/12.6 行/秒；是否取 8 取决于同机任务需要保留多少 CPU。若要把“大规模”定义为长期运行的几十至上百 worker，需要再测目标机器上的较长分片、系统可用内存/分页、超时及替换率，并设定可接受的吞吐收益和内存预算。现有证据不支持给 100 worker 一个可靠的容量承诺。
