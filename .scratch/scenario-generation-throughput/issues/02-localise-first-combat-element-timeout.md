# 02: Localise the first-combat element timeout

**What to build:** The reason one scenario generation element can stop answering for the full 60-second request timeout and take its worker down with it. The reproducer is known and measured: IRONCLAD at Ascension 0 with run seed `200150` costs **66.79 s** end to end, writes 2 scenario rows and 1 failure row, and replaces its worker once — about **164 times** a normal element, and about **1.6 times** the whole 512-element batch reference request. This ticket delivers the localisation, not the repair: which stage stops answering, whether the worker is alive but silent or has exited, and whether the behaviour belongs to that seed's Ancient offer, to the nested prompts that offer opens, or to neither. It ends by deciding the repair, which ticket 03 carries.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The stage that stops answering is named from a fresh run of the reproducer rather than from the earlier note, together with the failure row's own error kind and message.
- [ ] The worker's state at the timeout is characterised as alive-but-silent, exited, or merely slow, with the evidence that distinguishes them — process state and the worker's own log tail.
- [ ] It is stated whether the behaviour belongs to the seed's Ancient offer, to the nested prompts that offer opens, or to neither, by driving the same seed with the differing Ancient choices selected.
- [ ] The observed rate is stated so that measured and assumed are separable: zero failures across the 512 elements of the batch reference request (seeds 1–128), one known reproducer elsewhere.
- [ ] A repair is decided and handed to ticket 03, including whether it is a shorter bound, a retry, or a native-side change, and whether the case can be expressed in an offline test at all.
