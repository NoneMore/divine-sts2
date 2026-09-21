# 09: Require certification and default parity to reuse

**What to build:** Normal parity defaults to the fast reusable worker only when the current game, bridge lifecycle, progression-complete policy, and scenario set match a committed certification; explicit fresh mode remains available, while every uncertified or mismatched reuse attempt fails closed without silent fallback.

Blocked by: 08: Certify fresh and reused parity as equivalent.

Status: ready-for-agent

- [ ] Normal parity validates the complete certification identity before launching any reuse process.
- [ ] A matching certification makes reuse the default and executes the sixteen-entry run through one shipped-game process with the certified lifecycle.
- [ ] Callers can explicitly select fresh mode, which uses the same progression-complete baseline and one menu-start process per entry.
- [ ] Default or explicit reuse on an uncertified identity fails with an actionable error and never silently switches to fresh.
- [ ] A change to the assembly, PCK, lifecycle/protocol revision, profile-policy revision, or scenario-set revision invalidates certification.
- [ ] Ordinary parity remains unable to self-certify or modify the certification record.
- [ ] Offline tests cover matching, missing, malformed, stale, and digest-mismatched certification plus explicit fresh operation on an uncertified build.
- [ ] Shipped-game acceptance confirms the certified default starts one process for all sixteen entries, shares one PID, fingerprints the PCK once, and preserves all field-level parity results.
- [ ] Help text and reports state the selected process mode and certification identity without exposing machine-specific paths.
