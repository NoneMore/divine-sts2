# 08: Migrate reward, act-transition and terminal states

**What to build:** Move room rewards, standalone and custom rewards, linked/nested reward flows, act
transitions and run terminal states behind the active session.

**Blocked by:** 04, 06, 07.

**Status:** ready-for-agent

- [ ] Reward stacks are represented by typed continuations, not competing mode fields.
- [ ] Room, custom and standalone reward observations and action ordering remain compatible.
- [ ] Combat-to-reward, reward-to-map, act-transition and terminal paths settle deterministically.
- [ ] Failure codes and nested-choice limits remain unchanged.
- [ ] Branch replay reproduces the expected hash for every migrated path.
