# 03: Repair the first-combat element timeout

**What to build:** The element that today costs 66.8 s, writes a failure row and has its worker replaced completes the way any other element does — or fails quickly, within a bound that is small relative to a normal element, and without taking its worker down. The batch's contract does not change: a failure is still a failure row naming its stage and error kind, never a silent retry, and a fixed request with a fixed worker count still writes byte-identical shards.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] The reproducer at IRONCLAD, Ascension 0, seed `200150` produces its three scenario rows, or fails within a bound small relative to a normal element, with no worker replacement.
- [ ] The batch reference request still writes its full row set with zero failure rows and zero worker replacements, and its shards remain byte-identical across two runs.
- [ ] The repair is covered through the generator's public interface using the fake worker, so the case cannot regress without a game installed — or the ticket states why the case cannot be expressed offline.
- [ ] The wall clock of the reproducer before and after is recorded beside the numbers in the throughput diagnosis at `docs/research/act1-first-combat-scenario-generator-throughput.md`.

## Comments

### Handoff from 02

Seed `200150` 的第三项 `LARGE_CAPSULE` 无 Ancient 嵌套提示，进战前固定授予 `GAMBLING_CHIP`；其第一回合弃牌选择与地图入战直接等待 native task 的路径相遇，使首战 `run_step` 在 worker 存活时沉默至 60 s 超时。选择第三项单独在全新 worker 上仍复现。修复方向是 **native 侧**把地图入战接入已有的可暂停选择/恢复协议，再明确场景生成器如何记录并重放该入战提示；若 row 格式无法忠实表达，应迅速产 failure 行且保留 worker。不要用短全局超时或重试替代续接。fake worker 能覆盖生成器面对已呈现入战提示的公开接口行为，不能模拟 shipped game 内部死等；本 seed 仍须真机验收。详细证据见 [吞吐诊断](../../../docs/research/act1-first-combat-scenario-generator-throughput.md#种子-200150-的定位补测2026-09-25head-e0948364)。
