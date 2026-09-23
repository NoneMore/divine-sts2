# 07: Collect one-process parity evidence

**What to build:** The parity certification candidate can execute the complete sixteen-entry set through one reusable worker and produce the same field-level results plus enough lifecycle and performance provenance to prove that only one shipped-game process and one PCK fingerprint served the run.

Blocked by: 03: Promote the Act-variant probes into parity scenarios; 06: Reuse, recycle, and replace full-app workers.

Status: resolved

- [x] The reusable candidate executes all sixteen parity entries in their normal order through one worker and one full-app sandbox.
- [x] Entry one uses the shipped menu path and entries two through sixteen use warm direct start.
- [x] Every entry feeds the existing parity projection and per-path comparison contract; no reuse-specific gameplay projection or shared cross-encoder hash is introduced.
- [x] A lifecycle failure remains that entry's failure, poisons the process, and prevents the candidate from being mistaken for one-process evidence even if later entries continue on a replacement.
- [x] Entry results report PID, ordinal, warm provenance, lifecycle timings, teardown evidence, and replacement count.
- [x] The summary reports shipped-game processes started, maximum live process count, PCK bytes hashed, and total wall time.
- [x] A healthy candidate proves all sixteen entries share one PID, exactly one shipped-game process was started, and the PCK was fingerprinted once; no elapsed-time threshold is asserted.
- [x] Ordinary parity does not yet change its default mode or issue certification as part of this ticket.

## Comments

2026-09-23: `--reuse-candidate` ran the fixed sixteen-entry set in one serial worker and sandbox. The shipped-game acceptance matched 16/16 field by field on assembly `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52` and PCK `42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587`. All entries shared one PID; the report recorded one process launch, one PCK fingerprint of 1,901,378,340 bytes, a maximum of one live process, and 84.7 seconds total wall time. Local evidence: `artifacts/parity-run/reuse-candidate-16.json`.
