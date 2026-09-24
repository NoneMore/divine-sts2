# 第一战场景生成器的吞吐诊断

**测量日期：** 2026-09-25，`feat/first-combat-generator`（HEAD `193e51c`）。本文把**实测**与**推断**分开标出：标"实测"的数字来自本次运行，标"推断"的是由实测外推或由源码读出的结论，两者的可信度不同。原始产物在本机 gitignored 的 `artifacts/scenario-performance/` 下。

## 结论

1. **记录中的基线在本机today 精确复现**（热 worker 中位 4.033 s / 2.975 行每秒，记录值 4.049 / 2.963），因此后续比较有可靠基准，不需要重新建立基线。
2. **但那个基线不代表批量成本。** 它的请求只有 4 个 element，被 worker 启动与首次驱动的预热吃掉大部分。实测同一 worker 在 64 个 element 上的稳态成本是 **0.406 s/element**，而 4-element 请求是 **1.008 s/element** —— 差 **2.5 倍**。参考请求 B（512 element / 8 worker）端到端 **41.3 s，即 12.4 element/秒、37.2 行/秒**，是参考请求 A 的 1 worker 行速率的 **20 倍**。
3. **按 spec 的规模，这个生成器已经够快。** spec 的第一刀是"a few thousand records"：3000 行按实测的 37.2 行/秒约 **81 秒**；就是 spec 列为 out of scope 的 10⁵ 行，线性外推约 **45 分钟**。真正的账不是"太慢"，而是**之前的数字测错了对象**。
4. **成本确实集中在 native 侧**：实测单 worker 稳态下 `restore` 占生成时间 **46.9%**、`run_reset` **31.3%**、`run_step` **21.3%**。**Q13 门槛的条件 (i) 与 (iii) 满足；条件 (ii) 悬于一个尚未测量的事实**，见下文"仍然待查的一件事"。
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
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/tools/benchmark_scenario_generation.py diag-20260925-r1 --rounds 3'

# 参考请求 B：一次计时运行
pwsh -NoProfile -Command '. ./scripts/common.ps1; $s = foreach ($n in 1..128) { "--seed"; "$n" }; & ./.venv/Scripts/python.exe -m sts2_native_sim.cli scenario --character IRONCLAD --character DEFECT --ascension 0 --ascension 2 @s --workers 8 --compression 3 --output-dir artifacts/scenario-performance/diag-campaign-a1'

# 单 worker 稳态探针（漂移 + RPC 构成 + PCK 指纹对照）
pwsh -NoProfile -Command '. ./scripts/common.ps1; & ./.venv/Scripts/python.exe python/experiments/scenario_diagnosis_probe.py --elements 64 --seeds-per-chunk 2 --out artifacts/scenario-performance/diag-probe.json'
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

## 成本归因：实测与推断的分界

**实测（单 worker、无争用、份额以生成为分母）：** `restore` 46.9%、`run_reset` 31.3%、`run_step` 21.3%，三者合计 99.5%。

**推断（把份额搬到参考请求 B）：** 启动按 A 的 2.585 s 计，占 B 的 41.26 s 的约 6%；生成因此约占 88–94%。据此 `restore` 约占 B 墙钟的 **41–44%**，`run_reset` 约 **28–29%**，`run_step` 约 **19–20%**。
**这条推断未经测量**：它假定三类 RPC 在 8 路争用下按同一比例变慢。若争用只打在某一类上，份额会移动。**但它有稳健的下界**：生成 ≥88% × `restore` 46.9% > **41%**，这一条不依赖比例假设，只依赖"生成占多数"。

由此，`restore` 与 `run_reset` **各自**都越过 Q13 门槛的 25%。

## Q13 门槛评估

| 条件 | 判定 | 依据 |
| --- | --- | --- |
| (i) 单一原因占批量墙钟 ≥25% | **满足** | `restore` ≥41%（稳健下界），`run_reset` ≈28–29%（推断） |
| (ii) 移除它可信地带来 ≥1.5× | **未决** | 上界：仅去 `restore` 为 1/(1−0.42)=**1.72×**；去 `restore`+`run_reset`（0.42+0.29）为 **3.4×**。但"能否移除"未证 |
| (iii) 过字节同一 + 真机差分双门 | **可满足** | 本次 9 对分片/summary 字节同一；[`scenario_handle_reuse_acceptance.py`](../../tests/acceptance/scenario_handle_reuse_acceptance.py) 是现成的 native 差分 |

**结论：按 Q13 规则，现在不进入实现，先解决决定条件 (ii) 的那一个事实。** 该事实是一个有界的代码问题，不是新特性。

### 仍然待查的一件事

`restore` 昂贵的原因按源码是：run-mode 的分支不持有 combat 快照（[`PersistentNativeCombatEnvironment.cs:3321-3326`](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L3321-L3326)），故 `RestoreAsync` 落入 `ReconstructAsync`（[`:674`](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L674)、[`:794-821`](../../src/Sts2.NativeSim.Core/PersistentNativeCombatEnvironment.cs#L794-L821)）= 重建 run + 重跑地图 + 重放动作历史。**但同一份源码里存在一个 resident-prefix 快路径**，命中时 `restore` 的 `elapsed_ms` 直接报 `0.0`（[`NativeRunCoordinator.cs:342-344`](../../src/Sts2.NativeSim.Core/NativeRunCoordinator.cs#L342-L344)）。

实测这 8 次 `restore` 花 1.720 s（每次约 215 ms），**说明快路径基本没有命中——或者命中了，215 ms 花在别处**。二者指向完全不同的结论：

- 若不命中且可修 ⇒ `restore` 接近免费，**门槛 (ii) 通过，值得做**；
- 若已命中、其余 215 ms 是重放本身不可省 ⇒ `restore` 近乎不可压缩，**门槛 (ii) 不通过，应当停**。

这是一个可在 native 侧计时的单一问题（例如分别给"快路径命中"与"重放"两条路径打点，跑参考请求 A 即可分辨），**建议作为下一张票的唯一内容**。

## 建议

**建议做（与门槛无关，因为便宜且机制现成）：**

1. **把共享 PCK 指纹接到 corpus 路径**：在 `_native_worker` / `scenarios.py` 的默认工厂里，对整个批量测量一次 `PckFingerprint` 并下传。实测省 1.393 s/worker。离线测试用假 worker，不受影响；真机验收可用"分片字节同一"断言。
2. **先修超时缺陷再谈规模化**：单次 66.8 s 且换 worker，发生率未知。在它被理解之前，任何长批量（如 spec 的 10⁵ 行）的墙钟都不可预测。这属于缺陷诊断，不属于本方案。

**建议不做：**

3. **不要为参考请求 A 优化。** 它的每 element 成本是稳态的 2.5 倍、是参考请求 B 每行成本的 20 倍；优化它等于优化预热。
4. **不追**已测掉的捷径：handle 复用（已做，+1.9%）、native batch RPC（1.03–1.05×）、以及完全绕过 shipped run 的 fast compiler（需 34×–101×，原型 2288 个叶字段只对上 6 个）。
5. **如果目标就是 spec 的"a few thousand records"，做到第 1、2 条即可停。** 实测 37.2 行/秒意味着 3000 行约 81 秒。

**已被本次测量否证的假设：**

6. **`numpy`/`gym` 的导入时间开销**：实测 `pass` 0.053 s、`import sts2_native_sim` 0.344 s、`import sts2_native_sim.gym` 0.337 s、CLI 模块 0.524 s。gym 相对包本体**测不出额外时间成本**，故"懒加载 gym 能加快 CLI 启动"这条理由不成立。注意这只否证了**时间**：此前"父进程约 508 MiB 常驻来自 numpy"说的是**内存**，本文没有测量内存，该说法既未被证实也未被否证。

## 限制

- 参考请求 B 只有**两次**运行（41.487 / 41.033 s），不足以给出范围；参考请求 A 为三轮。
- 成本份额在**单 worker 无争用**下测得，搬到 8 worker 批量是推断，本文已标出稳健下界。
- 探针的每 element 漂移显示成本**随种子**变化（0.21–0.79 s）；本次未按 Ancient 选项数分层。
- 未做 CPU/内存 profiling，未测争用系数，未测 `restore` 快路径命中率。
- `artifacts/scenario-performance/` 被 gitignore，原始 JSON 与 corpus 目录不在 checkout 内；可复现的结论以本文表格为准。
