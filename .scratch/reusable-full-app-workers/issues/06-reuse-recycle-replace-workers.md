# 06: Reuse, recycle, and replace full-app workers

**What to build:** Python callers receive a reusable full-app worker abstraction that owns one process, executes entries serially with explicit start/end, retires healthy processes at a conservative cap, and replaces poisoned processes only for later entries without retrying the failed entry.

Blocked by: 02: Own the full-app process tree; 05: Start a warm second run in the same process.

Status: resolved

- [x] One reusable worker exposes serial entry execution over the bridge's explicit lifecycle and never overlaps runs.
- [x] The first entry uses the menu path and later entries use the warm direct-start path reported by the bridge.
- [x] A healthy worker accepts at most sixteen ordinary entries by default; reaching the cap closes it cleanly and causes only the next entry to create a replacement.
- [x] Entry failure, socket loss, process exit, driver failure, illegal lifecycle response, or `end_run` failure poisons and discards the worker.
- [x] The failed entry is recorded exactly once and is never automatically retried; a later unstarted entry may lazily launch a replacement in the same lane and sandbox after baseline revalidation.
- [x] Worker results expose PID, process entry ordinal, warm/cold provenance, process mode, startup/entry/teardown durations, replacement count, and PCK fingerprint work.
- [x] Controlled tests cover healthy cap recycling, mid-entry poisoning, teardown poisoning, no-retry behavior, and successful continuation on a replacement.
- [x] The abstraction remains one serial lane; it introduces neither parallel full-app workers nor RSS-triggered recycling.
