# 02: Localise the first-combat element timeout

**What to build:** The reason one scenario generation element can stop answering for the full 60-second request timeout and take its worker down with it. The reproducer is known and measured: IRONCLAD at Ascension 0 with run seed `200150` costs **66.79 s** end to end, writes 2 scenario rows and 1 failure row, and replaces its worker once — about **164 times** a normal element, and about **1.6 times** the whole 512-element batch reference request. This ticket delivers the localisation, not the repair: which stage stops answering, whether the worker is alive but silent or has exited, and whether the behaviour belongs to that seed's Ancient offer, to the nested prompts that offer opens, or to neither. It ends by deciding the repair, which ticket 03 carries.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] The stage that stops answering is named from a fresh run of the reproducer rather than from the earlier note, together with the failure row's own error kind and message.
- [x] The worker's state at the timeout is characterised as alive-but-silent, exited, or merely slow, with the evidence that distinguishes them — process state and the worker's own log tail.
- [x] It is stated whether the behaviour belongs to the seed's Ancient offer, to the nested prompts that offer opens, or to neither, by driving the same seed with the differing Ancient choices selected.
- [x] The observed rate is stated so that measured and assumed are separable: zero failures across the 512 elements of the batch reference request (seeds 1–128), one known reproducer elsewhere.
- [x] A repair is decided and handed to ticket 03, including whether it is a shorter bound, a retry, or a native-side change, and whether the case can be expressed in an offline test at all.

## Comments

2026-09-25：在 HEAD `e0948364` 上用全新 worker 复现，前两个 Ancient 选项产生 scenario 行；第三项 `LARGE_CAPSULE` 在 `first_combat` 的 `run_step(choose_map:0:1)` 沉默 60 s，failure 行记录 `request_timeout` / `run_step did not respond within 60.0 seconds`。超时前 `process.poll() is None`，stderr 只有启动信息与两条资源缓存警告；退出码 1 是客户端超时后主动杀进程的结果。第三项在另一个全新 worker 上单独选择仍超时，且没有 Ancient 嵌套提示。它授予 `GAMBLING_CHIP`；从 shipped game 的弃牌选择和本项目地图入战直接 `await` 的实现推断，这是入战时的卡牌选择未被过渡续接协议处理。参考请求 B 的 512 个 element 为 0 失败，请求外已知复现为 1 个，未推断总体发生率。完整时间线、实测和源码推断的界线、修复决策见 [吞吐诊断](../../../docs/research/act1-first-combat-scenario-generator-throughput.md#种子-200150-的定位补测2026-09-25head-e0948364)。交给 03：优先修 native 侧地图入战的异步提示续接；fake worker 可离线验证场景生成器处理已呈现提示的行为，但不能离线复现 shipped game 的等待本身。
