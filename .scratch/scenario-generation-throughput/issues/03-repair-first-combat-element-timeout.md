# 03: Exclude unsupported interactive first-combat relics before entering combat

**What to build:** Scenario generation recognizes a run whose final relic set contains a known, unsupported relic that asks for an interactive decision while entering the first combat. After resolving the selected Ancient choice and all of its nested decisions and leaving the Ancient room, but before entering the row-one fight, it excludes that Ancient-choice branch promptly. The branch produces an explicit failure row identifying the unsupported relic, while the worker remains usable for the next branch and element. The check uses the relics the run actually holds, including relics granted indirectly by an Ancient choice, rather than only the relic named in the offer. Supported branches still produce reproducible combat initial states.

**Blocked by:** 02: Localise the first-combat element timeout.

**Status:** done

- [x] The exclusion check runs only after all nested Ancient decisions have resolved and leaving the Ancient room has returned the map, and before the first map-node action is sent. It checks the complete relic inventory at that point. Its explicit unsupported set includes `GAMBLING_CHIP`; a relic obtained through `LARGE_CAPSULE` or another indirect Ancient reward is treated the same as one obtained directly.
- [x] An excluded branch produces one deterministic failure row with its Ancient-choice recipe, `first_combat` stage, `unsupported_interactive_first_combat_relic` error kind, and a message naming the relic or relics that caused exclusion. It has no combat initial state or state hash. The first map-node action is not sent for that branch, and no timeout or retry is used to classify it.
- [x] Fake-worker tests through the generator's public interface cover an indirectly granted unsupported relic, a supported branch that still reaches combat, later Ancient choices and a following element on the same worker, and a completed corpus with zero worker replacements. Repeating a fixed request with a fixed worker count yields byte-identical shards and summary.
- [x] On the shipped game, IRONCLAD at Ascension 0 with run seed `200150` yields three rows in offer order: two scenarios and one explicit exclusion/failure row for the `LARGE_CAPSULE` branch that ends with `GAMBLING_CHIP`. The whole one-worker request finishes in under 10 seconds on the same host used for the 66.79-second baseline, with zero worker replacements; record the before and after wall clock and row/replacement counts in the throughput diagnosis.

## Comments

### Handoff from 02

Seed `200150` 的第三项 `LARGE_CAPSULE` 无 Ancient 嵌套提示，进战前固定授予 `GAMBLING_CHIP`；其第一回合弃牌选择与地图入战直接等待 native task 的路径相遇，使首战 `run_step` 在 worker 存活时沉默至 60 s 超时。选择第三项单独在全新 worker 上仍复现。修复方向是 **native 侧**把地图入战接入已有的可暂停选择/恢复协议，再明确场景生成器如何记录并重放该入战提示；若 row 格式无法忠实表达，应迅速产 failure 行且保留 worker。不要用短全局超时或重试替代续接。fake worker 能覆盖生成器面对已呈现入战提示的公开接口行为，不能模拟 shipped game 内部死等；本 seed 仍须真机验收。详细证据见 [吞吐诊断](../../../docs/research/act1-first-combat-scenario-generator-throughput.md#种子-200150-的定位补测2026-09-25head-e0948364)。

### Scope revision

2026-09-25：本票按新的排除策略重写。上方交接中的 native 入战提示续接建议保留为历史诊断，已不再是本票的实施方向。当前验收以 Ancient 离开后、入战前的最终 relic set 为准；已知不支持项 `GAMBLING_CHIP` 应产生显式 failure 行，不进入会等待弃牌选择的首战调用，同时保持 worker 可复用。此前要求「三个 scenario 行或泛化的快速失败」已由更明确的「两个 scenario 行加一个排除 failure 行」取代。

### Implementation and verification

2026-09-25：地图 observation 不含 inventory，实际完整 relic set 位于 `leave_event` 结果的 `scoring_features.relics`。生成器现在据此在地图节点调用前排除 `GAMBLING_CHIP`，缺失 relic set 时也快速失败。fake-worker 场景测试覆盖间接与直接授予、Ancient 嵌套选择、后续选项及 element、worker 复用与 corpus 字节同一。shipped game 的 `200150` 单 worker corpus 实测 **3.892 s**、**2 scenario + 1 明确 exclusion failure**、**0 replacement**；旧基线为 **66.792 s**、**2 scenario + 1 timeout failure**、**1 replacement**。完整记录见[吞吐诊断](../../../docs/research/act1-first-combat-scenario-generator-throughput.md#工单-03-的排除策略验收2026-09-25)。完整离线测试 **275 passed**。
