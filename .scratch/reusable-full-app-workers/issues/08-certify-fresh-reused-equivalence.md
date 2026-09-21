# 08: Certify fresh and reused parity as equivalent

**What to build:** A dedicated gate compares the complete fresh menu-start oracle with one reusable process, repeats the first scenario after all warm entries, verifies the progression-complete profile once across the whole sequence, and issues auditable build-bound certification only when every equivalence and lifecycle check passes.

Blocked by: 07: Collect one-process parity evidence.

Status: ready-for-agent

- [ ] The gate runs sixteen independent fresh menu-start entries, then the same sixteen entries in normal order in one reuse process.
- [ ] The reuse cap is explicitly raised to seventeen for the gate, and entry seventeen repeats the first scenario in the same process; reverse-order execution is not required.
- [ ] Every reused entry, including the sentinel, matches its fresh counterpart for success/failure classification, the full parity projection, legal boundary behavior used to reach the comparison point, clean initial history, game build, and required lifecycle provenance.
- [ ] Cross-encoder state hashes are not treated as gameplay parity; history checks only prove per-run reset and ownership of the initial hash.
- [ ] The gate captures canonical persisted and in-memory profile fingerprints at readiness and compares them once after entry seventeen; both still equal the progression-complete baseline.
- [ ] Any fresh or reused failure, field mismatch, unexpected replacement, process-count violation, profile drift, or missing teardown evidence prevents certification.
- [ ] Successful certification binds assembly SHA-256, PCK SHA-256, lifecycle/protocol revision, profile-policy revision, and scenario-set revision.
- [ ] The full report is written as an untracked artifact without claiming authority before completion; the committed certification is compact, omits machine paths, and includes the report digest and pass time.
- [ ] Ordinary fresh or reused parity cannot create or update certification.

