# 02: Own the full-app process tree

**What to build:** A full-app client owns the shipped-game process from the moment spawn succeeds and reliably destroys that process and its descendants on close or partial-launch failure, including when a run is still active.

Blocked by: None (can start immediately).

Status: resolved

- [x] Process ownership is registered immediately after spawn, before port discovery, TCP connection, handshake, or profile readiness can fail.
- [x] A failure at every launch stage closes sockets/files and terminates the owned process tree without leaking a half-started game.
- [x] On Windows, ownership uses a Job Object or an equivalent kill-on-close primitive that includes descendants rather than terminating only the parent process.
- [x] Closing an active worker remains prompt and does not depend on a successful reusable-run teardown.
- [x] Normal close prefers the bridge's close request when possible and still guarantees process-tree termination when the bridge is unavailable or slow.
- [x] Controlled-subprocess tests observe that both parent and child processes die on close and on partial-launch failure.
- [x] Existing sandbox preparation and fresh full-app launch behavior remain unchanged from a caller's perspective.
