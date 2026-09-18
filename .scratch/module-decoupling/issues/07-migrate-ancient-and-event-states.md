# 07: Migrate Ancient and event states

**What to build:** Move Ancient and ordinary event decisions behind the active session, including their
Card-select prompt continuations and transitions into combat or back to the map.

**Blocked by:** 05, 06.

**Status:** ready-for-agent

- [ ] Ancient choices and nested choices reproduce every recorded Generated scenario recipe.
- [ ] Event observation, action order and errors remain compatible.
- [ ] Event-to-combat and event-to-map paths settle at one stable decision.
- [ ] No event or Ancient mode flag remains a second source of truth.
- [ ] Shipped-game acceptance covers representative prompt and combat paths.
