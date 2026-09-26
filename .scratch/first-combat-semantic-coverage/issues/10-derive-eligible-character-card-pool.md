# 10: Derive the eligible character card pool from the active build

**What to build:** The denominator for character card coverage comes from the active game build itself: each playable character's own card models that a fully unlocked single-player run can hold, with Ancient and multiplayer-only models excluded and no build's card counts written into the repository. A build whose pool cannot be read fails explicitly instead of quietly reporting a smaller target.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] A character's eligible card models are read from the active build's own card pool under the progression-complete baseline and the single-player constraint, not from a checked-in list or a count.
- [ ] Ancient and multiplayer-only models are excluded from the pool, and another character's models never enter it.
- [ ] The pool is reported per character together with the game build it came from, and an unreadable or inconsistent pool fails rather than yielding a smaller denominator.
- [ ] The simulator and the full-app sandbox agree on the pool for the same build.
- [ ] Public tests cover the exclusions and the build-derived route; the current build's counts appear as observed evidence in the ticket's record, never as encoded constants.
