# 03: Repair the first-combat element timeout

**What to build:** The element that today costs 66.8 s, writes a failure row and has its worker replaced completes the way any other element does — or fails quickly, within a bound that is small relative to a normal element, and without taking its worker down. The batch's contract does not change: a failure is still a failure row naming its stage and error kind, never a silent retry, and a fixed request with a fixed worker count still writes byte-identical shards.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] The reproducer at IRONCLAD, Ascension 0, seed `200150` produces its three scenario rows, or fails within a bound small relative to a normal element, with no worker replacement.
- [ ] The batch reference request still writes its full row set with zero failure rows and zero worker replacements, and its shards remain byte-identical across two runs.
- [ ] The repair is covered through the generator's public interface using the fake worker, so the case cannot regress without a game installed — or the ticket states why the case cannot be expressed offline.
- [ ] The wall clock of the reproducer before and after is recorded beside the numbers in the throughput diagnosis at `docs/research/act1-first-combat-scenario-generator-throughput.md`.
