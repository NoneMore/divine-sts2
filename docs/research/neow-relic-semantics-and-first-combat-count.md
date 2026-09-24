# 固定种子下涅奥遗物与第一战场景数

调查日期：2026-09-24。以下结论针对本仓库当前的单人、全解锁、无 modifier 第一战场景生成路径；游戏语义以相邻仓库 `../sts2-src/decompiled/MegaCrit/sts2` 中的反编译源码为准。本文所说的“语义不同”首先指**完整运行状态与后续游戏行为**，并另行指出不能由此推出第一场战斗内的行动转移必然不同。

## 当前生成器实际枚举的数量

在涅奥正常提供选项且三个分支都成功到达第一战时，**一个固定种子、角色、进阶难度的元素恰好产出 3 条场景记录**。`Neow.GenerateInitialOptions` 从允许的诅咒遗物选 1 个、从允许的正面候选选 2 个，按“正面、正面、诅咒”返回三个选项。[Neow.cs:215–278](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Events/Neow.cs#L215-L278)。生成器对每个提供的 Ancient 选项仅驱动一次，循环一轮写一行；失败分支也写一行，但其类型是失败记录，不计入成功场景。因此成功场景数可以是 **0、1、2、3**，正常完成的下界和上界都为 **3**。[生成循环](../../python/sts2_native_sim/_scenario_driver.py#L357-L390)、[失败行形成](../../python/sts2_native_sim/_scenario_driver.py#L410-L443)。

这不是所有玩家可达分支的枚举。遗物取得后可能打开选卡、选遗物或奖励界面，当前默认驱动只取每个嵌套提示的**首个合法动作**；离开涅奥后也只取首个可走的第一层地图节点。因此嵌套选择可以使固定种子的真实可达第一战状态多于 3 个，但**当前生成器不会因此多写场景**。[嵌套选择默认](../../python/sts2_native_sim/ancient.py#L114-L140)、[地图节点选择](../../python/sts2_native_sim/_scenario_driver.py#L462-L490)。不能从 `Neow.cs` 单独给出真实可达状态的一个通用最大值，因为选卡与奖励集合由角色、已解锁内容和后续随机抽取形成，且每种遗物开出的提示不同；需对给定元素实际展开分支才能得到这个数。[后述遗物源码](#候选遗物的具体效果)。

三个选项的遗物模型各不相同：正面池不含诅咒池的遗物，正面候选经洗牌后取前两个；按下选项时 `RelicOption` 调用 `RelicCmd.Obtain`，而它先把该遗物加入玩家遗物列表，再执行其 `AfterObtained`。因此三个成功记录至少在**持有的涅奥遗物及其持续语义**上不同。[Neow.cs:66–106,275–278](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Events/Neow.cs#L66-L106)、[AncientEventModel.cs:268–287](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/AncientEventModel.cs#L268-L287)、[RelicCmd.cs:35–54](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Commands/RelicCmd.cs#L35-L54)。当前 run-mode 首战 observation 的 `inventory.relics` 逐件记录模型 ID、可显示的计数与原生状态。[observation 构造](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L1284-L1286)。

**“3 个不同运行状态”不能写成“3 套不同的首战即时战斗规则”。** 第一层地图节点被强制设为普通怪房；`BoomingConch` 只在精英房首回合生效，`FishingRod` 要等每三次普通战斗结束才升级牌，`WingedBoots` 影响地图自由移动。这些持有物在第一场普通怪战斗开始时可只体现为不同的遗物身份，不必改变这场战斗内的抽牌、能量、敌人或行动规则。[StandardActMap.cs:271–275](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Map/StandardActMap.cs#L271-L275)、[BoomingConch.cs:27–55](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/BoomingConch.cs#L27-L55)、[FishingRod.cs:42–59](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/FishingRod.cs#L42-L59)、[WingedBoots.cs:47–92](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/WingedBoots.cs#L47-L92)。

## 候选池及排除条件

源码定义 14 个常驻正面候选，另有三组二选一的附加正面候选：`LavaRock`/`SmallCapsule`、`NutritiousOyster`/`StoneHumidifier`、`NeowsTalisman`/`Pomander`；诅咒池有 8 个候选。`MassiveScroll` 仅多人可用，在当前单人生成路径会被 `IsAllowedAtNeow` 过滤；`WingedBoots`、`SilverCrucible` 仅单人可用。[Neow.cs:66–106,215–278](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Events/Neow.cs#L66-L106)、[RelicModel.cs:439–446](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/RelicModel.cs#L439-L446)、[MassiveScroll.cs:19–22](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/MassiveScroll.cs#L19-L22)、[WingedBoots.cs:47–50](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/WingedBoots.cs#L47-L50)、[SilverCrucible.cs:81–84](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/SilverCrucible.cs#L81-L84)。

抽到特定诅咒候选会排除一项正面候选：`CursedPearl` 排除 `GoldenPearl`，`HeftyTablet` 排除 `ArcaneScroll`，`LeafyPoultice` 排除 `NewLeaf`，`PrecariousShears` 排除 `PreciseScissors`；`LargeCapsule` 使 `LavaRock`/`SmallCapsule` 那一组不加入正面池。`Kaleidoscope` 还要求所有角色卡池均已解锁，`ScrollBoxes` 要求当前角色有至少 4 张已解锁普通牌和 2 张已解锁罕见牌。[Neow.cs:225–274](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Events/Neow.cs#L225-L274)、[Kaleidoscope.cs:24–31](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/Kaleidoscope.cs#L24-L31)、[ScrollBoxes.cs:23–60](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/ScrollBoxes.cs#L23-L60)。有 modifier 时，`Neow` 改走 modifier 自己生成的选项流程，上述“三选一”数量不适用；当前生成器请求角色起始套装，原生 `CreateForTest` 收到空 modifier 列表。[Neow.cs:215–294](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Events/Neow.cs#L215-L294)、[生成器重置请求](../../python/sts2_native_sim/_scenario_driver.py#L493-L520)、[原生运行构建](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L899-L915)。

## 候选遗物的具体效果

表中“取得时”指涅奥选项的 `RelicCmd.Obtain` 路径，表中数字均为源码默认 `CanonicalVars` 的基值。由于 `RelicCmd.Obtain` 等待 `AfterObtained`，嵌套提示会在离开涅奥前解决。[RelicCmd.cs:35–54](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Commands/RelicCmd.cs#L35-L54)。

| 正面候选 | 源码语义 |
| --- | --- |
| `ArcaneScroll` | 取得时生成 1 张本角色稀有牌并直接加入牌组。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/ArcaneScroll.cs#L17-L28) |
| `BoomingConch` | 精英房首回合额外抽 2 张牌并获得 1 点能量；普通怪首战不触发。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/BoomingConch.cs#L21-L55) |
| `FishingRod` | 每结束 3 场普通怪战斗，随机升级牌组中一张可升级牌。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/FishingRod.cs#L40-L59) |
| `GoldenPearl` | 取得时增加 150 金币。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/GoldenPearl.cs#L13-L20) |
| `Kaleidoscope` | 取得时提供 2 组卡牌奖励；每组从 3 个不同的其他已解锁角色卡池各生成 1 张牌供选择。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/Kaleidoscope.cs#L33-L50) |
| `LeadPaperweight` | 取得时展示 2 张无色牌，可选 1 张加入牌组，也可跳过。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/LeadPaperweight.cs#L19-L35) |
| `LostCoffer` | 取得时提供一组含本角色 3 选 1 卡牌奖励与 1 个药水奖励的自定义奖励。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/LostCoffer.cs#L16-L23) |
| `MassiveScroll` | 只允许多人运行；展示 3 张多人专用牌，可选 1 张入牌组或跳过，当前单人生成器不会抽到。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/MassiveScroll.cs#L19-L44) |
| `NeowsTorment` | 取得时往牌组加 1 张 `NeowsFury`；它是 1 费、初始造成 10 伤害并可从弃牌堆取至多 2 张牌回手的消耗攻击牌。[遗物](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/NeowsTorment.cs#L17-L23)、[卡牌](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Cards/NeowsFury.cs#L17-L40) |
| `NewLeaf` | 取得时选择牌组中 1 张牌，随机转化。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/NewLeaf.cs#L18-L28) |
| `PhialHolster` | 取得时药水槽上限 +1，并随机生成 2 个药水，逐个尝试放入药水槽。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/PhialHolster.cs#L20-L33) |
| `PreciseScissors` | 取得时选择并移除牌组中 1 张牌。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/PreciseScissors.cs#L16-L23) |
| `ScrollBoxes` | 取得时生成两组 3 张卡，选择一组全部加入牌组；通常每组是 2 普通 + 1 罕见，故障机器人每组另有 1% 概率变成 3 张 `Claw`。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/ScrollBoxes.cs#L32-L44)、[生成规则](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/ScrollBoxes.cs#L62-L103) |
| `WingedBoots` | 单人运行中提供 3 次地图自由移动；走非正常子节点时消耗次数，普通第一战的战斗内无触发。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/WingedBoots.cs#L22-L92) |
| `LavaRock` | 第一幕 Boss 奖励额外添加 2 个遗物奖励，触发一次后失效。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/LavaRock.cs#L36-L64) |
| `SmallCapsule` | 取得时打开含 1 个随机遗物奖励的界面。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/SmallCapsule.cs#L13-L19) |
| `NutritiousOyster` | 取得时最大生命 +11。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/NutritiousOyster.cs#L15-L20) |
| `StoneHumidifier` | 每次营地治疗后，最大生命 +5。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/StoneHumidifier.cs#L16-L25) |
| `NeowsTalisman` | 取得时升级牌组中**最后一张**基础 `Strike` 与**最后一张**基础 `Defend`，如存在。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/NeowsTalisman.cs#L16-L31) |
| `Pomander` | 取得时从牌组选择 1 张可升级牌升级。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/Pomander.cs#L15-L24) |

| 诅咒候选 | 源码语义 |
| --- | --- |
| `CursedPearl` | 取得时向牌组加入 `Greed` 诅咒，并增加 333 金币。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/CursedPearl.cs#L17-L23) |
| `HeftyTablet` | 取得时展示 3 张本角色稀有牌，可选 1 张或跳过；无论是否选牌，向牌组加入 1 张 `Injury`。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/HeftyTablet.cs#L23-L38) |
| `LargeCapsule` | 取得时从遗物池前端连续取得 2 件遗物，并向牌组各加 1 张本角色基础 `Strike`、`Defend`。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/LargeCapsule.cs#L21-L35) |
| `LeafyPoultice` | 取得时最大生命 -12，然后随机转化牌组中第一张基础 `Strike` 和第一张基础 `Defend`。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/LeafyPoultice.cs#L17-L37) |
| `NeowsBones` | 取得时从涅奥可用的其他遗物洗牌取前 2 个作为奖励，之后随机向牌组加入 1 张可由 modifier 生成的诅咒牌；奖励可能再触发其他遗物取得效果。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/NeowsBones.cs#L25-L57) |
| `PrecariousShears` | 取得时选择并移除牌组中 2 张牌，然后受到 16 点无强化来源伤害。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/PrecariousShears.cs#L18-L31) |
| `SilkenTress` | 取得时失去全部金币；首次卡牌奖励生成时给可附魔的候选附加 `Glam`，处理该次奖励后即失效。[源码](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/SilkenTress.cs#L42-L82) |
| `SilverCrucible` | 单人运行中，前 3 次卡牌奖励的可升级候选变成升级版；进入宝箱房会计数，仅当宝箱房已进入超过 1 次时允许生成宝物。[使用次数](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/SilverCrucible.cs#L46-L48)、[卡牌奖励与宝箱](../../../sts2-src/decompiled/MegaCrit/sts2/Core/Models/Relics/SilverCrucible.cs#L94-L147) |
