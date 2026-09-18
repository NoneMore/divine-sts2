# 06: Migrate rest, treasure and shop states

**What to build:** Concentrate each simple non-combat room's projection, legal actions and transitions
behind the active session without creating caller-visible room interfaces.

**Blocked by:** 05.

**Status:** ready-for-agent

- [ ] Rest, treasure and shop each have one active-state implementation.
- [ ] Their observation and action ordering remain compatible.
- [ ] Native operations cross the semantic port; reflection objects do not enter state implementations.
- [ ] The coordinator contains no room-specific dispatch for these states.
- [ ] Replaced legacy methods and flags are removed rather than retained in parallel.
