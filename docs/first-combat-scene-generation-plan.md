# 第一战战斗场景生成模块执行计划

状态：**E0 已关闭；E1、E2、E3、E4 与 E5 的实施均已完成，待项目维护者复核合并；E5 比较器的根比较缺陷已发现并修复（离线测试通过），但两份 manifest 尚未在修复后的实现上重跑：磁盘上 targeted 的 39/39 记录由修复前的实现产出、breadth 报告仍缺失，因此游戏侧 authority gate 未关闭**  
规划日期：**2026-09-13**  
治理调查：[first-combat-neow-investigation-report.md](first-combat-neow-investigation-report.md)  
证据归属：E1–E5 的持久证据同时记录在 [persistent-environment-evidence.md](persistent-environment-evidence.md)；本计划内的逐单元证据用于维护者复核，计划退役后以证据文档为准。

## 1. 目标与完成定义

实现一个 build-pinned、deterministic、fail-loud 的第一战根状态生成模块。对每个输入 `seed + character + ascension`，模块必须在同一组原生 `RunState` / `Player` 对象上完成：

```text
构造原生 run
→ 生成 Act 1 rooms/map
→ 启动并原生结算 Neow（含嵌套选择）
→ 返回地图
→ 进入合法的第一战路线
→ 到达 turn == 1 && phase == Play
→ 导出可重放的 portable root
```

首版完成必须同时满足：

1. 现有 direct-combat、map、reward、rest、event、composed-run 行为无回归；
2. `run_reset` 不再创建、洗牌或初始化一个随后被丢弃的合成战斗；
3. `neow_run_reset` 从原生 Neow 决策态开始，Neow 到第一战之间不重建玩家；
4. 第一战根在本 worker restore 和跨 worker portable replay 后 hash、观测、合法动作完全相同；
5. 在冻结的 FullApp manifest 上，所有可比字段和代表性完整战斗轨迹与 `full_application_native` 一致；
6. 语料记录包含 build、schema、seed、Neow 路径、路线、根状态和失败原因；同一 seed 的所有分支固定进入同一数据 split；
7. 不提交生成语料、游戏资源、存档或其他受限工件；
8. 维护文档只在相应证据门通过后更新，不提前提升机械忠实度或执行广度声明。

本计划不包含战斗策略训练、Neow 策略学习、模型 promotion、完整 run 序列化或可见桌面自动化。

## 2. 固定架构决定

- 原生执行 Neow、遗物获取、卡牌/遗物/奖励嵌套选择和房间进入 hooks；不得在 Python 或 NativeSim 中逐项重实现 Neow 效果。
- 先生成 Act 1 世界，再结算 Neow。
- Neow 到第一战必须保留同一 `RunState` 和 `Player`；合成 post-Neow `ResetRequest` 仅保留为隔离测试工具，不是语料权威路径。
- 第一战根边界固定为 `combat.turn == 1` 且 `combat.phase == Play`。到达该边界前不得导出训练根。
- 第一战由原生地图进入决定；direct reset 的 `encounter = "first"` 不代表 seed 对应的自然第一战。
- portable root 的首版语义是“build-pinned reset provenance + 原生 action history + expected hash”的可重放配方。当前实现不是跨 worker 原生内存快照，不能声称低成本 keyframe restore。
- `full_application_native` 是差分权威；反编译源码只用于定位行为，不覆盖 shipped assembly 证据。
- 数据划分单位固定为 seed，而不是 branch/root。

## 3. 已确认的实现缺口

本节保留 E0 规划时的现场诊断。缺口 1–4（`Construct()` 既造 run 又造 combat、resident/portable restore 走合成战斗路径、`Branch` 缺少一等 provenance、`export_branch()` 只导出 reset/history/hash）已分别由 E1 与 E2 关闭，证据见第 5 节；缺口 5–8 仍归 E3/E5。

1. `PersistentNativeCombatEnvironment.Construct()` 同时构造 run 与 combat；`RunReset()` 先调用它，再生成地图。
2. Core resident restore 仍通过 `Construct(reset) → InitializeRunMap() → replay history` 重建 run 分支；只改 `RunReset()` 会留下同类合成战斗路径。
3. `Branch` 记录多个 mode 布尔值，但没有一等的初始化 provenance；新 `neow_run_reset` 必须能被 resident 和 portable restore 精确分派。
4. Python `export_branch()` 只导出 reset method/params、history 与 expected hash；跨 worker restore 会重放全部前缀。
5. 现有 event coordinator 可处理 `choose_event`、native choice/reward 和事件进入战斗，但 Neow 不是普通地图 `EventRoom`；完成后回到地图的状态转换需要专门接线。
6. FullApp 当前投影不足以直接比较调查报告要求的全部根字段；至少缺少完整牌堆顺序、遗物 native state、药水容量和完整 Run RNG counters。先补只读权威投影，才能把这些字段列入差分门。
7. FullApp 当前接收并回显 requested ascension，但仓库代码没有把它应用到原生 run 的证据；A>0 golden matrix 在该 seam 被 build-pinned 探针确认并接线前不可用。
8. FullApp 与 fast path 的 event、nested choice、card instance/hand index 和 target action identity 不同，不能直接复用同一个 action ID 做逐步 differential。

## 4. 执行依赖图

```text
E0 build-pinned Neow/FullApp 启动契约探针
 └──────────────────────────────┐
E1 行为保持的 ConstructRun / ConstructCombat 拆分
 └─ E2 清理 run_reset、统一 reset provenance 与 restore
     └─ E3 neow_run_reset 原生垂直切片（同时依赖 E0）
         ├─ E4 第一战根枚举库与 portable replay 验收
         │   └─ E6 队列式语料 farm、schema 与 seed split
         └─ E5 FullApp 投影补齐与 golden differential（投影工作可在 E1/E2 时并行）
             └─ E6 发布门

E7 真正跨 worker combat keyframe 调查
  仅在 E4/E6 基准证明前缀重放是实际瓶颈后启动；不阻塞首版正确性。
```

## 5. 执行单元

### E0 — build-pinned Neow 与 FullApp 启动契约探针

**状态：探针证据已完成（2026-09-13）；E3 入口契约已由项目维护者确认，E0 关闭。**
结果见 [first-combat-e0-launch-contract-report.md](first-combat-e0-launch-contract-report.md)。摘要：

1. 忠实启动 Neow 的前置条件是 **unlock profile 已 reveal `NEOW_EPOCH`**（`StartedWithNeow = UnlockState.IsEpochRevealed<NeowEpoch>()`）；起始点就是真实 Ancient map point / `EventRoom(Neow)`，不存在另一条 run-start seam，也不需要 standalone `event_reset`。
2. Neow 完成后回地图是纯 presentation（`NEventRoom.Proceed` → `NMapScreen`）；headless 等价物是按模型层 `MapTravel.GetTravelablePointsFrom` 暴露 `map_choice`。Player/RunState 引用不变（5/5 slice 实测）。
3. 第一层合法节点**恒为 combat**：3 profile × 5 角色 × A0/A10 × 12 seeds = 360 样本、0 violations；E4 无需为非战斗首层房间设计分支预算。
4. FullApp 的 requested ascension **未**写入原生 run（实测 echo=5 / native=10、A10 `ASCENDERS_BANE`×1）；正确 seam 为 `StartRunLobby.SyncAscensionChange` 或 `NGame.StartNewSingleplayerRun(..., ascensionLevel, ...)`，且需满足 profile 的 `MaxAscension` / ascension epoch 前置条件。该项归 E5。
5. 普通 console 进程无法执行 shipped run 生命周期（`Logger`/`LocManager` → Godot native）；E3 必须在 headless Godot 引擎上下文中执行。

**性质**

这是阻塞 E3 和 A>0 golden matrix 的有界调查，不授权选择或实现替代游戏机制。

**需要回答的问题**

1. 当前 pinned shipped assembly 中，忠实启动 Neow 需要哪些 `UnlockState`/run flags，应该进入 starting Ancient map point/真实 event room，还是调用另一条原生 run-start seam？
2. Neow 完成后，原生生命周期如何回到刚生成地图的可选节点，且保持同一 `RunState`/`Player`？
3. 第一层合法 map point 是否在支持的 build/角色上恒为 combat；若不是，“第一战路线”需要穿越哪些非战斗 decision，分支预算由谁决定？
4. FullApp 的 requested ascension 是否实际写入原生 run；若没有，正确的 native start seam 是什么？

**允许探针与证据**

- 对 pinned assembly 做只读 reflection/API probe；
- 使用 headless FullApp 产生最小 start→Neow→map trace；
- 记录 exact build version、assembly/PCK hash、调用签名、run flags、room/map 转换和对象 identity；
- 不提交游戏资源、生成 trace 或 disposable probe 输出。

**停止条件与决策所有者**

- 若证据确定唯一原生 lifecycle，把它写成 E3 的固定入口契约，由项目维护者确认后执行；
- 若只能依赖 UI presentation、合成 Neow 或逐效果模拟，则 E3 阻塞，项目维护者/用户决定缩小范围或另做规格设计；
- 若第一层可能不是 combat，提交可复现 seed 与有限状态图，由项目维护者决定“只支持直接第一战节点”还是“遍历到首战”；执行者不得静默扩域。

**E0 已落定的决策点**

- 唯一原生 lifecycle 已确定（见本报告 §7 契约），并已由项目维护者确认，可进入 E3；E0 未发现需要依赖 UI presentation 才能启动 Neow 的情形。
- 第一层已证实恒为 combat，因此第三个停止条件不触发，E4 首版范围可限定为“直接第一战节点”。
- 展示抑制方式已确认：沿用仓库现有 scoped Harmony presentation seam，全局 `TestMode.IsOn` 保持 off。

### E1 — 拆分 run 构造与 combat 构造

**状态：实施完成（2026-09-13），Refactor gate 证据见本节；合并决定由项目维护者复核。**

结果与证据摘要：

1. `Construct()` 现在只负责按顺序调用两个阶段并记录构造边界审计；`ConstructRun` 返回 `RunConstruction`（deck、稳定 card instance 映射、modifiers），`ConstructCombat` 只消费该结果与 `_run`/`_player`。
2. 新增只读审计 `diagnostics.last_construction`，在真实阶段边界读取 shipped 原生状态（`CombatManager._state` 引用、新玩家是否已有 `PlayerCombatState`、原生 run RNG counter map）。由于 shipped `Reset(graceful: false)` 会保留旧 `CombatState` 引用，审计按对象 identity 比较而非判空。
3. 负向证据（pinned build）：run-only 阶段 `run_phase_created_combat_state=false`、`run_phase_player_has_combat_state=false`，八个 combat RNG 流（`Shuffle`、`MonsterAi`、`CombatCardGeneration`、`CombatPotionGeneration`、`CombatCardSelection`、`CombatEnergyCosts`、`CombatTargets`、`CombatOrbs`）计数全为 0；combat 阶段则安装 `CombatState`、生成 `PlayerCombatState` 并消耗 `Shuffle`（10 张牌=9；A10 起始负载=10，同时native 起始牌组含恰好一张 `ASCENDERS_BANE`）。四 worker、同 worker 重复构造、八种 reset mode 的审计完全一致。
4. 两次临时故障注入证明断言可判别而非自证：把 combat 构造移入 run-only 阶段 → 边界报告 `run_phase_created_combat_state: true`、`Shuffle: 9`；仅在 run-only 阶段抽取一次 `Shuffle` → 报告 `run-only construction consumed combat RNG: {'Shuffle': 1}`（此时两条 CombatState 断言仍通过，说明 RNG 断言独立生效）。注入已完全回滚。
5. 正向回归：16 个 acceptance 脚本拆分前后退出码、状态 hash 集合与（除去计时字段的）输出完全一致，唯一差异是 `acceptance.py` 新增的 `construction_boundary` 字段；direct reset hash 保持 `CEE9B22A0D5E3FC2B3A0C66E2C5E694E54540059B9C27E9EEA77F3D840DBEF7B`。
6. `run_room_entry_acceptance.py`、`run_event_combat_acceptance.py`、`run_custom_reward_acceptance.py` 在拆分**之前**即已在当前树上失败（断言与当前原生内容/句柄语义不符），本计划未修改其期望，已记录在 `docs/persistent-environment-evidence.md` 的 E1/E2 回归对比节。
7. 构建：Protocol、Core、Host、GodotHost 的 Release 构建均 0 警告 0 错误；GodotHost Debug（Godot 默认加载配置）同样通过。

**结果**

把 `Construct()` 拆成明确的 run-only 与 combat-only 生命周期，同时保持 `reset` 及所有隔离 mode 的现有可观察行为。

**主要修改面**

- `src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs`
- 直接 combat、choice、reward、event、map acceptance 脚本

**Fixed**

- `ConstructRun` 创建玩家、起始牌组或自定义牌组、`RunState`、run services、ascension 效果、遗物/药水和稳定 card instance IDs；不得创建 encounter/combat、洗牌或滚怪物意图。
- `ConstructCombat` 承担 encounter、monster、`CombatState`、combat manager/player combat state、entry hooks、开局牌区/敌人覆盖和 combat RNG 初始化。
- 原有 `ResetRequest` 兼容性和 direct reset hash/合法动作不得改变。

**Local**

- 私有 helper 命名、参数对象、清理公共状态的内部组织方式。

**验证**

- 正向：原有 direct combat acceptance 与 choice/reward/event/reset 模式逐项通过，四 worker hash 一致。
- 负向：添加 instrumentation/test seam，证明 run-only 构造未创建 `CombatState`、未增加 `Shuffle`/`MonsterAi` 等 combat RNG counters。
- 构建：Protocol、Core、Host、GodotHost 受影响项目。

### E2 — 清理 `run_reset`、restore 与初始化 provenance

**状态：实施完成（2026-09-13），Run lifecycle gate 证据见本节；合并决定由项目维护者复核。**

结果与证据摘要：

1. 新增一等、可枚举的 `ResetMode`（`combat`/`run`/`map`/`card_reward`/`item_reward`/`custom_reward`/`rest`/`event`）与 wire 名映射；每个 reset RPC 只声明一个 mode，reset、resident restore、cross-worker portable restore 都由该值选择重建路径。`Branch` 用 provenance 加上该 mode 需要的参数替代原先的 mode 布尔组合；`diagnostics` 新增 `reset_mode` 与 `last_restore`。
2. `run_reset` 现在只执行 `ConstructRun → GenerateRooms → GenerateMap`：`last_construction` 报告 `combat_phase_constructed: false`、无 `CombatState` 安装、新玩家无 `PlayerCombatState`、八个 combat RNG 流计数全为 0。resident restore 对 run mode 分支同样只走 run-only 路径，不再 `Construct → InitializeRunMap`（E3 的 `neow_run_reset` 将复用同一 provenance 分派）。
3. run-only 阶段新增 run 级 deck→card instance 映射（原映射由被丢弃的合成战斗建立）。进入原生 combat 时卡片 instance ID 词表与 E2 前完全一致（实例集合相等，见 §5）。
4. 负向证据（pinned build）：把 `ResetMode.Run` 临时改成战斗构造路径后，reset 断言报 `combat_phase_constructed: true` + `Shuffle: 9`，restore 断言报 `synthetic_combat_installed: true` + `Shuffle: 9`/`Niche: 1`；健康路径为 `false`/`false`/0。注入已完全回滚。
5. 语义差分（同 seed、custom 10 张牌与 A10 原生起始负载各一）：map 观测的非 RNG 字段差异为 **0**（map 点、visited、legal actions 完全一致），差异仅在 `run.rng_counters`（`Shuffle` 9/10→0、`Niche` 1→0）以及随后第一场真实战斗的洗牌顺序与怪物 HP——即被删除的合成战斗原先消耗的两条流。map/房间生成使用 `UpFront`，因此路线与房间内容不变。
6. 正向回归：16 个 acceptance 脚本前后对比，所有不观测 composed run 的脚本（direct combat、choice、bundle、card/item reward、reward option、rest、event、map reset）退出码与 hash 集合完全相同，direct reset hash 保持 `CEE9B22A0D5E3FC2B3A0C66E2C5E694E54540059B9C27E9EEA77F3D840DBEF7B`；composed-run 脚本保留全部内容/路线/奖励/事件断言，仅 hash 变化（run 观测含 RNG counters）。`run_room_entry_acceptance.py` 原先把 seed `NATIVE-COMPOSED-ROOM-ENTRY` 的遭遇硬编码为 `NIBBIT`（shipped build 实际为 `TWIG_SLIME_S`/`LEAF_SLIME_M`/`LEAF_SLIME_S`），现改为四 worker 一致 + 真实敌人 + 牌数守恒 + instance ID 集合相等，脚本转为通过。
7. `portable_modes_acceptance.py` 覆盖 8 个 mode 的 reset→step→portable export→cross-worker restore，另覆盖 map、event 内嵌 `card_choice`、run combat 三阶段的 local restore 与 portable restore，并对 provenance / method / 未知 method / build / schema / history / expected hash 逐一篡改要求 fail closed（`reset_provenance_mismatch`、`unknown_reset_mode`、`build_mismatch`、`unsupported_portable_branch_schema`、`replay_divergence`），校验发生在任何 reset RPC 之前。无 schema 字段的 v0 记录仍经明确兼容路径精确重放（combat 与 run 各一）。
8. `run_event_combat_acceptance.py`、`run_custom_reward_acceptance.py` 在 E1 之前即已失败，E2 未改变其观测值与失败原因，仍按 `docs/persistent-environment-evidence.md` 记录保留。
9. 构建：Protocol、Core、Host、GodotHost 的 Release 与 Debug 均 0 警告 0 错误。

**迁移说明**：pre-E2 的 run-mode portable branch 在删除合成战斗后不再产生相同状态，重放会以 `replay_divergence` fail closed（不静默降级）；其余七个 mode 的旧记录（含无 schema 的 v0 记录）保持可重放。

**结果**

`run_reset` 只执行 `ConstructRun → GenerateRooms → GenerateMap`；所有 local/portable restore 都按原始 reset mode 重建，不偷偷走 direct combat 构造。

**主要修改面**

- `PersistentNativeCombatEnvironment` 的 reset 清理、`RunReset`、`RestoreAsync`、`Branch`/snapshot provenance
- `python/sts2_native_sim/client.py`
- `python/portable_modes_acceptance.py`
- `python/run_room_entry_acceptance.py` 及 composed-run acceptance

**Fixed**

- provenance 是一等、可枚举且 fail-loud 的 mode；不得通过互相冲突的布尔组合推断新入口。
- 未知 mode、build mismatch、replay hash mismatch 必须报错，不得降级为 direct reset。
- 现有 portable branch JSON 的已支持 mode 继续可重放；若 schema 增加版本字段，旧格式只能走明确兼容路径。

**Local**

- Core 使用 enum/record 还是单一 mode 字符串；Python 内部 reset bookkeeping 的机械实现。

**验证**

- 四 worker `run_reset` map hash/legal actions 一致，进入第一战后仍是 Turn 1 / Play。
- local restore 与 cross-worker portable restore 覆盖 map、event/nested choice、combat 三个阶段。
- 负向断言：restore 期间无 synthetic combat；篡改 mode/history/hash/build 均 fail closed。

### E3 — `neow_run_reset` 原生垂直切片

**状态：实施完成（2026-09-13），Neow gate 证据见本节；合并决定由项目维护者复核。**

结果与证据摘要（pinned build `A1F9E653…` / `v0.107.1`，见 `docs/persistent-environment-evidence.md`）：

1. 新增 `neow_run_reset` RPC 与独立 run-start DTO `NeowRunStartRequest`，线上只接受 `game_build`、`seed`、`character`、`ascension`；没有 deck/relic/potion/hand/enemy/RNG 字段，因此无法表达伪造的 post-Neow 状态。RPC 出现在 `hello.methods`、两个 host dispatch、`hello.run_start` 与 Python client 的 `RESET_METHOD_PROVENANCE`（`neow_run_reset → neow_run`）。
2. 固定序列按 E0 §7 执行：run-only 构造（`Player.CreateForNewRun` + `RunState.CreateForNewRun` + pinned unlock profile）→ `GenerateRooms` → `GenerateMap` → `AddVisitedMapCoord(StartingMapPoint.coord)` → `EnterMapPointInternal(1, Ancient, null, saveGame: false)` → 捕获并 await fire-and-forget `BeginEvent` → Neow 决策态。开始序列前执行与 `run_reset` 相同的 `CombatManager.Reset(graceful: true)` 清理，否则 shipped `Reset(false)` 留下的 stale `CombatState` 会让下一次 `SetUpCombat` 失败，一个 worker 只能服务一次 run start。
3. unlock profile 固定为 shipped `UnlockState.all`（`unlock_profile: "unlock_state_all"`，`docs/persistent-environment.md` 的 run-start 契约节记录选择理由），该固定选择已由项目维护者确认（2026-09-13），并发布在 `hello.run_start`、Neow 观测的 `run_start` 块与 `diagnostics.run_identity`。所有 E0 前置条件以 shipped 状态 fail-loud 断言：`StartedWithNeow`、起始点 `Ancient`、事件 id `NEOW`、选项数 > 0、`Hook.ShouldAllowAncient`、首层 travelable 节点全为 `Monster`；pinned enum 成员漂移报 `unsupported_build_contract`，profile 无法产生 Neow 报 `neow_unavailable`，都不降级为 direct reset 或合成 post-Neow 状态。
4. Neow 与全部嵌套选择都走 shipped 机制，无遗物 ID 分支：`choose_event`（身份为 shipped `text_key`）、`choose_cards`（New Leaf / Precise Scissors / Pomander / Hefty Tablet / Lead Paperweight / Massive Scroll）、`choose_option`（Scroll Boxes bundle 屏）、`choose_custom_reward`/`skip_custom_rewards`（Lost Coffer / Small Capsule / Large Capsule / Kaleidoscope / Neow's Bones）。事件 `IsFinished` 后由显式 `proceed_neow` 动作转入 map 决策，合法选项来自 `MapTravel.GetTravelablePointsFrom(run, StartingMapPoint)`；该动作不改动游戏状态，finished 的 EventRoom 留在 room stack 上，交由下一次原生 `EnterMapPointInternal` 退出，与生产路径一致。
5. 正向证据（`python/neow_run_acceptance.py`，四 worker，12 fixtures：Ironclad A0 × Large Capsule / Phial Holster / Small Capsule / New Leaf / Leafy Poultice / Precise Scissors / Scroll Boxes / Neow's Bones / Lost Coffer、Defect A0 Winged Boots、Silent A0 Lost Coffer、Ironclad A10 Scroll Boxes）：每个 fixture 的 Neow 决策在四 worker 上 hash、`choose_event` 动作、`event`/`run_start`/run inventory 完全一致；每条分支都到 `combat.turn == 1 && phase == Play`，根 hash/观测/合法动作/决策序列四 worker 一致；同一 worker 内 Neow 决策态与根的 `diagnostics.run_identity` 完全相同；A10 起始牌组 `ASCENDERS_BANE` 恰好一次、A0 为 0；决策态八个 combat RNG 流全为 0，run-start 构造审计 `combat_phase_constructed: false`。
6. fork 隔离：Neow 决策态 handle 在另一分支推进后 restore，hash/观测/合法动作逐字节复现，路径为 `replay`（非 resident-prefix），`synthetic_combat_installed: false`、`player_has_combat_state: false`、combat RNG 全 0；被污染 worker 上推进的分支与从未见过另一分支的 worker 上同一分支 hash/观测相同，决策态 RNG counters 不变。
7. 重放：把 resident 状态移离 run-start 根后 restore 该根会真正重建（`replayed_actions > 0`）；导出 branch 的 `provenance` 为 `neow_run`、reset request 恰为四个开局字段，跨 worker portable restore 复现 hash/观测/合法动作。
8. 负向证据：篡改 assembly hash / version、`ascension: 11`、空 seed 分别以 `build_mismatch`/`invalid_reset` 拒绝且不影响 resident run；未知角色在构造期以 `unknown_model` 拒绝，下一次合法 run start 即恢复；带伪造 deck/relic/potion/HP/gold/RNG/enemy 字段的记录产生与普通记录逐字节相同的决策，证明协议上无法伪造 post-Neow 状态。
9. 两次临时故障注入证明断言可判别：Neow 模式改用合成空 unlock profile → `neow_unavailable`（`StartedWithNeow` 未置位）；`MapPointType.Ancient` 改用改名成员 → `unsupported_build_contract: Pinned MapPointType has no member 'AncientRenamed'`。注入已完全回滚。
10. 一处顺带修复与两处记录在案的边界：map 进入战斗的 start 现在走可挂起的 transition coordinator —— Neow's Bones 可给出 Large Capsule，进而给出 Gambling Chip，其 `AfterPlayerTurnStart` 弃牌选择原本让 combat start 静默挂起（客户端仅超时、无协议错误），现在暴露为 `card_choice`（`phase == Start`）并在解析后到达 turn 1 / Play；另外在 pinned Act 1 样本上起始 Ancient 点连接全部 row 1 节点，`MapTravel` 与 `Children` 返回同一集合，因此该样本无法区分两者，Winged Boots 的 free travel 在起始 Ancient 点不可观测。

**结果**

新增专用 RPC，从真实起始牌组启动同 run 内的 Neow，并可用现有 action protocol 走到 map，再自然进入第一战。

**主要修改面**

- `src/Sts2.NativeSim.Protocol/Messages.cs`
- `src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs`
- `src/Sts2.NativeSim.Host/Program.cs`
- `src/Sts2.NativeSim.GodotHost/Main.cs`
- `python/sts2_native_sim/client.py`
- 新增 focused acceptance，例如 `python/neow_run_acceptance.py`

**Fixed**

- RPC 名称为 `neow_run_reset`，并出现在 `hello.methods`、两个 host dispatch 和 Python client。
- 使用独立的 run-start DTO，只接受 `game_build`、`seed`、`character`、`ascension` 等真实开局参数；不接受自定义 deck/relic/potion/hand/enemy，从协议上阻止伪造 post-Neow 状态。
- 顺序固定为 `ConstructRun → GenerateRooms → GenerateMap → Begin native NEOW`。
- “Begin native NEOW”的确切调用必须采用 E0 在当前 pinned build 上确认的原生 run-start/event lifecycle，不能仅凭逆向源码猜测或直接拼一个 standalone `event_reset`。
- 初始结果必须是 `decision.kind == "event_choice"` 且事件 ID 为 `NEOW`。
- Neow 获取与所有嵌套选择调用 shipped native machinery；不得按遗物 ID 写效果分支。
- Neow 完成后转为同一 run 的 `map_choice`；不得构造新 Player/RunState，也不得把 Neow 当独立 `event_reset` 重放后再拼接。

**Local**

- `_runStage` 的内部枚举/字符串表示；Neow finished 后是自动回 map，还是经过一个显式且确定的完成 action。
- DTO 的 C# 类型名及 observation 中非契约性诊断字段。

**验证**

- 同 seed/character/ascension 在四 worker 上 Neow options、metadata、hash 完全一致。
- 在 Neow 决策态建立临时 branch handle，分别解析不同 option/nested choice，再 restore；A 分支不改变 B 分支的 options 或 RNG counters。这里的 handle 只用于生成时的隔离/重放，不得导出为语料根或交给战斗 rollout；唯一可导出的训练 root 仍是 Turn 1 / Play。
- 通过对象 identity test seam 或只读诊断证明 Neow 前后及第一战的 Player/RunState 未替换。
- A10 起始牌组中的 `ASCENDERS_BANE` 恰好一次。
- 不支持/反射签名漂移/Neow 不允许时 fail loudly，并报告 build provenance。

### E4 — 第一战根枚举库与 portable replay

**状态：实施完成（2026-09-13），Root gate 证据见本节；合并决定由项目维护者复核。**

结果与证据摘要（pinned build `A1F9E653…` / `v0.107.1`，见 `docs/persistent-environment-evidence.md`）：

1. 新增 `python/sts2_native_sim/first_combat.py`：按 E4 结果要求枚举一个 `seed + character + ascension` 的全部合法 Neow 分支与第一战路线，并在 `combat.turn == 1 && combat.phase == Play` 精确边界产出结构化根记录。只跟随协议真实暴露的 legal actions（`choose_event`、`choose_cards`、`choose_option`、`choose_custom_reward`、`skip_custom_rewards`、`proceed_neow`、`choose_map`），不伪造无玩家选择的 RNG 分支。
2. 分支身份由有序 action trace 决定（`branch_identity`），不按 deck/relic/遭遇/状态 hash 去重：九个 fixture 共记录 656 条分支，但只有 5/3/4/12/27/4/68/4/27 个不同根 hash，收敛到同一战斗状态的多个首层 map 点仍是独立记录。
3. 节点一律用 run-start 配方重演（`neow_run_reset` + 记录动作），不依赖兄弟分支的 mid-tree restore 或 resident-prefix；因此每个根记录本身就是 E4 要求的 replay recipe：`neow_run` provenance、记录的动作历史、根 hash 期望值，外加根观测、合法动作、完整 Run RNG counters、build 身份与首层路线（坐标、节点类型、敌人）。
4. `EnumerationLimits` 显式限制每分支动作数、根数与展开节点数；触顶、遇到 terminal/unsupported decision 或无合法动作都写入 `EnumerationFailure` 并把该 seed 标为 `complete=False`，`assert_complete()` 拒绝把截断结果当作完整语料；另外输出按稳定排序（根按 trace、失败按 reason+trace+detail）并用 canonical 未压缩字节序列化。
5. 正向证据（`python/first_combat_root_acceptance.py`，四 worker，9 个 fixture：Large Capsule / Phial Holster / Small Capsule / New Leaf / Leafy Poultice / Scroll Boxes / Neow's Bones / Ironclad A10 Scroll Boxes / Defect 广度样本）：882 次决策节点展开得到 656 个根（15/9/8/36/108/16/340/16/108）。每个 fixture 经两种 worker 轮换各枚举一次（同一 fixture 必落在两个不同 worker 上），两次的 branch identities、root hashes、action traces 与 canonical 未压缩记录字节完全一致；首个 fixture 另外在同一 worker 上重复枚举两次，字节同样一致。
6. 每个根都满足 Turn 1 / Play，具备 `play_card`/`end_turn` 合法动作、八个 combat RNG 流全部可见、完整 build 身份、row 1 `Monster` 路线与敌人，以及 provenance 为 `neow_run`、history 等于 trace、expected hash 等于根 hash、reset request 恰为四个开局字段的 portable branch。
7. 同 worker replay、local fork restore、跨 worker portable restore 三条路径在每个 fixture 各抽 4 个根（共 36 个）执行，hash/observation/legal actions 全部逐字节一致；restore 证据取 worker 自身的 `last_restore`：`path == "replay"`、`replayed_actions` 等于 trace 长度（3–6）且大于 0、`synthetic_combat_installed == false`，并且验证前先把 worker 移离根状态、移离动作未改变状态则直接报错，避免把 resident-prefix no-op 当作重建证据。
8. 负向证据：`max_actions_per_branch=1` 与 `max_roots=2` 分别产生 `action_cap`/`root_cap` 失败、`complete=False`、`assert_complete()` 抛错，且 cap 下仍被产出的根全部通过边界断言；Neow 决策态被根断言拒绝；篡改根分支 `expected_hash` 以 `replay_divergence` 失败并只污染尝试它的那个 worker，pool 替换该 worker 后未篡改配方恢复正常，证明篡改是唯一原因。`tests/test_first_combat.py` 用不实现 `restore` 的假 worker 离线覆盖同一套枚举逻辑（分支调度、全部失败原因、caps、排序、canonical 字节稳定性、去重规则）。
9. 构建与回归：仅新增 Python 库、acceptance 与离线测试，未改动 C# 或 client 协议；`python/acceptance.py`、`python/portable_modes_acceptance.py`、`python/neow_run_acceptance.py` 行为不变（direct reset hash 仍为 `CEE9B22A…DBEF7B`，证据与命令见 `docs/persistent-environment-evidence.md` 的构造边界与 E1/E2 回归对比节）。

**结果**

提供可被 CLI、测试和后续训练复用的 Python 库，枚举合法 Neow 分支和第一战路线，在精确边界产出结构化根记录。

**建议修改面**

- 新增 `python/sts2_native_sim/first_combat.py`
- 新增 `python/first_combat_root_acceptance.py`
- `python/sts2_native_sim/__init__.py`

**Fixed**

- 只枚举协议实际暴露的 legal actions；generated outcome 若没有玩家选择，不伪造额外 RNG 分支。
- 每条分支记录有序 action trace；不得按表面 deck/relic tuple 去重。
- 第一版枚举所有 Neow/event/native nested choices；在 E0 证实“首层即 combat”的支持矩阵内，枚举所有当前合法且会原生进入 combat 的首层 map action。若 E0 证伪该假设，先由决策所有者确定跨非战斗房间的范围与分支预算。
- 若路径未到 Turn 1 / Play、进入未支持房间、超过显式 branch/depth cap 或没有合法动作，写明失败并将该 seed 标为不完整；不得把截断结果算作有效完整语料。
- 根记录中的 portable branch 是 replay recipe；跨 worker 恢复后必须校验 expected hash。

**Local**

- DFS/BFS、内存中的 dataclass/TypedDict、branch scheduling 顺序；输出顺序必须通过稳定排序保持确定性。

**验证**

- 同输入重复两次产生相同 branch identities、root hashes、action traces 和 canonical 未压缩记录字节（排除时间/路径等非确定字段；gzip header、文件名和 shard 布局不参与比较）。
- 每个 root 都满足 Turn 1 / Play，具有 combat legal actions、完整 Run RNG counters 与 build 信息。
- local fork restore、同 worker replay、跨 worker portable replay 三条路径的 hash/observation/legal actions 一致；检查 restore transition 与 `replayed_actions`，避免把 resident-prefix no-op 当成真正重建证据。这三条只证明等价性，不证明 keyframe 或低成本恢复。
- 专项 fixtures：Phial Holster、New Leaf、Leafy Poultice、Neow's Bones、Scroll Boxes、Small Capsule、Large Capsule、A10+。

### E5 — FullApp 权威投影与 golden differential

**状态：实施完成；根比较缺陷已发现并修复（2026-09-13，离线测试通过）；两份 manifest 尚未在修复后的实现上重跑，磁盘上 targeted 的 39/39 记录由修复前的实现产出，breadth gate 未关闭。**

**结果**

补齐只读、无桌面操作的 FullApp 第一战根投影，并建立 fast path 对 shipped application 的冻结差分门。

**主要修改面**

- `src/Sts2.NativeSim.FullAppBridge/ProtocolMessages.cs`
- `src/Sts2.NativeSim.FullAppBridge/FullAppStateTracker.cs` 及相关 bridge 文件
- 新增第一战 root/trajectory differential runner；复用现有 differential comparator 能力

**Fixed**

- 投影至少覆盖：角色/ascension/HP/gold、完整 deck 和 combat piles（含 instance/upgrades/native state）、relic identity/counter/native state、potion capacity/slots/content、encounter/enemies/intent/powers、角色资源、全部 Run RNG counters、legal actions、原生 `combat.turn`、原生 `PlayerCombatState.Phase` 和 build identity。根比较必须显式证明 `turn == 1 && phase == Play`，不得用 bridge 外层的 `phase == "combat"` 代替。
- 投影保持只读；不得操控可见窗口或依赖 UI presentation 状态。
- FullApp 与 fast path 仅在 schema 对齐字段上比较；缺字段是 gate failure，不得用“忽略差异”通过。
- 必须通过 E0 确认的原生 seam，把 requested ascension 实际应用到 FullApp run 并验证观测值；这项修复归 E5 所有。在此之前 A>0 样本不得进入 golden 结果。
- 比较器必须为 event、全部 Neow nested choices、play card、potion、target 与 end turn 建立无歧义的语义 action key，再各自翻译成本地 action。共同投影必须提供稳定 card occurrence/instance 与 target identity；不得把 filtered ordinal 当 native option index，也不得把 hand index 当跨环境 card identity。语义身份缺失或重复时 fail loudly。
- root 相同后，还要用同一确定性语义合法策略逐 action 比较完整第一战；只比较初始 hash 不足以验收。统一终点固定为“玩家死亡，或原 encounter 已无存活敌人且尚未执行 `generate_room_rewards`/进入下一 run decision”。FullApp 必须暴露等价的 `combat_complete`/奖励前末状态，比较器只可归一化协调器包装，不得跳过最后一次 combat 状态差异。

**验证梯度**

1. targeted manifest：覆盖五角色、A0/A10 和七类高风险 Neow 结果；
2. breadth manifest：至少 100 个冻结 seed，交叉五角色与代表 ascension；
3. breadth 全量比较根；每个 character/ascension cell 及每个高风险结果至少一条完整战斗逐步 replay；
4. 报告 error/cap/unsupported 数量，并固定 exact game build。任何 mismatch 都保留原始 seed/branch/action 以复现。

**实现与证据（2026-09-13）**

- 运行器：`python/first_combat_differential_acceptance.py`（比较器 `python/sts2_native_sim/first_combat_differential.py`，离线测试 `tests/test_first_combat_differential.py`，一键脚本 `scripts/run-e5-differential.ps1`）。
- targeted manifest（13 个 fixture × 3 个抽样 root = 39 条，全部逐步走到统一终点）：修复前的实现记录到 **39/39 match、0 error、0 mismatch、0 cap**，共比较 504 个 boundary / 355 个 combat step，全部终点为 `player_death`。**该记录由修复前的比较器产出**（`compared_roots` 为空、未在根边界显式断言），重跑前不得作为最终证据引用；A0/A10 与五角色均由 fixture 覆盖。
- breadth manifest 已冻结为 **100 个不同 seed**，每个 seed 钉定一个 (角色, ascension) 单元，十个单元各 10 个 seed。十条（每单元一条）以 `stop=endpoint` 走到统一终点（计划要求的"每 cell 一条完整第一战逐步 replay"），其余 90 条以 `stop=root` 沿同一确定性策略走到第一战根，并在两侧显式断言 `combat.turn == 1 && combat.phase == Play`（`assert_root_boundary`，含出厂侧的 declared == observed encounter）。**重跑待做**；磁盘上无 breadth 报告，运行命令见 [persistent-environment-evidence.md](persistent-environment-evidence.md)。
- 决策策略：有录制 trace 时按 trace，否则取字典序最小的语义动作键（wrapper 除外），两侧取同一决定；战斗因此由该策略驱动而不是出厂侧自己的偏好——实测在战斗内恒取 `end_turn`（`tests/test_first_combat_differential.py` 固定该行为）。因此"完整第一战"证明的是根边界、每边界合法性/投影与终点分类，**不覆盖打牌/药水效果的真实执行**（那一轴属于 `differential_campaign.py`）。每条记录用 `stop` 与 `decision_kinds`、汇总用 `stops`/`compared_roots`/`decision_kind_counts` 明示实际执行了什么。
- 比较器缺陷与修复（2026-09-13，修复后离线测试通过、游戏侧待重跑）：`run_entry` 原来在 `trajectory=False` 时于**第一个非 wrapper 边界**即返回，而一次全新 run start 的首个此类边界是 **Neow 事件决策**，于是 breadth 的 90 条"比根"实际只比了 Neow 选项，从未到达第一战根，与本单元 Fixed 第 1 条"根比较必须显式证明 `turn == 1 && phase == Play`"相矛盾。修复：`run_entry` 改为 `stop="root" | "endpoint"`，到达根边界时两侧都调用 `assert_root_boundary`（`root` 模式在此收束，`endpoint` 模式记录 `root_status` 后继续到统一终点），到不了根则以 `budget` 阶段 fail loud。离线回归测试覆盖该缺陷、收侧未证根、根不可达、以及 endpoint 轨迹同样要自证根。
- 唯一 unsupported 项：`discard_potion`（reconstruction 会暴露丢弃药水动作，bridge 的回合决策面没有该动作）。比较器把它列入 `unsupported_kinds` 而不是静默丢弃；所有已比较轨迹都未取用该动作。
- E5 期间在 bridge 只读投影中修正了三处真实缺陷（均为投影缺口，不是 reconstruction 行为差异）：Neow 遗物在战斗开始时打开的嵌套卡牌选择会丢失 combat 投影；`NRewardsScreen` 在 `WithSkippingDisallowed`（Neow's Bones）时禁用的 skip 按钮曾被当作合法 `proceed`；`CardReward` 的候选卡改为融合动作 `choose_reward:{r}:Card:{i}:{CARD}` 暴露。三处都记录在 [full-application-control-bridge.md](full-application-control-bridge.md)。

**声明边界**

通过只证明列入 manifest 的 Neow→第一战前缀和第一战轨迹；每条根比较在两侧显式断言 Turn 1 / Play，每条轨迹的终点为"玩家死亡，或清场且未执行 `generate_room_rewards`"。战斗由两侧同一确定性最小语义键策略执行，实际动作种类由报告字段固定，因此不构成打牌/药水效果覆盖。不扩展为全局 simulator certification，也不证明策略质量。

### E6 — 队列式语料 farm、schema 与发布门

**结果**

新增 `generate_first_combat_corpus.py`，以 persistent worker queue 消化异构 seed/branch 工作量，写出可审计、可恢复、不会数据泄漏的第一战根 shards。

**主要修改面**

- 新增 `python/generate_first_combat_corpus.py`
- 复用 `python/native_rollout_farm.py` 的 worker/metrics/shard 模式，不复制策略训练逻辑
- 新增纯 Python schema/split/serialization tests
- 更新 `docs/persistent-environment.md` 的接口契约与 `docs/persistent-environment-evidence.md` 的证据记录；仅在证据门通过后更新 `docs/project-status-and-review-guide.md`

**Fixed**

- 每条有效 root 记录：corpus schema version、simulator commit、game build version/assembly/PCK SHA-256、seed/character/ascension、完整有序 Neow trace、route coord/encounter、root hash/observation/legal actions/Run RNG counters、portable replay recipe 或其内容 hash。
- 错误、cap、unsupported 与 worker restart 形成显式记录和汇总；不得静默丢 seed。
- split 使用稳定、文档化的 seed hash 或冻结 manifest；同一 seed 的全部 Neow/route branches 必须同 split。
- 输出默认位于已忽略的 `artifacts/`；CLI 不提供把游戏二进制/资源嵌入语料的路径。
- 原始 root 生成与后续 policy/value labels 分层；本模块不宣称或执行模型 promotion。

**验证**

- 小型固定 manifest：1/4/20 worker 输出的有效 root identity 集合相同；允许 shard 布局不同，不允许内容集合不同。
- 中断后按 manifest 恢复不会重复或漏记 root；重复运行的 canonical 未压缩 root record 内容 hash 稳定。
- 20-worker soak 报告吞吐、内存、worker restart、错误、cap 和有效率，且零 unmanaged abort。
- public-tree 检查确认没有生成语料、游戏资源、存档或私有数据进入 git。
- broad validation：`python -m compileall -q python tests`、`python -m pytest -q`、`pwsh scripts/test-public-tree.ps1`，并构建所有受影响 C# 项目。

### E7 — 可选：跨 worker 原生 combat keyframe 调查

**触发条件**

仅当 E4/E6 的 build-pinned benchmark 表明“Neow→第一战前缀重放”是训练吞吐的主瓶颈，且 local `CombatSnapshot` 不能满足 worker 调度需求时启动。

**研究问题**

能否在不遗漏 active continuation、choice coordinator、combat manager、player/relic/potion native state 与 RNG 的前提下：

1. 先允许 run-mode 的 Turn 1 / Play root 在同一 worker 使用现有 `CombatSnapshot` 快速 restore；
2. 若仍有收益需求，再导出并在另一 worker 恢复完整 combat keyframe？

**允许产出**

- disposable probe、字段清单、失败案例、性能数据和推荐；
- 不得在未通过 exact full-combat differential 前将该路径设为默认或称为 certified snapshot。

**决策门**

项目维护者根据正确性覆盖、复杂度、恢复耗时和 replay 基线收益决定接受、延期或拒绝。若接受，再另立实现计划并更新相关架构/状态文档。

## 6. 实际交接拓扑

### 交接 A — Core 生命周期与 Neow RPC（E1→E3）

- **接收者能力**：熟悉 C# reflection/native lifecycle、异步 choice coordinator 和协议兼容性。
- **治理来源**：本计划第 1–3 节、调查报告第 9–12/24–27 节、`docs/persistent-environment.md`。
- **可改范围**：Protocol、Core、Host/GodotHost、对应 focused acceptance 与必要文档。
- **不得改**：逐遗物模拟、训练代码、FullApp 权威规则、现有 direct reset 合约。
- **开始条件**：E0 已给出当前 pinned build 的唯一原生 Neow lifecycle，或由决策所有者明确接受受限支持范围。
- **完成顺序**：E1 行为保持提交 → E2 run/restore provenance 提交 → E3 Neow 垂直切片提交；每一步独立可回滚、可验收。
- **升级触发器**：shipped build 中 Neow 启动必须依赖未建模 UI 状态；保持 Player/RunState identity 与现有 event machinery 冲突；协议兼容需要破坏旧 portable branch。

### 交接 B — FullApp golden projection（E5，可与 E1/E2 并行）

- **接收者能力**：熟悉 FullApp bridge、只读 state extraction、差分 schema。
- **治理来源**：调查报告第 18/24/27 节、`docs/full-application-control-bridge.md`、`docs/differential-trace-format.md`。
- **可改范围**：FullAppBridge 只读投影、第一战 differential fixtures/runner。
- **不得改**：可见桌面控制、NativeSim 行为、通过省略字段掩盖 mismatch。
- **接口依赖**：先与交接 A 冻结共同 root projection 与语义 action key；不依赖 E3 实现即可补 FullApp 字段，A>0 gate 依赖 E0 的 ascension 结论，最终 differential 依赖 E3/E4。
- **升级触发器**：字段只能从 UI presentation 获取；读取字段会改变游戏状态；同一 shipped build 无法稳定取得 RNG/native state。

### 交接 C — Python 根生成与 farm（E4→E6）

- **接收者能力**：熟悉 persistent worker、fork/restore、确定性遍历与 shard/manifest 数据工程。
- **治理来源**：本计划第 1–5 节、调查报告第 13–17/21–23/26–28 节、`python/native_rollout_farm.py`。
- **可改范围**：`python/sts2_native_sim` 第一战库、focused acceptance、corpus CLI、schema tests、运行文档。
- **不得改**：游戏机制、Neow 策略偏好、模型训练/promotion、默认开启未经批准的 keyframe 格式。
- **开始条件**：E3 的 RPC、decision/action contract 与 reset provenance 已冻结；E4 可先用小型 fixture，E6 发布必须等待 E5 golden gate。
- **升级触发器**：合法 action 图出现循环/无界分支；第一层合法路线不进入 combat；branch cap 会系统性截断某类 Neow；portable replay 在相同 build 上 hash 不一致。

共享 mutable scope 集中在协议字段和 observation schema。交接 A 与 B 在编码前先冻结字段清单；除此之外避免多人同时修改 `PersistentNativeCombatEnvironment.cs` 或 `python/sts2_native_sim/client.py`。

## 7. 合并与声明门

1. **Refactor gate**：E1 全回归通过，无 observable change。
2. **Run lifecycle gate**：E2 证明 run/restore 无 synthetic combat。
3. **Neow gate**：E3 四 worker determinism、fork isolation、同对象连续性和高风险 fixture 通过。
4. **Root gate**：E4 所有有效根均为 Turn 1 / Play，三种 restore 路径一致。
5. **Authority gate**：E5 冻结 manifest 根差分和代表性完整战斗差分为零；unsupported/error/cap 为零，或以明确不支持状态阻止发布。
6. **Farm gate**：E6 worker-count invariance、resume、soak、public-tree 和 broad validation 通过。
7. **Documentation gate**：更新 `docs/persistent-environment.md` 的实际接口与 `docs/persistent-environment-evidence.md` 的证据；只有当前能力确实改变时才修改 `docs/project-status-and-review-guide.md`。不得把 corpus 生成成功写成策略质量或全局 certification。

## 8. Re-plan 条件

出现以下任一证据时停止受影响执行包并回到设计/决策所有者：

- 需要在 Neow 与第一战之间替换 `Player` 或 `RunState`；
- 需要在 NativeSim/Python 中重实现具体 Neow 遗物或卡牌效果；
- shipped build 与调查使用的行为不符，且 FullApp trace 不能确认预期；
- 为取得 golden 字段必须操控 UI 或弱化 headless/fail-loud 边界；
- 需要破坏现有 public protocol/portable replay 而没有显式迁移方案；
- 需要把完整 active-combat serializer 作为首版正确性的前置条件；
- 范围扩展到第一战之后的 Player RNG、奖励、商店、事件或完整 run fidelity。
