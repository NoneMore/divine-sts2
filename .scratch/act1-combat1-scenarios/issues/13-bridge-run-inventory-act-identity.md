# 13: Run, inventory and act identity on the bridge

**What to build:** The bridge's run and inventory blocks gain what a parity contract needs, and stop reporting the wrong numbers where they already look present. The bridge reports the game build it is running; the act index in the same base as the rest of the system instead of one-based; the Act variant alongside it; the act floor as well as the run's total floor; the map coordinate the run is on, including the row-0 Ancient coordinate once the run has travelled there; the named RNG counters; relics in order as objects carrying their counter and native state rather than bare model ids; and potions by slot with their native state, keeping empty slots so a slot index is never destroyed.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The bridge reports the game build it is running.
- [ ] The act index is reported in the same base as the rest of the system, and the Act variant is reported alongside it, so neither has to be re-derived by a comparison.
- [ ] Both the act floor and the run's total floor are reported.
- [ ] The current map coordinate is reported, including the row-0 Ancient coordinate once the run has travelled to it.
- [ ] The named RNG counters are reported, with the same names the simulator uses.
- [ ] Relics are reported in order as objects carrying model id, counter and native state, not as bare model ids.
- [ ] Potions are reported by slot with model id and native state, and empty slots are retained so the slot index survives.
- [ ] A bridged shipped run reports these fields end to end, not only in static reading.
