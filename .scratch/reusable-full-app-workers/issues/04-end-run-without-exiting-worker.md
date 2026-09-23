# 04: End one shipped run without exiting its worker

**What to build:** A reuse-mode shipped-game process can start one menu-driven run, explicitly end it at any stable decision boundary, report auditable teardown evidence, and remain alive in a well-defined idle state rather than exiting with the shipped driver.

Blocked by: 01: Materialize the progression-complete baseline.

Status: resolved

- [x] Process mode is fixed at launch, reported by the ready handshake, and a client/process mode mismatch is rejected before lifecycle state changes.
- [x] Reuse-only seams are installed only in reuse mode; missing required seams make reuse unavailable rather than partially functional.
- [x] The externally observable lifecycle enforces `launching → idle → running → ending → idle`, with terminal `poisoned` and `closed` states.
- [x] Only idle accepts `start_run`, only running accepts run actions and `end_run`, ending accepts no new run, and poisoned accepts only close; overlapping lifecycle requests and a second client fail closed.
- [x] `start_run` never performs an implicit teardown.
- [x] `end_run` is accepted at any stable decision boundary where the bridge is waiting for coordinator input, not only at combat or a natural run ending.
- [x] Ending the menu-started run performs the minimal shipped-run cleanup and keeps the reuse process alive and idle.
- [x] The response records the ended generation, ending phase, parked-wait release, stale-continuation refusals, driver result, reset-time history counts, final state, and duration.
- [x] Final close destroys an active or idle worker without requiring `end_run` to succeed.
- [x] Protocol-level tests cover every legal and illegal transition through the public RPC surface.

## Comments

The shipped-game RPC acceptance exercises normal end at the initial and a later decision, idle and running request rejection, overlapping requests, second-client poisoning, fresh-mode rejection, and final close. Warm direct-start after this idle state is the separate 05 ticket.
