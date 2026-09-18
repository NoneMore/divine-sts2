# 09: Retire non-combat legacy dispatch

**What to build:** Remove the compatibility adapter, non-combat mode flags and duplicated Step/Capture/
BuildActions dispatch after every non-combat state has migrated. Combat remains an explicit legacy
active-state variant for later work.

**Blocked by:** 08.

**Status:** ready-for-agent

- [ ] Exactly one active state determines action execution, projection and legal actions.
- [ ] No non-combat room/action switch remains in the coordinator.
- [ ] Branch projection no longer mirrors non-combat mode flags.
- [ ] The temporary non-combat adapter and replaced tests are deleted.
- [ ] All offline, acceptance, parity and public-tree gates pass with frozen contracts.
