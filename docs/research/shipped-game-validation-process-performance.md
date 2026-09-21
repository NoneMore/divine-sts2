# 实机游戏校验为什么反复启动、终止进程

**仓库修订：** `git rev-parse HEAD` = `801f7dea6326a3a59dcbbd83bd4d641949c8ec3d`
（`Close module decoupling tools plan`，2026-09-21）

**调查范围：** 当前唯一留下过 simulator↔shipped-game 字段级比对结果的入口
`tests/acceptance/parity_run_acceptance.py`，以及它直接调用的 full-app client、bridge server、
sandbox 代码。其它实机 acceptance 只用于比较其进程生命周期是否相同。

## 结论

**是，当前字段级实机校验有一个明确而且量级不小的性能问题：默认完整运行会串行冷启动并终止
16 个 `SlayTheSpire2.exe`。** 这不是进程崩溃后的重试，也不是进程池替换；它是测试入口当前写死的
生命周期：14 个 parity sample 每个一个新进程，再加 2 个 Act-variant probe 每个一个新进程
（`tests/acceptance/parity_run_acceptance.py:187-213,658-671`）。

已有本机记录测得单个 full-app worker 到 ready 约 **4.8–5.2 秒**
（`.scratch/act1-combat1-scenarios/parity-findings.md:61`）。只按这段启动时间外推，16 次启动就是约
**77–83 秒**；还没有计入走到第一场战斗、逐字段投影/比较、sandbox 准备和关闭。一次留下 mismatch dump
的 14-sample 运行中，相邻 sample 的 bridge 文件时间差为 **16.44–19.59 秒，平均 17.67 秒**，首末
相隔 **229.65 秒**（`artifacts/parity-run/dump/*.bridge.json` 的 mtime）。这组时间还包含游戏内 drive
和 dump，因此不能把 17.67 秒全算成启动成本；但它证明完整串行路径确实是分钟级，而非仅仅视觉上
频繁闪过进程。

更关键的是，每个新进程还会重新流式读取并 SHA-256 整个 `SlayTheSpire2.pck`。当前 PCK 是
**1,901,378,340 bytes**（十进制 1.90 GB，约 1.77 GiB）；bridge 的 `Lazy<GameBuildDto>` 只保证同一
进程测一次，进程退出后没有跨进程缓存（`src/Sts2.NativeSim.FullAppBridge/GameBuild.cs:15-24,30-49`）。
默认 16 个真机进程因此逻辑上重复读取/哈希 **30.42 GB（约 28.33 GiB）**。2026-09-21 在本机用
`Measure-Command { Get-FileHash -Algorithm SHA256 <PCK> }` 单独测得一次 **4.12 秒**，约 440 MiB/s；
机械外推 16 次是 **65.9 秒**。这不是完整运行的严格分项测量——OS page cache 会改变物理磁盘 I/O，
同时运行环境也不同——但 SHA 计算和内存带宽不会被 page cache 消除，量级足以说明重复 fingerprint
很可能与冷启动本身同属首要热点。

重复终止同样是预期代码路径。client 先发 `close` RPC，server 安排 50 ms 后
`Environment.Exit(0)`，但 client 收到响应后会立即再调用 `Popen.terminate()`，等 2 秒仍未退出才
`kill()`（`src/Sts2.NativeSim.FullAppBridge/FullAppBridgeServer.cs:266-272`；
`python/sts2_native_sim/full_app_client.py:301-340`）。因此观察到每个游戏进程被启动后又终止，与源码
完全一致。

## 默认调用链和精确进程数

1. `main()` 建立 `NativeWorkerPool(--workers)`，默认 3 个 native/Godot worker，用于先生成记录；
   `_records()` 会把 10 个 distinct run 轮流交给这 3 个持久 worker
   （`parity_run_acceptance.py:221-243,628,651-656`）。
2. `main()` 对 14 个 `SAMPLE` 做普通的 Python `for` 循环；每次 `_sample_result()` 都新建
   `FullAppBridgeClient`、调用 `launch()`、drive 到战斗，并在 `finally` 调用 `close()`
   （`:474-506,658-664`）。这里没有 executor，也没有 full-app pool。
3. 随后对 2 个 `VARIANT_PROBES` 再做一个串行 `for` 循环。每个 probe 进入 `_launched()` 时同样
   launch 一个新进程，离开 context 时 close（`:509-568,666-671`）。
4. 所以默认真机进程启动数为 `14 + 2 = 16`，峰值真机并发数为 **1**；每个进程只服务一个
   sample/probe。`--workers` 只改变记录侧 native worker 数，**不会**减少真机进程数，也不会提高真机
   侧并发。

默认 3 个 native worker 也各自在 `PersistentNativeCombatEnvironment` 构造时哈希一次 assembly 和 PCK
（`src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs:90-100`；
`src/Sts2.NativeSim.Core/ReflectionTools.cs:20-24`）。因此一次默认 parity 从头运行总共会出现 **19 次**
PCK hash，逻辑数据量 **36.13 GB（约 33.64 GiB）**；按上述独立单次测量仅作为量级外推约 **78.3 秒**。
native 侧好于真机侧之处是这 3 个 worker 随后会复用，不会按 10 个 distinct run 重启。

缩小运行时，真机启动次数可直接由参数算出：

- `--limit N`：`N + 2` 次（除非再加 `--no-probes`）；
- `--only LABEL`：1 次，代码会自动不跑 probe；
- `--no-probes`：完整 sample 为 14 次；
- `--limit N --no-probes`：N 次。

这些分支见 `parity_run_acceptance.py:630-650`。失败也不会自动重试：`_sample_result()` 捕获异常、记录
该 sample 失败然后继续下一个（`:500-505`）；`launch()` 内只是轮询 port file 和 TCP 连接，没有再次
`Popen`（`full_app_client.py:187-256`）。因此“反复启动”是逐 sample 执行，不是 retry storm。

## 每次冷启动实际做了什么

每次 `launch()` 都会：

- 调 `prepare_sandbox()`；遍历安装根目录，把顶层文件硬链接到独立 `worker_N`，并把两个安装目录做
  junction。已经存在的 link/junction 会跳过，所以同一 worker id 的后续运行是幂等复用，不会再次
  复制游戏（`python/sts2_native_sim/full_app_sandbox.py:86-109`；
  `tests/test_sandbox.py:44-52`）。
- 复制 protocol/bridge mod package 的顶层文件，清除该 sandbox 的 save，读取真实 profile 的
  `settings.save`，再写隔离 settings（`full_app_client.py:123-176`）。
- 启动真实 sandbox 中的 `SlayTheSpire2.exe --headless --force-steam=off`，最多等 30 秒 port file，
  再最多等 15 秒 TCP 连接（`:187-256`）。
- 第一次生成 observation 时访问 `GameBuild.Current`，触发 per-process `Lazy` fingerprint：先哈希游戏
  assembly，再以 1 MiB `FileStream` buffer 流式哈希 PCK
  （`src/Sts2.NativeSim.FullAppBridge/FullAppStateTracker.cs:42-50`；
  `src/Sts2.NativeSim.FullAppBridge/GameBuild.cs:21-24,30-49`）。parity 不调 `hello()`，所以这笔成本发生在
  `start_run()` 等待第一 observation 的过程中，而不是 port ready 之前
  （`parity_run_acceptance.py:326-327,496-499`）。
- 每个 sample 使用不同 worker id（默认从 11 递增），因此一次完整运行会涉及 16 个独立 sandbox
  目录（`parity_run_acceptance.py:629,659-670`）。安装本体是 hard link/junction，不是 16 份数据；
  但 userdata、日志、mod 文件和文件系统元数据仍各自存在。

这里已证实的主要固定成本是完整游戏进程冷启动，加上每个新进程重复哈希 1.77 GiB PCK，而不是复制
11 GB。当前 sandbox 实现明确禁止跨卷后回退到 copy，并已有测试保证“链接失败就报错且不复制”
（`full_app_sandbox.py:58-83`；
`tests/test_sandbox.py:55-73`）。历史上曾经存在的跨卷 copy 问题不是 HEAD 的当前行为。

## 为什么现在不能简单把一个 client 移出循环

bridge 的公开 Python API 看起来可以重复调用 `start_run()`，但 server/游戏侧目前实际上是 one-shot：

- 游戏到 main menu 后，`StartAfterMainMenuAsync()` 只等待第一次 `IsRunStarted`，读取一次 seed，构造
  一个 `AutoSlayer` 并调用一次 `Start()`；它没有循环，也没有返回 lobby 后开始下一 run 的路径
  （`src/Sts2.NativeSim.FullAppBridge/FullAppBridgeMod.cs:141-159`）。
- `start_run` RPC 只改 requested 参数、替换 `_initialBoundaryTcs`、把 `IsRunStarted` 置 true，然后等
  新 boundary；它没有结束旧 run、清游戏单例或再启动 `AutoSlayer`
  （`FullAppBridgeServer.cs:183-209`）。
- `ActionHistory` 和 `StateHashHistory` 是进程级静态列表，也没有在 `start_run` 时清空
  （`:40-49,255-264`）。

所以“让 16 个样本共用一个现有进程”不是 acceptance 脚本的一行改动；按当前协议，第二次
`start_run()` 很可能等待一个不会按新请求产生的 initial boundary。要复用必须先实现并验证真正的
`reset_run` 生命周期。

此外，独立新 profile 是本 oracle 语义的一部分：文档和 sample 选择都依赖 fresh shipped profile
会强制 Act 1 的非默认 variant，而 probe 专门测量这个边界
（`parity_run_acceptance.py:40-49,175-213,525-565`）。任何进程复用都必须保证 profile discovery、
run 单例、RNG、bridge 静态状态和 save 被还原；否则省掉启动会同时污染 oracle。

## 哪些开销是必要隔离，哪些是可优化实现

### 源码事实

- 不同 Ancient choice 代表不同分支。同一个已开始的 run 不能先走 choice 0，再回退去测 choice 1；
  full-app bridge 没有 snapshot/restore RPC。14 个 sample 中虽只有 10 个 distinct run，当前仍需要 14 个
  独立 run execution（`parity_run_acceptance.py:181-202,283-298`）。
- sample 和 probe 使用不同 sandbox、动态端口，互相没有共享写目录；这是可以安全隔离并发的基础
  （`full_app_client.py:97-108,190-201`）。
- 当前执行完全串行（`parity_run_acceptance.py:658-671`）。
- parity 报告不记录总耗时、启动耗时、drive 耗时、PID 或进程数；现有离线测试只检查报告契约，
  不会发现 cold-start 次数或 wall time 回归
  （`parity_run_acceptance.py:571-623`；`tests/test_parity_projection.py:21` 及其 `report()` 测试）。

### 基于上述事实的判断

1. **先消除跨进程重复 PCK hash，潜在收益最明确。** parity 已从第一个 native worker取得完整
   `game_build`（`parity_run_acceptance.py:655-656`），所有 full-app sandbox 又通过 hard link/junction
   指向同一安装。可以设计一次可信 fingerprint、其余进程复用的协议，例如由 coordinator 传入期望
   fingerprint，并以 Windows file identity/大小/mtime 和 sandbox share 关系验证它确实对应当前文件；
   或建立带严格失效键的共享 fingerprint cache。具体信任模型需要设计，不能直接无条件信任环境变量，
   但当前“每个 one-shot 进程重新哈希 1.77 GiB”没有增加独立性：这些进程读的是同一个硬链接文件。
2. **随后增加有界的 full-app 并发。** 给 parity 入口增加独立的 `--game-workers`，用有界 executor
   并行 `_sample_result()`/probe，可以保留“一 sample 一新进程”的隔离语义，同时把 cold start 和
   drive 重叠起来。它不会减少总 CPU/内存/启动次数；尤其多个 SHA-256 同时跑会争抢内存带宽，未先
   去重 fingerprint 时加并发未必线性提速。因此并发上限必须保守并实测峰值资源。从当前 unique
   sandbox + dynamic port 设计看，没有明显的共享目录阻碍。
3. **真正减少启动次数需要把已有的 bridge lifecycle 机制适配回当前结构。** 一个可复用 worker至少需要：显式结束当前 run、
   回到可启动状态、清空 bridge history/TCS/pending action/boundary 状态、重建或重启 `AutoSlayer`、重置
   profile/save，并用“同 sample 新进程 vs 复用进程”字段级一致测试证明无泄漏。完成前不应把 client
   简单提到循环外。相关 sibling 仓库已经实现并局部测量过这套生命周期，见下一节；当前工作不是从零
   发明 reset，而是把它适配到重构后的协议和 observation 模块，并补完等价性 gate。
4. **probe 可在日常局部迭代中跳过，但完整认证不应静默删除。** 现成 `--only`、`--limit`、
   `--no-probes` 已能把开发时启动数降到 1 或 N；最终 gate 仍应跑完整 14+2，因为两个 probe 测的是
   oracle 可达范围，而不是冗余样本。
5. **关闭协议有一个小的重复动作。** server 已承诺 50 ms 后退出，client 却马上 `terminate()`；可以改成
   先短暂等待正常退出、超时再 terminate/kill，并记录实际退出方式。它能让生命周期更干净，也方便
   区分正常退出和故障，但相对于约 5 秒启动和十几秒 sample 周期，预计不是主要 wall-time 收益。
6. **应先补测量再优化。** 报告至少应加入 `full_app_processes_started`、每个 sample 的
   `sandbox_seconds/startup_seconds/fingerprint_seconds/drive_seconds/close_seconds`、总 wall time、PCK
   bytes hashed 和最大并发。否则优化前后只能靠控制台观感或文件 mtime 判断。

## Sibling 仓库已有的复用证据

按根目录 `AGENTS.md` 的 related-repository 约定继续检查 `../_deprecated_divine-sts2` 后，可以确认“一个
shipped-game 进程只能服务一局”从来不是游戏本身的约束；该 sibling 已实现过可选的 reuse lifecycle：

- `ReuseSession` 抑制 shipped `AutoSlayer.RunAsync` 最终调用的 `QuitGame`，跟踪并等待旧 driver task，
  用 run generation 拒绝上一局恢复的 coordinator continuation，并以 `RunManager.CleanUp()` 清掉当前 run；
- `end_run` 之后清空 bridge 的 per-entry 状态，下一次 `start_run` 通过 direct-start seam 再调用 shipped
  `NGame.StartNewSingleplayerRun`；reuse run 使用 `shouldSave: false`，并在 teardown 前后记录 profile
  fingerprint；
- WP2a 的受控 probe 中，15 个样本在 `RunManager.CleanUp()` 和 `NGame.ReturnToMainMenu()` 两种 teardown 下
  都成功开始第二局；相同 seed 的第二局 combat-initial hash 与第一局及 fresh process 相同。最小 teardown
  的第二个 root entry 为约 3.7–3.9 秒，对照 fresh entry 约 15.2 秒；
- 后续 runner-level reuse 用 2 个进程处理 38 个 entries（每个进程 19 个），结果 38/38 match，且每个 warm
  entry 的 history 从 0 actions / 1 initial hash 开始。不过完整 manifest 的 fresh-vs-reused 同 entry-set
  等价性运行当时未完成，所以这仍是强可行性证据，不是完整认证。

一手来源是 sibling 的
`src/Sts2.NativeSim.FullAppBridge/ReuseSession.cs:24-53,101-167,265-299,318-435`、
`src/Sts2.NativeSim.FullAppBridge/FullAppBridgeServer.cs:265-340` 和
`docs/e5-differential-run-cost-and-process-reuse-report.md:274-555`。当前仓库已经拆分 shared RPC wire adapter、
typed canonical observation encoder、card identity 和 card-select prompt；旧 `ReuseSession.cs` 依赖的
`DirectRunStart`、`ReleaseParkedCoordinatorWait`、`ResetForReusedRun` 与 `RunStartPhaseLog` 在当前树中均不存在。
因此旧文件不能直接复制或覆盖当前 `FullAppBridgeServer`/`FullAppBridgeMod`，但其 teardown、generation、
driver-task 和 profile-isolation 机制可以作为适配依据。

## 与其它实机 acceptance 的区别

- `bridge_card_select_acceptance.py` 也采用每个样本一进程：3 个 prompt sample 加 1 个 bundle sample，
  共 4 次串行 launch/close（`tests/acceptance/bridge_card_select_acceptance.py:450-473`）。因此这个模式
  不只存在于 parity 入口。
- `full_app_bridge_acceptance.py` 启动 4 个主 worker 并保持它们贯穿多个 step，另起 2 个 replay worker；
  它证明 full-app client 可以作为**单 run 内的持久进程**使用，但没有证明跨 run reset 可用
  （`tests/acceptance/full_app_bridge_acceptance.py:67-85,95-173,175-228,271-274`）。
- native worker 已经是固定持久池并带 crash replacement
  （`python/sts2_native_sim/client.py:361-407`）；这个复用机制不适用于 full-app client，两个 client 类型
  没有共享 lifecycle 协议。

## 最终判断

用户观察到的“不断启动、终止游戏进程”是准确的，并且可以从源码精确解释为默认 16 次串行、每个样本
一次的 one-shot 设计。它不是异常重试，也不是当前 sandbox 在复制整份游戏。更具体的浪费是相同 PCK
在默认 16 个真机进程和 3 个 native 进程里共被哈希 19 次；其中真机侧约 28.33 GiB 重复 fingerprint，
本机单次测量外推已是约 65.9 秒的量级。独立 run/profile 有验证价值，但重复 fingerprint 和“全部串行
冷启动”都不是 oracle 必需条件。优先做可信的 build-fingerprint 复用、补计时指标，再做有界真机并发，
可以在不改变隔离语义的情况下降低 wall time。跨样本复用进程已有 sibling 实现和 38-entry 运行证据，
潜在收益更大；当前仓库需要把该生命周期适配到重构后的模块，并完成 fresh-vs-reused 全量等价性 gate，
而不能直接复用现有 `start_run()` 或原样复制旧 bridge 文件。
