# 03: Derive the eligible character card pool from the active build

**What to build:** A coverage user can ask which of a character's card models count for character card coverage on the build actually installed — the fully unlocked single-player pool of that character, with Ancient and multiplayer-only cards excluded — and gets the eligible model identities plus the game build they belong to, with no count written into the code.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] For a character, the eligible set is read from the active build's own character card pool under the progression-complete baseline, and names each eligible card model once.
- [ ] Ancient and multiplayer-only cards are excluded by a stated rule rather than by a hand-maintained list, and no eligible card count is a constant any code asserts.
- [ ] The result identifies the game build it was derived from, so a report can state which build its denominator belongs to.
- [ ] The present build's observed counts (83 eligible Ironclad models and 84 for each other playable character) are recorded as evidence for this build, not as expectations a build-independent test encodes.
- [ ] A public test derives the set for at least two characters, finds an excluded card of each excluded kind absent, and finds an eligible card that no constant list would have produced.
