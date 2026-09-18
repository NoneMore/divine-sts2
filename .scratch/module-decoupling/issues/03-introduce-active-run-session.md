# 03: Introduce the Active run session seam

**What to build:** Put a compatibility implementation behind `Current DecisionFrame` and
`ApplyAsync(actionId)` so the coordinator stops choosing capture, legal-action and execution paths by
room or action kind. Preserve every external contract while legacy state implementations still exist.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] A frame atomically supplies observation, legal actions, terminal status and kernel projection.
- [ ] The coordinator alone owns branch/history, hash, RPC envelope and timing.
- [ ] The session is serial, validates before native mutation and has deterministic poisoned-state behaviour.
- [ ] Combat and unmigrated states are reachable only through one temporary compatibility adapter.
- [ ] Existing schema, hash, errors, scenario rows and parity remain unchanged.
