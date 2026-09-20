# 12: Reorganize Python by support level

**What to build:** Move maintained commands, experiments and shipped-game acceptance into explicit
support areas while keeping documented paths as thin compatibility launchers and preventing dependency
inversion back into scripts.

**Blocked by:** 01, 11.

**Status:** resolved

- [x] Supported library and CLI implementation live only in `sts2_native_sim`.
- [x] Maintained tools, experiments and acceptance occupy their declared directories.
- [x] Supported code imports none of tools, experiments or acceptance.
- [x] Published old paths forward with the same arguments and exit behaviour during deprecation.
- [x] Scenario materialization, Combat episodes, scoring and worker primitives stay importable for research.

## Answer

Maintained commands now live under `python/tools`, unsupported research lives under
`python/experiments`, and shipped-game checks live under `tests/acceptance`. The documented
`python/native_rollout_farm.py` and `python/soak_test_20_workers.py` paths remain thin launchers that
execute the relocated modules without changing arguments or exit handling; the existing Gym import
compatibility wrapper remains in place.

The supported package has no imports from the lower support areas. Shared frozen scenario data moved
behind an internal `sts2_native_sim` module so tools and acceptance no longer force supported code to
depend on scripts. Scenario materialization, `CombatEpisode`, worker types and scoring interfaces remain
importable through their supported package surfaces.
