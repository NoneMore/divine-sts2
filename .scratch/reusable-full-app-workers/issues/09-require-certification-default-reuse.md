# 09: Require certification and default parity to reuse

**What to build:** Normal parity defaults to the fast reusable worker only when the current game, bridge lifecycle, progression-complete policy, and scenario set match a committed certification; explicit fresh mode remains available, while every uncertified or mismatched reuse attempt fails closed without silent fallback.

Blocked by: 08: Certify fresh and reused parity as equivalent.

Status: resolved

- [x] Normal parity validates the complete certification identity before launching any reuse process.
- [x] A matching certification makes reuse the default and executes the sixteen-entry run through one shipped-game process with the certified lifecycle.
- [x] Callers can explicitly select fresh mode, which uses the same progression-complete baseline and one menu-start process per entry.
- [x] Default or explicit reuse on an uncertified identity fails with an actionable error and never silently switches to fresh.
- [x] A change to the assembly, PCK, lifecycle/protocol revision, profile-policy revision, or scenario-set revision invalidates certification.
- [x] Ordinary parity remains unable to self-certify or modify the certification record.
- [x] Offline tests cover matching, missing, malformed, stale, and digest-mismatched certification plus explicit fresh operation on an uncertified build.
- [x] Shipped-game acceptance confirms the certified default starts one process for all sixteen entries, shares one PID, fingerprints the PCK once, and preserves all field-level parity results.
- [x] Help text and reports state the selected process mode and certification identity without exposing machine-specific paths.

## Comments

2026-09-24: Default parity on the committed identity matched all 16 scenarios field by field. The
ignored `artifacts/parity-run/certified-default-16-final.json` report records one shipped-game process,
one PID across all entries, one PCK fingerprint (1,901,378,340 bytes), and no process replacement.
Explicit fresh is selected with `--process-mode fresh`; the default and explicit reuse validate the
five-part identity before constructing a reusable worker. The preflight also reads the revisions
from the packaged protocol DLL and rejects a source/binary mismatch. Local certification evidence
is checked against the committed report digest when the ignored full report is present.
