# E0 报告：Neow 与 FullApp 启动契约探针（build-pinned）

状态：**探针证据完成（2026-09-13）；§7 E3 入口契约已由项目维护者确认（2026-09-13），可据此执行 E3**
日期：2026-09-13
上游：[first-combat-scene-generation-plan.md](first-combat-scene-generation-plan.md) §5 E0
治理调查：[first-combat-neow-investigation-report.md](first-combat-neow-investigation-report.md)

本报告只记录 E0 的只读/一次性探针证据与由此得出的入口契约。它不提升机械忠实度、执行广度或策略质量声明，也不授权任何 E3 实现改动。

---

## 1. 本次证据的 build 指纹

| 项 | 值 |
| :--- | :--- |
| 游戏版本 | `v0.107.1`（`release_info.json`: `commit 59260271`, `branch v0.107.1`, `date 2026-06-18`） |
| `sts2.dll` SHA-256 | `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52` |
| `SlayTheSpire2.pck` SHA-256 | `42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587` |
| `sts2.dll` ProductVersion | `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314` |
| 引擎 | Godot `4.5.1.stable.mono` |

与 [version-compatibility.md](version-compatibility.md) 记录的 pin 一致。所有结论仅在上述指纹下成立。

## 2. 探针与执行约束（先决条件）

E0 允许的两类证据都执行了：pinned assembly 的只读 reflection/API 探针，以及 headless `full_application_native` 的最小 start→Neow→map trace。

**关键约束：shipped run 生命周期不能在普通 console 进程里执行。** 实测两条硬崩溃链：

```text
RunManager.SetUpTest → PeerInputSynchronizer..ctor → Logger..cctor
  → Logger.GetIsRunningFromGodotEditor → Godot.OS.GetCmdlineArgs    → 0xC0000005（进程终止）

LocManager.Initialize → SetLanguage → LoadTablesFromPath
  → Godot.DirAccess.DirExistsAbsolute                                → 0xC0000005（进程终止）
```

因此探针必须运行在 **Godot 引擎上下文**（headless Godot，与仓库既有 `NativeSim.GodotHost` 的执行模型一致）。在引擎上下文并挂载 pinned PCK 后，本地化正常初始化（`language=eng`，日志 `Loading locale path=res://localization/eng`）。

**展示抑制 seam（探针用，非契约）。** 探针使用 shipped 测试 seam `TestMode.IsOn = true`，因为 `ClearScreens`、`FadeIn`、`PreloadManager.LoadActAssets/LoadRoomEventAssets`、`NEventRoom.Create`、`NCombatRoom.Create`、`EventModel.GetAssetPaths` 都显式受 `TestMode` 保护。注意 pinned 源码中 `ModManager.Initialize` 在 `TestMode.IsOn` 时直接令 `State = Skipped`：**测试 seam 与游戏 mod 加载互斥**。仓库现有快路径的做法相反（全局 TestMode 保持 off，改用有审计范围的 Harmony presentation seam）。本契约只依赖 lifecycle，不依赖具体 seam；E3 应复用仓库既有的 scoped seam，而不是把全局 TestMode 当作生产开关。

**补充 seam。** `EventSynchronizer.BeginEvent` 通过 `TaskHelper.RunSafely` 以 fire-and-forget 方式启动事件，直接读取 `CurrentOptions` 会得到 0 个选项（实测报错 `attempted to choose option index 0 in event EVENT.NEOW, but there were only 0 options available`）。探针安装 Harmony postfix 捕获该 task 并 await，与 `PersistentNativeCombatEnvironment` 既有的 `CaptureScopedScheduledTask` seam 同型。

**探针工件（未提交，均位于被忽略的 `artifacts/`）。**

| 工件 | 内容 |
| :--- | :--- |
| `artifacts/e0-probe/` | 探针源码（console 与 Godot 宿主共享同一份 `ProbeRunner`） |
| `artifacts/e0-probe-godot/` | 一次性 Godot 宿主工程 |
| `artifacts/e0-probe/out/godot-run4.json` | 引擎宿主探针证据（签名清单、360 样本 sweep、5 条 Neow slice） |
| `artifacts/e0-probe/out/fullapp-trace.json` | FullApp 最小 trace 证据 |
| `artifacts/e0-probe/fullapp_trace.py` | FullApp trace 驱动脚本 |

按计划要求，游戏资源、存档、trace 与 disposable 探针输出都不进入 git（`git status` 干净，`artifacts/` 已忽略）。

## 3. Q1：忠实启动 Neow 需要哪些 UnlockState / run flags，走哪条 seam

**结论**

1. 唯一相关的 run flag 是 `ExtraRunFields.StartedWithNeow`（pinned 成员仅为 `StartedWithNeow` / `TestSubjectKills` / `FreedRepy`）。它由 `RunManager.InitializeNewRun → SetStartedWithNeowFlag` 从 `State.UnlockState.IsEpochRevealed<NeowEpoch>()` 派生，不接受外部直接设置。
2. `RunState.UnlockState` 是各 `Player.UnlockState` 的并集（`RunState.CreateShared`），所以**真正的前置条件是传入 `Player.CreateForNewRun(character, unlockState, netId)` 的 unlock profile 里 `NEOW_EPOCH` 已 reveal**。
3. 忠实启动路径就是游戏自己的 **starting Ancient map point（真实 event room）**，不是另一条独立 run-start seam，也不是 standalone `event_reset`。

**实测（引擎宿主，pinned assembly）**

| unlock profile | `StartedWithNeow` | `StartingMapPoint.PointType` | 样本 |
| :--- | :--- | :--- | :--- |
| `UnlockState.all` | `true` | `Ancient` | 120 |
| 仅 reveal `NEOW_EPOCH` | `true` | `Ancient` | 120 |
| 空 epoch 集合 | `false` | `Monster`（被强制改写） | 120 |

进入起始节点后（`EnterMapPointInternal(actFloor: 1, MapPointType.Ancient, preFinishedRoom: null, saveGame: false)`）：

```text
base_room_type = Event        event_id = NEOW        event_type = ...Models.Events.Neow
act_floor = 1                 room_stack_depth = 1   Hook.ShouldAllowAncient = true
map_history   = [{ point_type: Ancient, rooms: [{ room_type: Event, model_id: NEOW }] }]
options       = 3（2 个 positive + 1 个 cursed），例如
                0=LAVA_ROCK 1=PRECISE_SCISSORS 2=SILKEN_TRESS
```

5/5 slice 都是 `event_id = NEOW`、`ShouldAllowAncient = true`、3 个选项；观察到的 cursed 选项覆盖 `SILKEN_TRESS`、`PRECARIOUS_SHEARS`、`HEFTY_TABLET`、`NEOWS_BONES`；positive 覆盖 `LAVA_ROCK`、`PRECISE_SCISSORS`、`STONE_HUMIDIFIER`、`PHIAL_HOLSTER`、`NEW_LEAF`、`LOST_COFFER`。

**失败反例（两台独立证据）**：新档 profile 没有 Neow。

- 引擎探针：`ProgressState.CreateDefault()` → `epochs=0`，`neow_revealed=false`。
- shipped app 自己写出的 `progress.save`（fresh sandbox，`--force-steam=off` 的 `default/1` profile）：`"epochs": []`、`"ftue_completed": []` → `StartedWithNeow=false` → `GenerateMap` 把起始点强制改成 `Monster`，**整局没有 Neow**。

因此 E3 必须显式固定 unlock profile（例如“所有 epoch revealed 的 profile” 或某一具体 profile），并把 `StartedWithNeow` 记入 provenance；否则同一 seed 在不同 profile 下会走完全不同的第一层世界。

**执行的 seam 序列（探针实际调用，全部为 pinned 公开/测试 API）**

```text
Player.CreateForNewRun(character, unlock, netId: 1)
RunState.CreateForNewRun(players, acts(ToMutable), modifiers, GameMode.Standard, ascension, seed)
RunManager.SetUpTest(state, NetSingleplayerGameService, disableCombatStateSync: true, shouldSave: false)
RunManager.GenerateRooms()
await RunManager.GenerateMap()
await RunManager.EnterMapPointInternal(1, MapPointType.Ancient, null, saveGame: false)
```

生产等价物是 `RunManager.SetUpNewSingleplayer(state, shouldSave, dailyTime)`（`InitializeShared + InitializeRunLobby + InitializeNewRun + GenerateRooms`）；`NGame.StartRun` 之后再 `EnterAct(0)`，而 `EnterAct(0)` 在 `StartedWithNeow` 为真时直接 `EnterMapCoord(StartingMapPoint)`。

**依赖的 pinned 签名（节选，全部由探针从 assembly 读出）**

```text
RunManager: Void SetUpTest(RunState, INetGameService, Boolean disableCombatStateSync, Boolean shouldSave)
            Void SetUpNewSingleplayer(RunState, Boolean shouldSave, Nullable<DateTimeOffset> dailyTime)
            Void GenerateRooms()
            Task GenerateMap()
            Task EnterMapPointInternal(Int32 actFloor, MapPointType, AbstractRoom preFinishedRoom, Boolean saveGame)
            Task EnterAct(Int32 currentActIndex, Boolean doTransition)
            Void ApplyAscensionEffects(Player)
RunState:   static RunState CreateForNewRun(IReadOnlyList<Player>, IReadOnlyList<ActModel>, IReadOnlyList<ModifierModel>, GameMode, Int32 ascensionLevel, String seed)
Player:     static Player CreateForNewRun(CharacterModel, UnlockState, UInt64 netId)
UnlockState: Boolean IsEpochRevealed()   // generic
EventModel: Task BeginEvent(Player, Boolean isPreFinished)
EventRoom:  Task EnterInternal(IRunState, Boolean isRestoringRoomStackBase)
MapTravel:  static IEnumerable<MapPoint> GetTravelablePointsFrom(IRunState, MapPoint currentPoint)
TestMode:   public static Boolean get_IsOn() / set_IsOn(Boolean)
```

## 4. Q2：Neow 完成后如何回到地图，以及对象连续性

**结论**

1. Neow 是普通 `EventRoom`；事件结束后**没有** RunManager 级别的“回到地图”调用。返回值地图是**纯 presentation**：`NEventRoom.Proceed()` → `NMapScreen.SetTravelEnabled(true)` + `NMapScreen.Open()`。它既不退出房间栈，也不替换 `Player`/`RunState`。
2. 因此 headless 环境里的“Neow 完成 → map_choice”等价物是：事件 `IsFinished` 后，按模型层算出合法选项 `MapTravel.GetTravelablePointsFrom(runState, StartingMapPoint)`（非自由移动时返回 `currentPoint.Children`），再由环境自行暴露为 `map_choice`。这是环境的状态机接线，不是重新实现游戏机制。
3. Player/RunState/Creature 在 Neow 前后保持同一对象。

**实测证据**

```text
identity（RuntimeHelpers hash，before → after 解析 Neow option 0）
E0PROBE0001 A0  player 10749951→10749951  run 5531635→5531635  creature 4802396→4802396
E0PROBE0002 A0  player 52692618→52692618  run 13915403→13915403  creature 46682518→46682518
E0PROBE0003 A0  player 60505468→60505468  run 48373580→48373580  creature 24876774→24876774
E0PROBE0004 A0  player 38103338→38103338  run 25581352→25581352  creature 64122126→64122126
E0PROBE0005 A10 player 10167433→10167433  run 65067768→65067768  creature 40574624→40574624
```

Neow 选项生成后的 run RNG counters（seed `E0PROBE0001`，Neow 进入时）：

```text
UpFront = 417      Shuffle = 0    MonsterAi = 0    CombatCardGeneration = 0
CombatCardSelection = 0   CombatEnergyCosts = 0   CombatTargets = 0
CombatPotionGeneration = 0   CombatOrbs = 0   Niche = 0   TreasureRoomRelics = 0
```

即 Neow 选项只用 event-local RNG（`EventModel.BeginEvent` 里 `new Rng(seed + slot + hash(eventId))`），**不消耗任何战斗相关 run RNG 流**；调查报告 §6.1 在 pinned build 上得到确认。

**嵌套选择是真实存在的。** 选择 `NEW_LEAF`、`LOST_COFFER`、`PRECISE_SCISSORS` 后事件仍 `IsFinished=false`（5 条 slice 中 3 条），说明这些 blessing 会 suspend 到 shipped 的卡牌选择机制；FullApp trace 也观测到同一步出现 native card-selection 提示。E3/E4 必须走 shipped 选择机制，不能按遗物 ID 写效果分支。

**陷阱（契约必须包含）。** 直接调用 `EnterMapPointInternal(..., saveGame: false)` 不会更新 `State.VisitedMapCoords`（实测 `visited_coords` 为空），而生产路径 `EnterMapCoord` 会先 `State.AddVisitedMapCoord(coord)`。E3 要么显式补这一步，要么接受并记录该差异；否则后续 `MapLocation`/旅行状态与原生不一致。

## 5. Q3：第一层合法 map point 是否恒为 combat

**结论：是。** 在 pinned build 的支持矩阵内，起始点的所有 children（row 1）恒为 `Monster`；因此“第一战路线”**不需要**穿越任何非战斗 decision，E4 不需要为非战斗首层房间设计分支预算。

**实测矩阵**：3 种 unlock profile × 5 角色（IRONCLAD / SILENT / DEFECT / NECROBINDER / REGENT）× A0 / A10 × 12 seeds = **360 样本，0 violations**。

| 观测 | 结果 |
| :--- | :--- |
| `StartingMapPoint` children 类型 | 全部 `Monster`（每样本 2–3 个），去重后仅 `Monster,Monster` 与 `Monster,Monster,Monster` |
| row 1 全行类型 | 只有 `Monster` |
| 起始点类型 | `StartedWithNeow` 为真 → `Ancient`；为假 → 强制 `Monster` |
| 地图规模（seed `E0PROBE0001`） | 49 points / 16 rows |

`full_application_native` 交叉验证：seed `E0FULLAPP01` 在 Neow 之后的地图决策暴露 `1:Monster, 2:Monster, 3:Monster`，选择其一后进入 `phase=combat`、`combat.turn=1` 并给出 `play_card:*` / `end_turn` 合法动作。

**覆盖限制**：每格 12 seeds；仅 Act 1（`StandardActMap`，非 `SpoilsActMap`/`GoldenPathActMap`）；仅 `GameMode.Standard` 单玩家。其他 act、其他 map 实现与自定义 mode 未探针，不得外推。

## 6. Q4：FullApp 的 requested ascension 是否写入原生 run

**结论：没有。requested ascension 只被回显，从未写入原生 run；实测原生值是 profile 的 preferred ascension。**

**repo 侧证据（本仓库代码，非反编译）**

- `FullAppBridgeServer.RequestedAscension` 仅在 `hello` / `start_run` / `history` 响应里回显。
- `FullAppBridgeMod.OnBeginRunForAllPlayers` 只设置 `NGame.Instance.DebugSeedOverride` 与 `__instance.SetLocalCharacter(targetChar)`；没有任何 `SyncAscensionChange` 或 `StartNewSingleplayerRun(..., ascensionLevel, ...)` 调用。
- `FullAppStateTracker.Ascension = runState?.AscensionLevel ?? 0`，所以 observation 里读的是**原生**值——差异可观测。

**实测（headless FullApp，pinned build，seed `E0FULLAPP01`，请求 `ascension: 5`）**

```text
start_run echo        : character=IRONCLAD  ascension=5      （请求回显）
first boundary        : phase=event  event=Neow  act=1 floor=1  room_options=3
observation.ascension : 10                                    （原生 RunState.AscensionLevel）
deck_size = 11        ascenders_bane_count = 1                （A10 原生效果已生效）
first combat          : combat.turn = 1, legal_actions = play_card:* / end_turn
```

请求 5、原生 10，且 A10 的 `ASCENDERS_BANE` 恰好出现一次 → requested ascension 完全未参与 run 构造。

**正确的 native start seam（两条，均由 pinned 签名确认）**

1. 生产 seam：`NGame.StartNewSingleplayerRun(CharacterModel, Boolean shouldSave, IReadOnlyList<ActModel>, IReadOnlyList<ModifierModel>, String seed, GameMode, Int32 ascensionLevel, Nullable<DateTimeOffset> dailyTime)`，内部 `RunState.CreateForNewRun(..., ascensionLevel, seed)`；`RunManager.InitializeShared` 随后用 `State.AscensionLevel` 构造 `AscensionManager`，`InitializeNewRun → ApplyAscensionEffects` 生效。
2. Lobby seam（当前 FullApp 走的路径）：`StartRunLobby.SyncAscensionChange(Int32)`（public，host 侧）必须在 `BeginRunForAllPlayersIfAllReady` 之前调用。

**并且必须满足 profile 前置条件**，否则原生钳制会静默把值改小：`BeginRunLocally` 对单人对局执行 `Ascension = Math.Min(Ascension, Progress.GetOrCreateCharacterStats(character).MaxAscension)`，`SetSingleplayerAscensionAfterCharacterChanged` 还要求 `IsAscensionEpochRevealed(character)`。实测：用 fresh profile 时该值会被钳到 0；用本地已解锁 profile 时钳到 profile 的 preferred（10）。所以 **E5 的 A>0 golden matrix 需要同时接线 seam 与固定 profile**，这正是计划 §3 缺口 7 的内容，归属 E5。

## 7. E3 固定入口契约（已由项目维护者确认，2026-09-13）

**执行环境**

- 在 headless Godot 引擎上下文中执行 shipped assembly（同 `NativeSim.GodotHost`），挂载 pinned PCK；普通 console 进程不可用（§2）。
- 展示抑制**确认沿用仓库既有 scoped Harmony presentation seam**；全局 `TestMode.IsOn` 保持 off，只作为本次一次性探针的手段，不作为生产开关。
- 必须保留 `TaskHelper.RunSafely` 任务捕获（Neow `BeginEvent` 是 fire-and-forget）。
- 不加载游戏 mod（`ModManager.State = Skipped`）；不使用 `[ModInitializer]`。

**固定序列**

```text
ConstructRun
  Player.CreateForNewRun(character, pinnedUnlockProfile, netId: 1)
  RunState.CreateForNewRun(players, acts.ToMutable(), modifiers, GameMode.Standard, ascension, seed)
  RunManager.SetUpTest(state, NetSingleplayerGameService, disableCombatStateSync: true, shouldSave: false)
  LocalContext.NetId = 1 ; CombatReplayWriter.IsEnabled = false
→ GenerateRooms()
→ await GenerateMap()
→ State.AddVisitedMapCoord(StartingMapPoint.coord)          // 生产路径 EnterMapCoord 会做这一步
→ await EnterMapPointInternal(1, MapPointType.Ancient, null, saveGame: false)
→ 捕获并 await BeginEvent 任务；初始结果必须是 decision.kind == event_choice 且 event id == NEOW
→ 用 shipped option/nested-choice 机制解析 Neow（不得按遗物 ID 分支）
→ 事件 IsFinished 后暴露 map_choice = MapTravel.GetTravelablePointsFrom(run, StartingMapPoint)
→ await EnterMapPointInternal(row + 1, MapPointType.Monster, null, saveGame: false)
→ 到达 combat.turn == 1 && PlayerCombatState.Phase == Play
```

**必须 fail loudly 的断言**

- `ExtraRunFields.StartedWithNeow == true`，`StartingMapPoint.PointType == Ancient`。
- 起始事件 id == `NEOW` 且初始选项数 > 0；`Hook.ShouldAllowAncient == true`。
- 所有可旅行首层节点类型 == `Monster`。
- Neow 前后 `Player` / `RunState` / `Player.Creature` 引用相同（不得重建）。
- 若 unlock profile 未 reveal `NEOW_EPOCH`、反射签名漂移、或 `saveGame` 需要置真，必须报错并附 build provenance，不得降级为 direct reset 或合成 post-Neow 状态。

**不得做**

- 不在 Neow 与第一战之间重建 `Player`/`RunState`；不使用 standalone `event_reset` 再拼接；不使用 `encounter = "first"` 代表自然第一战；不逐遗物实现 Neow 效果。

**保留给 E3 的 Local 决定**：`_runStage` 的内部表示、Neow 完成是自动回 map 还是显式完成 action、DTO 命名与非契约性诊断字段。

**契约确认记录**：2026-09-13 项目维护者确认 §7 全文，并选择“沿用现有 scoped Harmony presentation seam、全局 `TestMode` 保持 off”。E3 可据此执行；任何偏离上述 Fixed 项（尤其环境上下文、对象连续性、shipped 机制、fail-loud 断言）需回到决策所有者。

## 8. 对 E4 / E5 的连带发现

| 发现 | 归属 |
| :--- | :--- |
| FullApp 的 event observation 只有 `option_index`（`choose_event:<idx>`），**没有**遗物/native option 身份 | E5 必须补语义 action key，否则 Neow 分支无法与 fast path 对齐 |
| FullApp `combat_phase` 为 null：投影未暴露原生 `PlayerCombatState.Phase` | E5 必须显式暴露 `combat.turn` 与原生 phase，而非外层 `phase=="combat"` |
| FullApp run start 依赖完整 sandbox：缺少顶层 GDExtension 原生库（`libspine_godot.*` 等）时 char-select/其它场景解析失败，AutoSlayer 以 `Room type not assigned` 超时 | 运行文档/E5 环境记录 |
| FullApp 在 fresh profile 下拿不到 Neow（`epochs: []`）且 ascension 被钳到 0 | E5 golden matrix 的 profile 前置条件 |
| Neow 嵌套选择（`NEW_LEAF`/`LOST_COFFER`/`PRECISE_SCISSORS` 等）会 suspend 到 native card selection；FullApp 侧目前由 AutoSlayer 自动选一张 | E3/E5 共同语义动作键 |
| A10 起始牌组 `ASCENDERS_BANE` 恰好一次（IRONCLAD deck 11、SILENT deck 13；A0 分别为 10/12） | E3/E4 fixture 断言 |
| Neow 选项生成不消耗 Combat* / Shuffle / MonsterAi RNG 流 | E4 分支隔离断言可用 |

## 9. 未覆盖与证据边界

- 未做跨 worker determinism：本报告是单进程探针证据，四 worker 一致性属 E3/E4 门。
- 未验证 portable replay/hash 等价；本报告不含任何 keyframe 或低成本恢复声明。
- Q3 只覆盖 Act 1 / `StandardActMap` / Standard 单人，见 §5 限制。
- Q4 只证明“当前 FullApp 未应用 requested ascension”与“正确 seam 存在”，未实现修复；A>0 golden matrix 仍需 E5 完成接线与验证。
- FullApp trace 是**最小** trace（1 seed、1 角色、A5 请求），不是 golden differential。
- `E:\Home\projects\sts2-src` 的反编译源码只用于定位行为；本报告结论均以 pinned assembly 执行结果与仓库源码为准。

## 10. 复现步骤

```powershell
$dotnet = ".\.tools\dotnet9\dotnet.exe"
$godot  = ".\.tools\godot-4.5.1-mono\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_mono_win64_console.exe"
$asm    = "$env:STS2_GAME_ROOT\data_sts2_windows_x86_64\sts2.dll"

# 引擎宿主探针（签名清单 + 360 样本 sweep + Neow slices）
& $dotnet build artifacts/e0-probe-godot/E0GodotProbe.csproj -c Debug
$env:APPDATA = "$PWD\artifacts\godot-home\roaming"; $env:LOCALAPPDATA = "$PWD\artifacts\godot-home\local"
$env:DOTNET_ROOT = "$PWD\.tools\dotnet9"; $env:DOTNET_ROOT_X64 = "$PWD\.tools\dotnet9"
& $godot --headless --path "$PWD\artifacts\e0-probe-godot" -- $asm "$PWD\artifacts\e0-probe\out\godot.json" --with-localization

# FullApp 最小 trace（需先构建 bridge，并把操作者自己的 profile 复制到 seed-profile/）
& $dotnet build src/Sts2.NativeSim.FullAppBridge/Sts2.NativeSim.FullAppBridge.csproj -c Release
python artifacts/e0-probe/fullapp_trace.py
```

Godot 宿主必须以 `DOTNET_ROOT` 指向仓库 pin 的 .NET 9；否则 0Harmony 会以 `CoreCLR version 10.x is not supported` 拒绝打补丁。探针与 trace 输出都落在被忽略的 `artifacts/`。

## 11. 声明边界

- 本报告通过只证明：上述 pinned build 上 Neow 启动生命周期、Neow→map 转换、第一层节点组成，以及当前 FullApp 未应用 requested ascension。
- 不构成 `full_application_native` 与 fast path 的等价性证明（属 E5），不构成 simulator certification，不涉及策略质量，也不涉及 Neow 之后的 run fidelity。
- 探针为一次性工件，未提交；E3 按 §7 契约实现时需要新的 focused acceptance。
