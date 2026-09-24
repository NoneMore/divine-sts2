# Fast First-Combat Compiler 可行性探测

**日期：**2026-09-24。范围固定为完全解锁的单人 `IRONCLAD`、Ascension 0、四个种子 `A1B2C3D4E5 / 1 / 2 / 3`。本报告把已完成的独立计算与尚需复刻的规则分开；原型不构成完整首战编译器。

## 实测结论

研究原型 [`fast_first_combat_probe.py`](../../python/experiments/fast_first_combat_probe.py) 仅移植种子哈希、`xoshiro256**`/`SplitMix64`、`Rng.NextInt` 和 Act 1 选择，不调用 shipped-game run 来产生预测。它随后用现有 [`generate_rows`](../../python/sts2_native_sim/_scenario_generation.py) 取原生结果，将 **每个 observation 叶字段**标为 `match`、`mismatch` 或 `unimplemented`。分类明细在 gitignored 的 `artifacts/scenario-performance/fast-first-combat-field-diff.json`，可重跑原型生成。计数包括数组元素和 `null` 叶值。[哈希实现](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Helpers/StringHelper.cs#L136-L151)、[RNG 实现](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Random/MegaRandom.cs)、[选择路径](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L2260-L2284)、[字段投影](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1230-L1291)。

| 四种子、12 个 Ancient choice | 结果 |
| --- | ---: |
| 原生成功场景 | 12 / 12 |
| observation 叶字段数 | 2,288，单行 164–220 |
| 已计算并匹配 | 72 / 72，单行 6 个 |
| 已计算但不匹配 | 0 |
| 尚未计算 | 2,216 |
| 四个种子的部分编译耗时 | 0.000063 秒（单次 `perf_counter` 测量） |

六个已匹配字段是 `run.seed`、`run.ascension`、`run.act_variant`、`decision.kind`、`terminal`、`victory`。有随机性且真正提供独立 RNG 证据的只有 `run.act_variant`：预测为 `OVERGROWTH / UNDERDOCKS / UNDERDOCKS / OVERGROWTH`，四种子全部符合。`decision.kind` 和终局标志仅是已知目标“活着的首战”所带的常量。**没有完整 observation 相等、state hash 相等或后续 combat parity 的证据；0.000063 秒绝不能外推为完整编译器吞吐量。**字段计数与时间由上述原型同机实测得出。[部分编译代码](../../python/experiments/fast_first_combat_probe.py)、[原生观察结构](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1230-L1291)。

复现命令（本机 `.env` 需设置游戏路径和 Godot，worker 需在文件沙箱外运行）：

```powershell
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/experiments/fast_first_combat_probe.py'
```

## 要复刻的最小规则链

1. **起始配置、种子和 Act。** `Ironclad` 定义 80 HP、99 金、10 张牌和 `BurningBlood`；`Player.CreateForNewRun` 装载起始牌组及 relic。Run RNG 先对字符串做确定性 32 位哈希，再为每个命名 stream 创建独立 `Rng`。Act 选择另用 `act_selection` RNG；完整解锁后，Act 1 候选按 `ModelDb` 顺序为 `Overgrowth`、`Underdocks`。这是原型已经独立复刻的一段。[Ironclad](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Characters/Ironclad.cs#L25-L61)、[Player](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Entities/Players/Player.cs#L298-L343)、[RunRngSet](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Runs/RunRngSet.cs#L103-L129)、[Act pool](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/ModelDb.cs#L270-L309)、[Act roll](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/ActModel.cs#L538-L569)。
2. **起始生成和 Ancient 选项。** `RunManager.GenerateRooms` 对共享 Ancient、每个 Act 的事件/弱遭遇/普通遭遇/精英/首领/Ancient 作 `UpFront` 消耗；`ActModel.GenerateRooms` 对遭遇使用有标签约束的 grab bag。因此首个弱遭遇不只是“seed 对弱遭遇数取模”。Neow 的三选项又用其独立 event RNG：诅咒池过滤、相斥的正面选项过滤、最多三次布尔抽签、洗牌后取两个正面选项，再附一个诅咒选项。每件 relic 的拾取效果可进一步产生牌、奖励或嵌套决策；现有驱动记录并按固定规则选择这些决策。[房间生成](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Runs/RunManager.cs#L666-L695)、[遭遇池](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/ActModel.cs#L331-L421)、[event RNG](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/EventModel.cs#L230-L241)、[Neow offer](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Events/Neow.cs#L215-L282)、[现有决策驱动](../../python/sts2_native_sim/ancient.py#L110-L143)。
3. **地图与 row 1。** `StandardActMap` 使用独立的 `act_1_map` RNG，构建路线、分配节点、剪枝和调整位置。场景生成器走离开 Ancient 后报告的第一个可选 map action；不能把“row 1 是 Monster”当成足以确定节点坐标、map 投影或 RNG 计数。遭遇序列来自上一步的 Act 房间池，走入节点时由 `RunManager` 抽取。[地图构造](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Map/StandardActMap.cs#L84-L121)、[原生 map 驱动](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1368-L1420)、[Python 节点选择](../../python/sts2_native_sim/_scenario_driver.py#L455-L475)、[抽取遭遇](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/ActModel.cs#L445-L455)。
4. **首战内部。** `CombatRoom.StartCombat` 生成敌人并建立 combat；遭遇的独立 RNG 由 run seed、总楼层和 encounter ID hash 组成。怪物 HP、招式和意图依赖各自模型及 RNG，Ascension 的修正也要进入这条路径。`CombatManager` 调用玩家 `PopulateCombatState` 洗牌，然后执行战斗进入和开局抽牌；这些 hook 受 Ancient relic 和牌效果影响。完整 canonical observation 包括 run counters、楼层、gold，敌人的 HP/intent/powers，五个牌堆中每张牌的实例 ID、费用、升级与 native state，以及 relic/potion state 和 legal actions。[CombatRoom](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Rooms/CombatRoom.cs#L197-L227)、[encounter RNG](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/EncounterModel.cs#L250-L276)、[shuffle 与开局](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Combat/CombatManager.cs#L360-L421)、[抽牌](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Combat/CombatManager.cs#L645-L675)、[canonical 投影](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1238-L1291)、[牌与怪物字段](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L2605-L2630)。

## RNG parity 与 silent divergence

**RNG 算法本身可独立实现。** 本次移植的哈希、`SplitMix64`、`xoshiro256**` 与 `NextInt` 在 Act 选择这条 stream 上得到四个种子的正确结果。但完整 parity 还要求保持**每个 stream 的所有抽取次数、抽取顺序与候选列表顺序**。`UpFront` 跨三 Act 的房间/遭遇生成而消耗，Neow 使用 event 自身 RNG，map 与 encounter 又是另行派生的 RNG；`Rng` 对 `NextBool`、`NextInt`、`NextDouble` 和 Fisher–Yates 的计数方式必须逐一照搬。[Rng 接口](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Random/Rng.cs#L33-L106)、[命名 streams](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Runs/RunRngSet.cs#L17-L100)、[列表洗牌](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Extensions/ListExtensions.cs#L45-L62)、[房间序列](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Runs/RunManager.cs#L666-L695)。

最易静默偏离的字段是 `run.rng_counters`、地图坐标/楼层、Ancient effect 后的 inventory、牌实例 ID/顺序、怪物 HP 与首回合 intent。它们可在 encounter 名称与起手牌表面上相同的情况下不同。尤其 `state_hash` 的输入除 observation 外还有 `TransitionKernelProjection()`，所以只比 JSON observation 仍不足以证明 simulator continuation parity。[投影及哈希](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1213-L1228)、[hidden kernel 与 branch](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L3230-L3305)、[牌投影](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L2618-L2630)。

现有 `reset_mode=combat` 也不能直接被当成编译器的注入端：它重新生成 encounter 怪物、重新洗牌，并手动构造 `CombatRoom`；`reset_mode=run` 则只建地图、不建战斗。更直接的障碍是 kernel 明确记录 `run_mode` 和 `run_stage`，所以即使 combat reset 能产生相同 observation，它的 state hash 也会与 run-derived 首战不同。要让编译产物继续交给现有 native combat simulator，必须验证一个可还原完整内核状态的入口，或扩展重置路径使其在 observation、hash 和后续动作上严格相等。[两种 reset 路径](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L940-L1019)、[kernel 与 hash](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1169-L1228)。

## 性能与建议

当前热 worker 基线约 4.049 秒 / 12 行，即 2.96 行/秒；达到 100 行/秒需约 **34 倍**，达到 300 行/秒需约 **101 倍**。完全跳过 shipped run 的方案在计算量上有机会跨过这道门槛，但当前原型只算一个 Act roll，没有任何完整行/秒测量，故“至少数百行/秒”仍是**待验证假设**。工程复杂度为高：至少涉及角色初始配置、Act/遭遇池、Neow/relic 效果、地图、怪物及战斗进入规则，外加一个可靠的 native state 导入接口。[热 worker 基线](act1-first-combat-scenario-handle-reuse.md#three-round-same-host-benchmark)、[需要的原生阶段](../../python/sts2_native_sim/_scenario_driver.py#L393-L475)。

可把现有 Native generator 留作**随机抽样 oracle**：按 seed、角色、进阶、Ancient choice 采样，比较 recipe、全 observation、state hash，再对若干 legal actions 比较 continuation；每次游戏 build 更新都重新认证。现有场景 materialization 已在重新驱动 run 后比较完整 observation 和 hash，可复用其字段比较思路。只有编译器能从纯输入直接构造同一状态，且上述差分连续通过，才有依据让 shipped-game run 退出 bulk generation。下一步优先验证一个 **最窄的状态导入闭环**：先限定固定 `IRONCLAD/A0`、一个无嵌套的 Neow choice、一个 seed，目标是首战全字段、hash 与一回合动作完全相等；在此之前扩大 seed 数或做吞吐量宣传意义不大。[materialization 全状态比较](../../python/sts2_native_sim/_scenario_driver.py#L260-L355)、[现有 native oracle](../../python/sts2_native_sim/_scenario_generation.py#L16-L29)。
