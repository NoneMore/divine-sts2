# 09: Retire non-combat legacy dispatch

**What to build:** Remove the compatibility adapter, non-combat mode flags and duplicated Step/Capture/
BuildActions dispatch after every non-combat state has migrated. Combat remains an explicit legacy
active-state variant for later work.

**Blocked by:** 08.

**Status:** resolved

- [x] Exactly one active state determines action execution, projection and legal actions.
- [x] No non-combat room/action switch remains in the coordinator.
- [x] Branch projection no longer mirrors non-combat mode flags.
- [x] The temporary non-combat adapter and replaced tests are deleted.
- [x] All offline, acceptance, parity and public-tree gates pass with frozen contracts.

## Answer

Every RPC reset, including combat, now initializes `NativeRunCoordinator`; its `ActiveRunSession`
owns the single current state and routes non-combat actions through typed map, room, event, reward,
prompt, act-transition and terminal variants. Combat is the only explicit legacy state. Option picks
now carry their own typed continuation instead of falling through generic action dispatch, and both
native hosts route reset, observe, step, fork and restore through the same coordinator seam.

The shipped-game port is now `INativeRunAdapter` with a production `NativeRunAdapter`; the temporary
compatibility types and files are gone. Native branch checkpoints retain one typed reset recipe plus
history instead of copying six mode booleans, while the frozen hash kernel derives its legacy fields
from that recipe. Restore replays non-combat actions through their semantic operations, leaving the
legacy `StepAsync` dispatch limited to combat and native choice execution.

Release and Debug/Godot builds pass with no warnings, as do 43 Core xUnit tests, 198 offline pytest
tests, the non-combat shipped-game acceptance suite, portable restore across every reset kind,
Act-variant and Ancient coverage, all fourteen field-for-field shipped-game parity samples, and the
public-tree gate. The parity samples were isolated into one process apiece because this host drops the
long-lived harness session while it launches a later shipped-game process; every isolated comparison
matched all declared fields.
