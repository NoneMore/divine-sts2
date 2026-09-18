# 05: Migrate the map state

**What to build:** Move map observation, legal actions, action execution and next-state selection behind
the active-session implementation, using the semantic native port rather than reflection objects.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] Map projection and its hidden action executors are produced together.
- [ ] Entering each supported map point selects exactly one next active state.
- [ ] Ancient entry and the recorded first-combat replay remain bit-for-bit compatible.
- [ ] The coordinator contains no map-specific dispatch.
- [ ] The old map path is removed when the new path passes its seam tests.
