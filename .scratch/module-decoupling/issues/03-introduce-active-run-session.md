# 03: Introduce the Active run session seam

**What to build:** Put a compatibility implementation behind `Current DecisionFrame` and
`ApplyAsync(actionId)` so the coordinator stops choosing capture, legal-action and execution paths by
room or action kind. Preserve every external contract while legacy state implementations still exist.

**Blocked by:** 02.

**Status:** resolved

- [x] A frame atomically supplies observation, legal actions, terminal status and kernel projection.
- [x] The coordinator alone owns branch/history, hash, RPC envelope and timing.
- [x] The session is serial, validates before native mutation and has deterministic poisoned-state behaviour.
- [x] Combat and unmigrated states are reachable only through one temporary compatibility adapter.
- [x] Existing schema, hash, errors, scenario rows and parity remain unchanged.

## Answer

`RunSession` now exposes the active run through only `Current DecisionFrame` and
`ApplyAsync(actionId)`. The compatibility implementation serializes transitions, builds its hidden
executor table from the current frame, validates before mutation, restores after a failed mutation,
and becomes deterministically poisoned if recovery itself fails. `DecisionFrame` atomically carries
the observation, legal actions, terminal/victory status, compatibility kernel projection and scoring
projection.

`NativeRunCoordinator` projects frames into the existing RPC result, computes the unchanged state
hash and `s:` branch identity, and owns action history and transition timing. Every legacy run state,
including combat, is reachable through the single `LegacyRunSessionAdapter`; that adapter checks the
coordinator's projected hash against the legacy environment on every real capture and reports
`protocol_desync` rather than allowing drift. Offline session tests cover atomic frames, serial
mutation, pre-mutation validation, recovery and poison semantics, while the shipped-game Ancient
acceptance covers run reset, nested choices, first combat and branch restoration.
