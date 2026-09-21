# 04: End one shipped run without exiting its worker

**What to build:** A reuse-mode shipped-game process can start one menu-driven run, explicitly end it at any stable decision boundary, report auditable teardown evidence, and remain alive in a well-defined idle state rather than exiting with the shipped driver.

Blocked by: 01: Materialize the progression-complete baseline.

Status: ready-for-agent

- [ ] Process mode is fixed at launch, reported by the ready handshake, and a client/process mode mismatch is rejected before lifecycle state changes.
- [ ] Reuse-only seams are installed only in reuse mode; missing required seams make reuse unavailable rather than partially functional.
- [ ] The externally observable lifecycle enforces `launching → idle → running → ending → idle`, with terminal `poisoned` and `closed` states.
- [ ] Only idle accepts `start_run`, only running accepts run actions and `end_run`, ending accepts no new run, and poisoned accepts only close; overlapping lifecycle requests and a second client fail closed.
- [ ] `start_run` never performs an implicit teardown.
- [ ] `end_run` is accepted at any stable decision boundary where the bridge is waiting for coordinator input, not only at combat or a natural run ending.
- [ ] Ending the menu-started run performs the minimal shipped-run cleanup and keeps the reuse process alive and idle.
- [ ] The response records the ended generation, ending phase, parked-wait release, stale-continuation refusals, driver result, reset-time history counts, final state, and duration.
- [ ] Final close destroys an active or idle worker without requiring `end_run` to succeed.
- [ ] Protocol-level tests cover every legal and illegal transition through the public RPC surface.

