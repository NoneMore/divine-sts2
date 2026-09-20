# 08: Migrate reward, act-transition and terminal states

**What to build:** Move room rewards, standalone and custom rewards, linked/nested reward flows, act
transitions and run terminal states behind the active session.

**Blocked by:** 04, 06, 07.

**Status:** resolved

- [x] Reward stacks are represented by typed continuations, not competing mode fields.
- [x] Room, custom and standalone reward observations and action ordering remain compatible.
- [x] Combat-to-reward, reward-to-map, act-transition and terminal paths settle deterministically.
- [x] Failure codes and nested-choice limits remain unchanged.
- [x] Branch replay reproduces the expected hash for every migrated path.

## Answer

Standalone rewards, combat-room rewards, act transitions and terminal outcomes now have closed active
states whose hidden executors call typed semantic operations on the compatibility port. Reward reset,
item-reward reset and custom-reward reset all initialize `NativeRunCoordinator`, so observe, step,
fork and restore use the same active-session seam in both native hosts. Card-select, custom/linked
reward and option-pick prompts replace their reward parent while active; reward action ownership keeps
option picks on their existing compatibility path, and typed continuations rebuild their nested stack
from replay rather than serializing it.

Offline seam tests preserve action identity and ordering for standalone and room rewards, cover
combat-to-reward-to-map, act-transition and terminal settlement, retain `invalid_action` and
`choice_too_large` failure codes, and reproduce hashes after restoring every migrated path. Four-worker
shipped-game acceptance passes for card, relic, potion, custom, linked, nested and option rewards, plus
the combat-room reward cycle back to the map. The custom-reward acceptance restore assertions now run
before the next reset, matching the established rule that a reset invalidates older branch handles.
