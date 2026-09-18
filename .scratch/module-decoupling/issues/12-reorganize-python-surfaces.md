# 12: Reorganize Python by support level

**What to build:** Move maintained commands, experiments and shipped-game acceptance into explicit
support areas while keeping documented paths as thin compatibility launchers and preventing dependency
inversion back into scripts.

**Blocked by:** 01, 11.

**Status:** ready-for-agent

- [ ] Supported library and CLI implementation live only in `sts2_native_sim`.
- [ ] Maintained tools, experiments and acceptance occupy their declared directories.
- [ ] Supported code imports none of tools, experiments or acceptance.
- [ ] Published old paths forward with the same arguments and exit behaviour during deprecation.
- [ ] Scenario materialization, Combat episodes, scoring and worker primitives stay importable for research.
