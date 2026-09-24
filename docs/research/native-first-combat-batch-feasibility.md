# Native-side batch generation 可行性探测

**日期：**2026-09-24。研究范围为 `IRONCLAD`、Ascension 0、种子 `A1B2C3D4E5 / 1 / 2 / 3`，共 12 个 Ancient choice。对应的另一条路线见 [Fast First-Combat Compiler 探测](fast-first-combat-compiler-feasibility.md)。

## 原型与实测

仅在 `DEBUG` 构建可用的研究用 [`generate_first_combat_scenarios_probe` RPC](../../src/Sts2.NativeSim.GodotHost/Main.cs) 在 C# worker 内对一个 seed 执行 reset、进入 Ancient、三个 choice、嵌套选择、离开 Ancient、进入首战。它复用 Python 驱动相同的 native run/session 操作，后两个 choice 使用 Ancient offer 的 checkpoint 恢复。RPC 返回最终 observation/hash、choice 和首个 row-1 node；尚未实现正式 corpus row 的全部 envelope、失败行和编码。[原生原型](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs)、[现有 Python 驱动](../../python/sts2_native_sim/_scenario_driver.py#L357-L489)。

原型有两种路径：`native_full` 对每步调用已有 `StepAsync`；`native_light` 只在中间步调用 `Session.ApplyAsync` 并读取 `DecisionFrame`，略过 coordinator 的每步 `Project`、hash 和 branch handle。两者仍通过 `NativeRunAdapter.Capture` 进入 legacy environment；那里继续生成**完整** observation、hash、branch handle，且 adapter 再算一次 hash 做一致性检查。因此 `native_light` 是“省去一层中间投影”的实测，**不是**“所有中间投影已省去”的实测。[原型方法](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs)、[adapter capture](../../src/Sts2.NativeSim.Core/RunSession/NativeRunAdapter.cs#L70-L94)、[legacy map/event capture](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1503-L1530)。

[`probe_native_scenario_batch.py`](../../python/tools/probe_native_scenario_batch.py) 用现有 `generate_rows` 作 oracle。两个独立的 fresh-worker 对照中，native 两模式各自的 **12/12 最终 combat observation 逐字段相等、state hash 相等、Ancient choice identity 和 row-1 node 相等**；Python 基线也各为 12 个成功行。每次各模式分别新启 worker，表中生成时间不含 startup、关闭、gzip 写入。原始首轮数据在本机 gitignored 的 `artifacts/scenario-performance/native-batch-probe-fresh-20260924.txt`；第二轮由同一脚本复跑，关键数据列在表中。[差分逻辑](../../python/tools/probe_native_scenario_batch.py)、[场景记录格式](../../python/sts2_native_sim/_scenario_driver.py#L580-L615)。

| 4 seeds / 12 rows | fresh 对照 1 | fresh 对照 2 | 两次均值 |
| --- | ---: | ---: | ---: |
| Python 当前驱动 | 3.770 s | 4.066 s | 3.918 s |
| native_full | 3.716 s | 3.762 s | 3.739 s |
| native_light | 3.833 s | 3.755 s | 3.794 s |
| worker startup，三模式各自 | 2.46–2.51 s | 2.49–2.56 s | — |

这与此前独立测得的约 **4.049 s / 12 rows** 热路径中位数同一数量级。两次 fresh 对照中的 native batch 相比当前 Python 只有约 **1.03–1.05 倍**表面收益；样本太少、模式固定顺序，不能把这个小差距认定为稳定加速。单 worker 连续跑三轮时，第一次 Python 批次约 4.04 s，后续 Python 与 native 批次均落在约 1.6–1.9 s，显示 JIT/游戏模型/缓存预热显著影响本小批量；不能用第一轮 Python 对后续 native 比较来声称 2 倍收益。[先前热路径基线](act1-first-combat-scenario-handle-reuse.md#three-round-same-host-benchmark)、[测量脚本](../../python/tools/probe_native_scenario_batch.py)。

## 为什么收益有限

第二次 fresh 对照的 C# 阶段计时（`native_light`）为：4 次 reset **1.017 s**、8 次 restore **1.484 s**、12 次进入 combat **0.901 s**，三项合计 **3.402 s**，占 3.755 s wall time 的约 **91%**。进入 Ancient、选择 Ancient、嵌套选择、离开 Ancient 合计约 **0.293 s**。两个 fresh 对照的阶段分布接近；这些是包裹方法调用的 wall time，包含其内部状态投影，不能细分成 shipped-game mechanics 与投影成本。[原型阶段计时](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs)、[reset 强制 GC 与构建](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L212-L244)、[恢复实现](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L633-L794)。

现有 restore 对 run-mode checkpoint 没有 combat snapshot，落入 `ReconstructAsync` 后重放 Ancient 入口动作；后两个 choice 因此仍各需一次 reconstruct。C# 内循环只减少跨进程 JSON/RPC；它不能把同一个可变 shipped run 倒回 Ancient 前的对象图。若未来实现经验证的原生快照/克隆，才可能真正移除这两次 reconstruct，那已经超出本方向的“小改动”。[run-mode snapshot 条件](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L3321-L3325)、[reconstruct/replay](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L674-L794)。

**中间 observation/hash/handle 可否跳过？** 从调用语义看可以建专用内部 fast path：中间步骤只需下一步合法动作、决策类型和 prompt continuation；Ancient offer 仍需一次 checkpoint，最终首战仍需完整 canonical observation/hash。现有 `ActiveRunSession` 与 `NativeRunAdapter` 却以完整 `DecisionFrame`、legacy `Capture` 和 hash 一致性检查为边界；restore 的 replay 也会走投影。因此要真正跳过它们，需要同时改环境捕获、adapter/session 和 replay 内部路径，并证明嵌套 prompt、失败恢复和分支不会改变。原型仅证明跳过 coordinator 那一层后没有显著收益。[session 决策模型](../../src/Sts2.NativeSim.Core/RunSession/ActiveRunSession.cs)、[adapter 检查](../../src/Sts2.NativeSim.Core/RunSession/NativeRunAdapter.cs#L70-L94)、[event capture](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1836-L1868)。

**保守上限。** 若只删除四类 Ancient 中间阶段的全部耗时，第二次测量可从 3.755 s 降到约 3.46 s，理论上最多约 **1.09 倍**；这是刻意宽松的上界，因为其中包含必要的 shipped-game effect。把 reset/restore/combat 内部的无用投影也去掉可能进一步受益，但当前没有把这三项拆分的 profile，不能给可靠数值上界。仅凭“一个 seed 一个 RPC”没有证据能从约 3 rows/s 提升一个数量级。[原型阶段计时](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs)、[旧热路径分解](act1-first-combat-scenario-handle-reuse.md#three-round-same-host-benchmark)。

## 工程量和主要风险

只做批量 RPC：**中等工程量、低至中等 parity 风险**，但预期收益很小。完整去掉中间状态捕获：**中高工程量、中等 parity 风险**，因为 run/session 现在靠 action table、hash 与 checkpoint 保持状态一致，专用 fast path 必须在 nested card/reward/option prompt、失败行及 restore 重放中保持等价。原型仅覆盖固定角色/A0 的 12 个成功行，尚未测其他角色、Ascension、异常路径、完整 JSONL byte parity，也未测大规模 corpus 或多 worker。正式实现前应先 profile `ResetState`、`ReconstructAsync`、`CaptureMap/Event`、`EnterCombat` 的独立耗时，再决定是否值得改捕获层。[失败行契约](../../python/sts2_native_sim/_scenario_driver.py#L418-L448)、[nested drive](../../python/sts2_native_sim/ancient.py#L110-L143)。

## 两方向对比与下一步

| 路线 | 已证实或可合理预期的收益 | 工程复杂度 | parity 风险 |
| --- | --- | --- | --- |
| Native batch | 已测约 1.03–1.05 倍，未确立稳定加速；只省中间 Ancient 阶段的乐观上限约 1.09 倍 | 批量 RPC 中等；完整跳过投影中高 | 批量路径低至中；跳过校验后中 |
| Fast Compiler | 完整绕开 shipped run 才可能跨越约 3 rows/s 的瓶颈；百行/秒尚无实测 | 高，需复刻生成链并增加可验证的 native 状态导入 | 高，RNG 顺序、隐藏 kernel 与后续战斗都可能偏离 |

优先验证 Fast Compiler 的**一个 seed、一个无嵌套 Ancient choice 的状态导入闭环**：完整 observation、state hash 和一回合动作都与 Native oracle 相等。若这个闭环不成立，再评估是否值得对 native `ReconstructAsync` 和内部 capture 做专项 profile；目前证据不支持先产品化 batch RPC。方向二的规则清单、部分 RNG 原型和差分覆盖率见[独立研究报告](fast-first-combat-compiler-feasibility.md)。
