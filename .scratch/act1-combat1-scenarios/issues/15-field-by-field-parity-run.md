# 15: Field-by-field parity run against the shipped game

**What to build:** The acceptance gate for the feature. For a fixed sample of about a dozen generated scenarios spanning characters and Ascensions, the shipped game is driven with the same character, Ascension, run seed, Act variant, Ancient choice and nested choices, and every field of the parity contract is compared against the record's combat initial state. The comparison goes through a projection layer that normalises the bridge's observation and the record into one shape — including the phase and decision-kind vocabulary mapping and the act-index base — and then uses the repository's existing per-path comparison helper, which was built for exactly this and currently has no caller. A mismatch names the field path that differed. The two encoders' state hashes are never compared, because they are incomparable by construction and a hash match would prove nothing. The evidence document records what has actually been observed at runtime, so a static conclusion is never mistaken for a measurement, and the sample states which nested-choice kinds it covers rather than implying complete coverage.

**Blocked by:** 01: Configurable sandbox root for the full-app bridge; 06: Tracer bullet — one seed to one generated scenario; 11: The bridge's combat block carries the full parity contract; 12: Ordered piles and per-card identity on the bridge; 13: Run, inventory and act identity on the bridge.

**Status:** ready-for-agent

- [ ] A fixed sample of about a dozen scenarios, spanning characters and Ascensions, drives the shipped game through the same Ancient room and row-1 node each record describes, and compares the full contract field list.
- [ ] The comparison is field by field and reports the first differing field path; no state hash is compared at any point.
- [ ] The projection layer maps the bridge's phase words onto the simulator's decision kinds and normalises the act-index base, so neither difference is reported as a false mismatch.
- [ ] The contract fields covered are stated explicitly, so a field that is not compared cannot be mistaken for one that is.
- [ ] The oracle runs on a machine whose shipped-game install and local app-data live on different drives, with the sandbox on the game's own volume.
- [ ] The sample states which nested-choice kinds it covers and names any kind it cannot drive, rather than implying complete Ancient-choice coverage.
- [ ] The comparison routes through the repository's existing per-path comparison helper instead of a third comparator, and that helper gains a real caller.
- [ ] The evidence document separates what has been read from the decompiled build from what has actually been observed at runtime, and records the result of this run.
- [ ] Offline tests assert the same contract field list the oracle compares, so the two seams cannot drift apart.
