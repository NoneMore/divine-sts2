# 模拟器与实机游戏的一致性，目前是怎么验证的

**仓库修订：** `git rev-parse HEAD` = `13412dcb0a0e9faa37a9b47e678bb06bf39ff6cd`
（`fix(native-sim): a run reset builds no combat the run never plays`，2026-09-17）
**工作树：** `git status --porcelain` 为空（干净）。
**写作约束：** 按 ADR-0004（`docs/adr/0004-public-tree-gate-scope.md:3`），本文档只用相对路径描述机器相关位置。

> 本仓库没有 `research*.md` / `findings*.md` 约定（glob 无命中）；`docs/` 下只有 `architecture-review.md` 与 `adr/`。因此按任务指定新建 `docs/research/`。

---

## 1. 一句话结论

本仓库里没有"重写的模拟器"：**native sim 就是把实装的 `sts2.dll` 装进 Godot headless 进程、用反射加 Harmony 无头化后驱动**（`src/Sts2.NativeSim.GodotHost/Main.cs:19-24,43-46`；`src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs:92-93,394-397`），所以这里的"一致性"实际上是**同一条游戏二进制被两条驱动路径观察时结果是否相同**，而不是"独立实现 vs 原版"的等价性。目前唯一**跑通并留下记录**的、真正跨这两侧做比对的自动化检查是字段级 parity oracle（`tests/acceptance/parity_run_acceptance.py`），它在一次运行中把 14 个生成场景与真机客户端的战斗初始状态逐字段对齐，结论 14/14 一致、0 个比对哈希、2/2 个 Act-variant 探针（`artifacts/parity-run/parity-run.json`，2026-09-17，build `0.1.0+5926027…`）。这条 oracle **不在 CI 里**，覆盖范围只到"第一幕第一个战斗"及其 run/creature/pile/inventory 字段；另一条设计好的跨侧通道（真机导出 trace → 无头 worker 精确重放）**在本机没有任何产物，从未被认证过**。

---

## 2. 一致性在这里指什么

### 2.1 需求本身

- `docs/adr/0003-generated-scenarios-are-reproducible-in-the-shipped-game.md:3`：
  > "Every scenario this project generates … must be exactly what a fully unlocked Slay the Spire 2 client produces for the same run seed, so that any generated scenario can be replayed by hand in the shipped game; … **acceptance must compare against the shipped game**"，
  并且明确否决了"仅凭模拟器自洽（simulator-only self-consistency）"作为验收。
- 词汇边界（`CONTEXT.md`）：**shipped game** `:15-17`、**full-app sandbox** `:11-13`、**generated scenario** `:51-53`、**combat initial state** `:43-45`、**Act variant** `:47-49`、**card-select prompt** `:35-37` 与 **option pick** `:39-41`（后者"a bridged run reports no stage of its own for it yet"——这条区分正是后面"未验证"的直接来源）。
- 支撑前提：ADR-0001（`docs/adr/0001-…md:3`，完全解锁；`:9-11` "Act variants are rolled from the run seed … discovery state is pinned off"）、ADR-0002（`docs/adr/0002-…md:3`，net9.0 以便加载桥接 mod）。

### 2.2 被比较的契约

契约是显式声明的 50 个字段路径，单一来源在 `python/sts2_native_sim/parity_projection.py:155-206`（`CONTRACT_FIELDS`）：
`$.game_build.*`（3）、`$.run.*`（8：seed/ascension/gold/act_variant/act_index/act_floor/total_floor/rng_counters）、`$.combat.*`（7）、`$.creatures[]`（含 next_move/intents/powers 的子字段）、`$.piles[]`（五堆的有序 cards 及每张卡属性）、`$.inventory.relics[]/potions[]`。
三处**显式排除**及其理由在 `parity_projection.py:119-146`：卡牌 `instance_id`（编码器各自铸造）、意图的实现类名、以及**任何一方的 `state_hash`**（"incomparable by construction … a hash match would prove nothing"）。可空字段单列于 `:212-221`。

### 2.3 两条侧别到底是什么（关键区分）

| 侧 | 实际产物 | 入口证据 |
|---|---|---|
| "模拟器"侧 | Godot headless 进程 + 反射/Harmony 驱动的**同一份 `sts2.dll`**（**不是** .NET 重写实现） | `python/sts2_native_sim/client.py:91`（`--headless --path <GodotHost> -- --server <sts2.dll>`）、`Main.cs:26,30-35,45-49` |
| "实机游戏"侧 | 真实安装的 `SlayTheSpire2.exe`（`--headless --force-steam=off`）+ in-process 桥接 mod DLL | `python/sts2_native_sim/full_app_client.py:172-202`、`:17-27`（`src/Sts2.NativeSim.FullAppBridge/bin/Release/net9.0/package/sts2-full-app-bridge.dll`） |
| 第三类通道 | 真机内跑的 Harmony 导出 mod 产出 JSONL trace，再在无头 worker 上重放 | `src/Sts2.NativeSim.TraceExporter/TraceExporterMod.cs:21-37`、`python/tools/differential_replay.py:93-110` |

桥接 mod 与导出 mod 直接引用实装程序集（`src/Sts2.NativeSim.FullAppBridge/Sts2.NativeSim.FullAppBridge.csproj`：`RequiresGameData` + `sts2.dll`/`0Harmony.dll`/`GodotSharp.dll` 的 `HintPath="$(GameDataDir)\…"`，路径来自 `STS2_GAME_ROOT`，见 `Directory.Build.props:9-18`）。因此**"game 侧"的取值来自游戏运行时对象，但"读的是哪个访问器/字段"是仓库自己写的 mod 决定的**——这一半是被假定的，后文 §5 给出三个"看起来有、实际读错"的实测例子。

---

## 3. 现有的验证机制

### 3.1 字段级 parity oracle（唯一真正的 simulator↔shipped 自动比对）

- **入口**：`tests/acceptance/parity_run_acceptance.py`；`report()` `:571-623`，`main()` `:626-690`，固定样本 `SAMPLE` `:187-202`（14 个场景 / 10 条不同 run / IRONCLAD+DEFECT / A0+A2），变体探针 `VARIANT_PROBES` `:210-213`（2 个）。
- **记录侧**：`generate_rows` 在 native worker 上生成（`_records` `:221-243` → `python/sts2_native_sim/scenarios.py:571-589`），失败元素以 failure row 形式报出（`:246-260`）。
- **真机侧**：`FullAppBridgeClient.launch()`（`:496`、`:517`）→ 启动真 `SlayTheSpire2.exe`，用记录的 seed/角色/Ascension 从 `start_run` 驱动，经 Ancient 房、按 `choose_event:{option_index}` 取记录的选项（`:345-351`）、按记录的"首个合法动作"规则回答卡选择提示（`:263-311`），走到记录的 row-1 节点后停在战斗（`:314-373`，`MAX_STEPS=40`）。
- **比对**：`compare_contract`（`parity_projection.py:329-357`）把两侧投影成同一形状后用仓库既有的逐路径比较器 `parity.compare_snapshots`（`python/sts2_native_sim/parity.py:33-64`），阶段词经 `decision_vocabulary` 归一（`parity_projection.py:377-413`），act index 基准只声明一次（`:58-62,436-447`）。
- **调用方式**：手工。`python tests/acceptance/parity_run_acceptance.py --report … [--workers N] [--limit N] [--only LABEL] [--dump DIR] [--no-probes]`（`:626-642`）。需要配置 `STS2_GAME_ROOT`，且沙盒必须落在游戏安装所在卷（`:59-61`）。
- **是否在 CI**：**否**。`.github/workflows/ci.yml:22-35` 只做 `pip install -e ".[dev]"`、`compileall`、`pytest -q`、两个 game-independent 的 C# 工程构建、`scripts/test-public-tree.ps1`。整个仓库没有任何 workflow 或脚本调用 `parity_run_acceptance.py`（grep 全仓仅命中 `tests/test_parity_projection.py:18` 的 `from parity_run_acceptance import report`，那只是在无样本的情况下取报告文档，不驱动游戏）。
- **是否有调用者**：CI 内只有 `report`（离线）；**真正运行 oracle 的调用者不存在**（无脚本、无 README 命令）。
- **通过证据**：见 §4.1。

### 3.2 桥接/全客户端自身的确定性（game ↔ game，不是 sim ↔ game）

`tests/acceptance/full_app_bridge_acceptance.py:48-119`：4 个独立的真 `SlayTheSpire2.exe` 进程，相同 seed/角色/动作序列，要求 `len(set(initial_hashes)) != 1` 即抛错（`:117-119`），并做前缀重放与反事实分支（`:194-213`）。它证明的是"真机 + 桥接可复现、可回放、可分支"，**两侧都是同一个编码器**。运行记录见 `artifacts/bridge-combat-acceptance.log`、`artifacts/bridge-run-inventory-acceptance.txt`（§4）。不在 CI（需要游戏安装）。

### 3.3 真机 trace → 无头 worker 精确重放（第二套跨侧通道；已建成，无产物）

- `scripts/run-isolated-autotrace.ps1:99-102` 在硬链接沙盒里启动真 `SlayTheSpire2.exe`，带 `--native-sim-trace --native-sim-autotrace-driver --native-sim-autotrace-policy=…`；`:127` trace 目录 = 沙盒 APPDATA 下的 `native_sim_traces`；`:152` 对每条 trace 执行 `python differential_replay.py --require-exact`；`:29-31,175-188` 通过者复制进 `artifacts/shipped-autotraces/certified`。
- 重放器：`python/tools/differential_replay.py:93-110`（在 `NativeWorker` 上 `reset`+逐 checkpoint `step`，用 `first_difference` 精确比对 observation；`:29,51` 是它**自带的**比较器），并先比对 game build（`:102-105`）。
- **精确否定**：本机不存在 `native_sim_traces` 目录、不存在 `artifacts/shipped-autotraces/{candidates,certified,failures}`、不存在任何 `native-sim-autotrace-run.json`（对仓库、用户 APPDATA、LOCALAPPDATA、TEMP 的有界搜索均无命中）。即**该通道从未在本 checkout 留下任何成功或失败的认证产物**。
- 唯一跑过的相关验证是 `tests/acceptance/differential_harness_acceptance.py`，而它在第一行就自我否定：
  `:1` "Self-test for trace parsing/comparison; **this does not count as differential coverage**"，且喂进去的是模拟器自产 trace（`:23` `"source": "simulator_self_test"`）。它证明的是"比较器能发现被篡改的字段"（`:36-39`），不是跨实现一致性。
- 该通道的辅助工具：`python/tools/differential_campaign.py:14`、`python/tools/promote_differential_candidates.py:13,27`、`python/tools/trace_inventory.py:1-6`（"read-only inventory, not replay validation"）。三者都只有 `differential_replay` 这一个真实依赖，且没有 trace 可以处理。

### 3.4 由 seed 独立推导的"预言机"（sim ↔ 反编译移植 ↔ sim）

- `python/sts2_native_sim/shipped_rng.py:1-12` 明说是反编译件的直接移植：`StringHelper.GetDeterministicHashCode`、`MegaRandom`（splitmix64+xoshiro256\*\*）、`Rng` 的抽取面。
- 调用者只有两个 acceptance：`tests/acceptance/act_variant_acceptance.py:32`（对比 seed→Act variant）与 `tests/acceptance/ancient_room_acceptance.py:52`（对比 seed→Ancient 报价与 SlimesWeak 组成）。
- 两个脚本都**只驱动 NativeWorker**（`act_variant_acceptance.py:31`；`ancient_room_acceptance.py:50`），不与真机对话；`ancient_room_acceptance.py:29-33` 自己声明：
  > "It is **not** the shipped-game parity comparison: that compares whole states field by field against a real client … What this script covers is the simulator's side of the claim, plus the independent ports…"
- 所以这里的"游戏侧"是**反编译源码的移植**，属于假定而非观测（`.scratch/neow-options/neow-options.md:5`："this is unverified at runtime"；`:68`："That is static reasoning only; it has not been observed"）。

### 3.5 观察形状与 schema 的离线锚定（不是 parity）

- 在线记录 + 校验：`tests/acceptance/observation_schema_acceptance.py:1-21`（驱动 worker 走遍每个 run stage，验证 `schemas/canonical-state.schema.json`；`--record` 写出 `tests/fixtures/canonical-observations.json`）。
- 离线（CI 内）：`tests/test_observation_schema.py:58`（校验已入库的真实 capture 夹具）、`tests/test_scenarios.py:571,677,1322,1405`（行/schema/字节同一性）、`tests/test_bridge_observation_shape.py:29-31,41-50`（**用正则读 FullAppBridge/PNC 的 C# 源码**做静态断言）、`tests/test_decision_vocabulary.py:33-60`（同样读 C# 源码收集阶段词）。
- 这些都**不驱动游戏**，因此证明的是"形状/词汇/序列化一致"，不是"值与实机一致"。它们把桥接观察与"模拟器自己的投影"对齐（`tests/test_bridge_observation_shape.py:1-7`），后者本身是同一仓库的产物。

### 3.6 模拟器内部确定性（(b) 类，明确区别于跨实现一致性）

- `scripts/test-godot-determinism.ps1:47-55`：跑两次 `NativeFeasibilityProbe`（不带 `--server` 的 GodotHost 分支，`Main.cs:50-56`），比对 `assembly_sha` 与三个 `state_hash`、legal action 列表。
- `tests/test_scenarios.py:1322`（同请求两次字节同一）、`:1405`（不同完成顺序仍字节同一）。
- 记录在案的字节同一：`artifacts/scenario-corpus-ticket10` 与 `artifacts/scenario-corpus-ticket10-repeat`（2026-09-16 23:14:50 / 23:14:55）四个文件 SHA-256 全同（例如 `worker-00.jsonl.gz` = `184FCD0146786CC1DBE2DCBF…`）。
- 这些全部属于"同种子→同结果 / 语料字节一致"，**不能**用来支持 `docs/architecture-review.md` 意义上的 parity。

### 3.7 架构评审第 10 节的断言核对（逐条）

| `docs/architecture-review.md` 的断言 | 当前 commit 的判定 |
|---|---|
| `:630` "**`parity.py` has no callers.** `compare_snapshots` … unreferenced" | **已被推翻**。`parity_projection.py:56` 导入并在 `:344` 调用它；`tests/test_parity_projection.py:288` 断言 `projection.compare_snapshots is parity.compare_snapshots`；`parity.py:36-41` 的 docstring 已改写为"两个调用者"。引入者是 `2e6877a`（ticket 15）。 |
| `:630` `build_trust_matrix` … unreferenced | **仍成立**。grep 全仓只有定义处 `parity.py:67` 与被评审文档自身引用（`docs/architecture-review.md:630`）——无任何调用者。 |
| `:630` "`differential_replay.py:29,51` rolls its own `first_difference` / `first_subset_difference` for the same job" | **仍成立**。两个函数仍在 `differential_replay.py:29`、`:51`，且 `:99` 用它做 exact/subset 比较。 |
| `:628` "CI sees three files … The 22 acceptance files are never collected" | **方向仍成立**（acceptance 脚本都不在 CI）。当前 `tests/` 有 11 个 `test_*.py`、173 个 `def test_*` 函数，全部离线可跑（`tests/conftest.py:11-20` 用假安装目录）。 |

---

## 4. 记录在案的证据

### 4.1 parity oracle 的通过报告（唯一 (a) 类证据）

`artifacts/parity-run/parity-run.json`（47 395 B，mtime **2026-09-17 23:32:17**，被 `.gitignore:26 artifacts/` 忽略，故未入库）：

- `success: true`；`matched: 14`，`mismatched: 0`；14 个样本每个 `mismatched_fields: 0`、`difference: null`、`differing_paths: []`；逐样本 `compared_fields` 为 134–172 个叶子路径。
- `game_build` = version `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314`，assembly `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`，pck `42520EB8…`。
- `contract.state_hashes_compared: 0`（按设计不比哈希）。
- `act_variant_bound`：对比样本 variant = `UNDERDOCKS`，`forced_variant` = `UNDERDOCKS`，`probes_measured` = 2。
- `nested_choice_kinds`：`declared: ["card_choice"]`、`measured: ["card_choice"]`、`agrees: true`；明确列出未覆盖的 `option_choice` 与 `custom_reward_choice` 及理由。
- `contract.fields_declared_not_exercised` = `$.inventory.potions[].model_id`、`$.inventory.potions[].slot`、`$.piles[].cards[].enchantment.amount`、`$.piles[].cards[].enchantment.model_id`（**这 4 个字段声明了但没被读到**）。
- 报告内部**没有**时间戳字段、也没有 repo commit，只有上述 game build 指纹；定年依据是文件 mtime。

过程证据（同一目录）：

- `artifacts/parity-run/dump/`（2026-09-17 22:47–22:51，14 个样本 × 4 个文件：record/bridge 观察 + 两侧投影）= **红灯那次运行**的产物（`parity_run_acceptance.py:504-505` 只在 `not matched` 时 dump）；绿灯那次没有写入。
- `artifacts/parity-run/smoke-3.json`（21:58:41）：`success: false`、`matched: 0`、`mismatched: 3`、每样本仅等比 45 个字段——早期小样本的红灯。
- `artifacts/parity-run/seed-probe.json`（21:50:15）：只有 `game_build` 与 `runs` 两个键，是探针阶段产物。

### 4.2 ticket 层面的红→绿叙述

- `.scratch/act1-combat1-scenarios/issues/15-field-by-field-parity-run.md:21-27`（2026-09-17）："14 of 14 drove to their fights and **0 of 14 matched** … the feature stays unaccepted until 16 lands"；`:43-52` 给出差异细节（每样本 15–37 条叶子路径，全部含 `$.run.rng_counters.Niche` 高一次，以及其后的敌人 HP 与有序手牌/牌堆）；`:59-68` 定位到 `PersistentNativeCombatEnvironment.Reset` "builds a combat unconditionally … (`:455-466`)"。
  该 ticket 引用的 `:455-466` 是**修复前**的行号；在 HEAD 上该缺陷的修复形态是 mode 分流：`PersistentNativeCombatEnvironment.cs:173`（`ResetState(Declaring(request, ResetModes.Combat))`）、`:186`（`Declaring`）、`:203`（`ResetState`）、`:231`（run 模式：`ResetState(Declaring(request, ResetModes.Run))`），而两处真正花随机数的调用现在只在战斗模式下到达——`:523`（`GenerateMonstersWithSlots`）、`:533`（`PopulateCombatState(…, Shuffle)`），`:504-505` 的注释正是对这次修复的说明。
- 同文件 `:116-121`（同日稍后）："**the gate is green now.** … 14 of 14 samples matched field for field and 2 of 2 probes measured the bound … so the feature this ticket gates is accepted"。
- `.scratch/act1-combat1-scenarios/issues/16-run-mode-reset-builds-a-combat.md:82-94` 复述绿灯并自曝时序缺口：
  > "That run precedes the request-field redesign in the first bullet, which leaves a *declared* run reset exactly as it was … and the run-mode state the final build stands up is re-evidenced there by the acceptances that drive it"。
  也就是说：**最终的 `reset_mode` 请求字段重构之后，没有重跑过 parity oracle**。
- 同文件 `:113-119`：`"A combat-mode reset is unchanged" is a hash comparison now, not an argument`（重构前后 `reset`/`map_reset`/`reward_reset`/… 的 state hash 相同，`34409767…` / `5807B698…`）。
- `.scratch/act1-combat1-scenarios/parity-findings.md`（mtime 2026-09-17 23:39:29）是对外的证据文档：`:7` 说明来源分层（反编译静态阅读 + 运行时观测）；`:219`/`:236` 记红灯；`:299`/`:317-320` 记绿灯；`:345-374` 记桥接编码器在被修前的约三打字段缺失/错误；`:376-397` "Still open"。

### 4.3 `.scratch/*-acceptance.log`（15 个）实际证明了什么

全部是 **2026-09-16 00:29–00:32** 的 **native-simulator** 运行（每份第 1 行都是 `[sts2_native_sim] The user profile is not writable; …`），并且被 `.gitignore:46 *.log` 忽略：

| 文件 | 实际证明 |
|---|---|
| `ancient_room_acceptance.log` | (b)+(d)：`success: true`，内嵌与 §4.1 相同的 game_build（`:4-9`），15 个样本、`total_floor_at_first_fight` 全为 2、`repeat_combat_hash` 跨 worker 相同——**模拟器侧**值 + 内部确定性 |
| `act_variant_acceptance.log` | 同上：8 seed → 4 `OVERGROWTH` / 4 `UNDERDOCKS` + game_build；"与独立移植的 shipped roll 一致"这一句**只在脚本与 ticket 里**（`issues/02-…md:53-56`），日志本身没有对照物 |
| `run_custom_reward_acceptance.log` | **唯一失败**：`Traceback … NativeSimError: unknown_state_handle`（模拟器 restore 缺陷，非 parity 不符） |
| 其余 12 个（rest/reward/item_reward/option_reward/event/event_combat/room_entry/room_cycle/composed_utility_rooms/map/portable_modes/choice） | 全部 (b)+(d)：模拟器内部哈希、房间/奖励/地图步骤与耗时 |

**精确否定**：没有任何 `.scratch` 日志比对过"模拟器字段 vs 实机字段"，没有任何 `.scratch` 日志记录过桥接观察，也没有任何日志含 `"success": false`。且这些日志全部早于最终的桥接形状（tickets 12/13）与 ticket 16 修复，因此**不能**为绿灯 parity 运行作证。

### 4.4 其它入库/本地产物

- `artifacts/bridge-combat-acceptance.log` / `-repeat.log`（2026-09-16 23:53/23:54）：真机运行，seed `A1B2C3D4E5`，哈希 `DC382F57…`/`3AB58111…`（与 `issues/11-…md:62-78` 引用一致），但形状仍是 ticket-11 期（`hand[].index/cost/card_id`、`draw_pile_count`）。
- `artifacts/bridge-run-inventory-acceptance.txt`（2026-09-17 20:16:39）：真机、最终形状的单 seed 观察（`piles`、`run_at_the_ancient`/`run_at_the_first_fight`、`inventory_at_the_first_fight`、`game_build`、`state_hash_at_the_first_fight` = `8C6638C1…`、`state_hash_at_powers` = `37F1CB88…`，与 `issues/13-…md:95-96` 一致；counters 在 Ancient 为 `Niche` 0/`Shuffle` 0、到战斗为 1/9）。**它是"真机侧观察"的最强记录，但从未与任何生成记录做字段级比对。**
- `artifacts/scenario-corpus-ticket10` vs `-repeat`（2026-09-16 23:14）：字节同一（(b) 类）。
- `tests/fixtures/canonical-observations.json`（**已入库**）：由 `observation_schema_acceptance.py --record` 从"实机装配的 native worker"录制的 capture，被 CI 内 3 个离线测试读取——它是"实机来源的形状"，被用于投影与词汇锚定，而不是 parity 结论。

---

## 5. 已确认 vs 假设 vs 未验证

### 5.1 已确认（有调用者 + 有记录）

1. **字段级 parity oracle 在 build `0.1.0+5926027…` 上通过**：14/14 样本逐字段一致，`state_hashes_compared: 0`，2/2 变体探针（`artifacts/parity-run/parity-run.json`；`issues/15-…md:116-121`；`issues/16-…md:82-94`）。
2. **该 oracle 具备区分力，不是橡皮图章**：它测出并定位了一处真实分歧（run-mode reset 无条件构建战斗，多花 1 次 `Niche` 抽签与 1 次洗牌），修复后转绿（`issues/15-…md:43-68`、`issues/16-…md:1-17,42-65`）。
3. **`compare_snapshots` 已有真实调用者**（`parity_projection.py:56,344`；`tests/test_parity_projection.py:288` 断言函数对象同一）——`docs/architecture-review.md:630` 的这一半在当前 commit 不成立。
4. **契约字段清单是单一来源并有离线锚定**（`parity_projection.py:155-206` ↔ `tests/test_parity_projection.py:120-135,300-313`），且在 CI 中执行（`.github/workflows/ci.yml:26-27`）。
5. **模拟器内部确定性与语料字节同一**（`tests/test_scenarios.py:1322,1405`；`artifacts/scenario-corpus-ticket10` vs `-repeat`）。
6. **桥接 4 进程哈希一致 + 前缀回放/分支可用**（`full_app_bridge_acceptance.py:117-119,194-213`）——属 game↔game。
7. **ADR-0001 的完全解锁前提在桥接侧可观测**：`tests/acceptance/full_app_unlock_acceptance.py:16-32` 断言 `hello`/`start_run`/`history` 都报 `unlock_policy == "all"`，并确认角色/Ascension 被采用。

### 5.2 假设（无自动强制，或只由反编译源码/文档支撑）

1. **ADR-0003 的"可在 shipped game 中手工复现"没有自动化强制**。最接近的是 `tests/acceptance/scenario_record_acceptance.py` 的"仅用记录字段重驱动 → 同一 state hash"，而它的 docstring 自称是 "**the simulator-side half** of 'paste the seed into the shipped game's custom run screen and the same fight is there'"（`:22-27`）。仓库里找不到任何对手工复现的机器检查。
2. **Act variant 的 shipped 侧被 ADR-0001 故意偏移**：因为 bridge 沙盒是全新 profile，实机强制非默认变体，于是 oracle 的对比样本被限定为 `UNDERDOCKS`（`parity_run_acceptance.py:40-49,175-186`；`parity-findings.md:270-279`：默认变体那一半"unreachable here"）。
3. **`act_variant_acceptance` / `ancient_room_acceptance` 的"游戏侧"是反编译移植**（`shipped_rng.py:1-12` 自述），不是运行时观测。
4. **手牌能量消耗、升级数、遗物计数"存在"分支只有离线/静态锚定**：`parity-findings.md:129-137`；`issues/12-…md:76-84`；`issues/13-…md:129-137,175`。
5. **升级/转化/弃牌三类卡选择提示、以及牌组卡选择屏，是"读自反编译"而非测量**（`parity-findings.md:184-192`；`bridge_card_select_acceptance.py:32-35,44-45`）。
6. **真机侧读数的正确性靠离线静态测试锚定**（`tests/test_bridge_observation_shape.py:29-31,41-50` 用正则读 C# 源），而"读错访问器"在历史上确实发生过：`parity-findings.md:349` 记录三处"看起来有但读错"（act index 一位偏移、恒为 0 的升级字段、手牌 cost 读了另一个 accessor）。
7. **`.scratch/neow-options/neow-options.md:5,68,94-96`** 自述"unverified at runtime" / "static reasoning only"。

### 5.3 未验证 / 缺口（明确的负面清单）

1. **契约声明但通过那次运行从未被 exercise 的 4 个字段**：`$.inventory.potions[].slot`、`$.inventory.potions[].model_id`、`$.piles[].cards[].enchantment.model_id`、`$.piles[].cards[].enchantment.amount`（`parity-run.json` 的 `fields_declared_not_exercised`；`issues/15-…md:50-52,86-87`）。对这些字段而言，"通过"没有任何证据。
2. **嵌套选择覆盖不完整**：`option_choice`（bundle / 遗物选项）在实机里由 autoplay 自身处理、桥接不报告该阶段，`custom_reward_choice`（奖励集）在本样本中未被取用（`parity_run_acceptance.py:106-116`；`parity-findings.md:383-384`）——这是"覆盖缺口"而非"parity 缺口"，但 ADR-0003 要求的完整 Ancient-choice 可复现性尚未成立。
3. **绿灯重跑与最终代码不同步**：绿灯 parity 运行早于最后 `reset_mode` 请求字段重构（`issues/16-…md:90-93` 自述），此后没有 oracle 重跑记录；替代证据是"其它 acceptance 都通过"这一间接论证。
4. **契约本身只覆盖"战斗初始状态"**：奖励、商店、休息、宝箱、事件、act 过渡、地图、终局等**从未**与生成记录做过字段级比对。它们的 `run_*_acceptance.py` 只断言模拟器内部哈希/值（§4.3），既无实机对照也无契约。
5. **trace 差分通道从未产出任何产物**：无 `native_sim_traces`、无 `artifacts/shipped-autotraces`、无 autotrace 沙盒记录（§3.3 的精确否定）。这是"已建成但未使用/未跑通"的接缝。
6. **`parity.build_trust_matrix`（`parity.py:67`）仍无调用者**（grep 只命中定义与评审文档）。
7. **没有任何 C# 测试工程**（架构评审候选 13 该条仍成立）；桥接/导出器的形状完全靠 Python 正则读 C# 源来锚定，重命名私有成员即可静默失效。
8. **`bridge_card_select_acceptance.py`、`bridge_combat_observation_acceptance.py`、`scenario_record_acceptance.py`、ticket 16 之后的若干 acceptance 重跑，都没有留存的输出文件**；`issues/15` 引用的一些哈希只存在于 ticket 正文。
9. **证据可追溯性弱**：`.scratch/*.log` 与 `artifacts/**` 都被 gitignore（`.gitignore:26,46`），不随修订入库；`parity-run.json` 内部无 timestamp/commit。因此"某次运行通过"只能靠 mtime + game build 指纹归属。
10. **文档陈旧/自相矛盾**：`issues/11-bridge-combat-block.md:7` 状态仍是 `ready-for-agent`（但 checklist 全 `[x]`、`：21` 已写"implemented"）；`spec.md:159` 仍说"no field-by-field comparison has run yet"（已被 `parity-findings.md:219,299` 推翻）；`parity-findings.md:7` 说 "51 contract fields per scenario" 而同文件 `:283` 与代码都说 50（`CONTRACT_FIELDS` 长度 50，逐样本 `compared_fields` 是 134–172 个叶子）。**已在后续修复：** 本条记录的三处矛盾与 `spec.md:3` 的 "draft" 状态、以及 `issue-tracker.md:11` 引用而不存在的 `triage-labels.md`，均已于 2026-09-25 修复（`issues/11` → `Status: done`；`spec.md` 顶部改为 implemented、末尾 "Evidence and its limits" 改写；`parity-findings.md:7` 改为 50 条声明字段路径，与 `CONTRACT_FIELDS` 实测长度 50 一致；新建 `docs/agents/triage-labels.md`）。

---

## 6. 主要来源索引（HEAD = `13412dcb0a0e9faa37a9b47e678bb06bf39ff6cd`）

**需求与词汇**
- `docs/adr/0003-generated-scenarios-are-reproducible-in-the-shipped-game.md:3`
- `docs/adr/0001-fully-unlocked-runs-are-the-simulator-baseline.md:3,9-11`
- `docs/adr/0002-target-net-9-for-game-host-compatibility.md:3`；`docs/adr/0004-public-tree-gate-scope.md:3`
- `CONTEXT.md:11-13,15-17,35-41,43-49,51-53`
- `.scratch/act1-combat1-scenarios/spec.md:50-75,119-121,123-136,138-159`
- `docs/architecture-review.md:609-657`（尤其 `:630`）

**契约与比较**
- `python/sts2_native_sim/parity_projection.py:56,58-62,119-146,155-206,212-221,270-289,329-357,377-413,436-447`
- `python/sts2_native_sim/parity.py:33-64,67-95`
- `python/sts2_native_sim/decision_vocabulary.py`（经 `parity_projection.py:55,389-412` 被读）
- `tests/test_parity_projection.py:18-25,120-135,146,279-313`

**oracle 与驱动**
- `tests/acceptance/parity_run_acceptance.py:2-62,93-121,175-213,221-260,263-373,376-432,455-506,525-568,571-623,626-690`
- `python/sts2_native_sim/scenarios.py:1-8,414-423,571-589,706-799,872-895`
- `python/sts2_native_sim/client.py:33,91,105,127-134,178-220`
- `python/sts2_native_sim/full_app_client.py:17-27,73-86,101-170,172-202,243-284`
- `python/sts2_native_sim/full_app_sandbox.py`（硬链接沙盒；经 `full_app_client.py:108` 调用；离线锚定 `tests/test_sandbox.py:13,26`）
- `python/sts2_native_sim/paths.py`（`find_game_root`/`find_sandbox_root`；经 `full_app_client.py:14,75,85` 调用）

**真机侧编码器与差分通道**
- `src/Sts2.NativeSim.GodotHost/Main.cs:19-58`
- `src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs:92-93,173,186,203,231,394-397,504-505,523,533,764-812,867-890`
- `src/Sts2.NativeSim.FullAppBridge/Sts2.NativeSim.FullAppBridge.csproj`
- `src/Sts2.NativeSim.TraceExporter/TraceExporterMod.cs:21-37,122-160`
- `src/Sts2.NativeSim.AutoTraceDriver/Sts2.NativeSim.AutoTraceDriver.csproj`
- `scripts/run-isolated-autotrace.ps1:29-31,99-102,126-188`
- `python/tools/differential_replay.py:1-5,29,51,74-110`
- `tests/acceptance/differential_harness_acceptance.py:1,13-41`；`python/tools/differential_campaign.py:14-23`；`python/tools/promote_differential_candidates.py:13,27-30`；`python/tools/trace_inventory.py:1-6`

**由 seed 推导的移植**
- `python/sts2_native_sim/shipped_rng.py:1-12,34-44,51-80`
- `tests/acceptance/act_variant_acceptance.py:1-21,31-38`；`tests/acceptance/ancient_room_acceptance.py:1-39,50-52`

**schema 与离线测试**
- `tests/acceptance/observation_schema_acceptance.py:1-21,40-44`；`python/sts2_native_sim/schema.py:43`
- `tests/conftest.py:11-20`；`tests/test_observation_schema.py:58`；`tests/test_bridge_observation_shape.py:1-7,29-31,41-50`；`tests/test_decision_vocabulary.py:1-9,33-60`；`tests/test_scenarios.py:571,677,1322,1405`
- `.github/workflows/ci.yml:22-35`；`scripts/test-public-tree.ps1:5-30`；`scripts/test-godot-determinism.ps1:47-55`；`pyproject.toml:13-18,27-43`

**运行记录（本地、被 gitignore）**
- `artifacts/parity-run/parity-run.json`（2026-09-17 23:32:17，14/14 通过）
- `artifacts/parity-run/smoke-3.json`（21:58:41，0/3）、`artifacts/parity-run/seed-probe.json`（21:50:15）、`artifacts/parity-run/dump/**`（22:47–22:51）
- `artifacts/bridge-combat-acceptance.log`、`artifacts/bridge-combat-acceptance-repeat.log`（2026-09-16 23:53/23:54）
- `artifacts/bridge-run-inventory-acceptance.txt`（2026-09-17 20:16:39）
- `artifacts/scenario-corpus-ticket10{,-repeat}/**`（2026-09-16 23:14）
- `.scratch/*-acceptance.log`（15 个，2026-09-16 00:29–00:32）

**ticket 与证据文档**
- `.scratch/act1-combat1-scenarios/issues/15-field-by-field-parity-run.md:21-27,43-68,85-94,104-121`
- `.scratch/act1-combat1-scenarios/issues/16-run-mode-reset-builds-a-combat.md:13-17,42-65,66-94,113-129`
- `.scratch/act1-combat1-scenarios/parity-findings.md:5-7,61,129-137,184-192,219-249,270-297,299-343,345-374,376-397`
- `.scratch/act1-combat1-scenarios/issues/11-bridge-combat-block.md:7,21,62-78`；`12-…md:60-84`；`13-…md:75-97,129-137,175`；`14-…md:72-96,116-125`
- `.scratch/neow-options/neow-options.md:5,68,94-96`
- `.gitignore:26,46`
