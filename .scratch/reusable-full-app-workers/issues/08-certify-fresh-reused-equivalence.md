# 08: Certify fresh and reused parity as equivalent

**What to build:** A dedicated gate compares the complete fresh menu-start oracle with one reusable process, repeats the first scenario after all warm entries, verifies the progression-complete profile once across the whole sequence, and issues auditable build-bound certification only when every equivalence and lifecycle check passes.

Blocked by: 07: Collect one-process parity evidence.

Status: resolved

- [x] The gate runs sixteen independent fresh menu-start entries, then the same sixteen entries in normal order in one reuse process.
- [x] The reuse cap is explicitly raised to seventeen for the gate, and entry seventeen repeats the first scenario in the same process; reverse-order execution is not required.
- [x] Every reused entry, including the sentinel, matches its fresh counterpart for success/failure classification, the full parity projection, legal boundary behavior used to reach the comparison point, clean initial history, game build, and required lifecycle provenance.
- [x] Cross-encoder state hashes are not treated as gameplay parity; history checks only prove per-run reset and ownership of the initial hash.
- [x] The gate captures canonical persisted and in-memory profile fingerprints at readiness and compares them once after entry seventeen; both still equal the progression-complete baseline.
- [x] Any fresh or reused failure, field mismatch, unexpected replacement, process-count violation, profile drift, or missing teardown evidence prevents certification.
- [x] Successful certification binds assembly SHA-256, PCK SHA-256, lifecycle/protocol revision, profile-policy revision, and scenario-set revision.
- [x] The full report is written as an untracked artifact without claiming authority before completion; the committed certification is compact, omits machine paths, and includes the report digest and pass time.
- [x] Ordinary fresh or reused parity cannot create or update certification.

## Comments

2026-09-24: The dedicated gate passed 16/16 fresh and 17/17 reused comparisons on assembly
`A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52` and PCK
`42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587`. Fresh used 16
PIDs; reuse used one PID, one PCK fingerprint, and the same first scenario at entry 17. In-memory
and persisted profile fingerprints both stayed `748178a628480a1e2dbee91c9fce4db7aecac27f0dabbd4693fcd3188e3ebf02`.
Ignored evidence: `artifacts/reuse-certification/report.json` (SHA-256
`e6c2a4024045a5f29e0b626656c04740381d42de9fad488939814607e523ea1d`). Compact trust
record: `certifications/full-app-reuse.json`.
