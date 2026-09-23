# 03: Promote the Act-variant probes into parity scenarios

**What to build:** Full fresh-process parity compares all sixteen generated scenarios field by field under the progression-complete baseline, with the two former fresh-profile Act-variant probes becoming ordinary parity entries rather than a special non-comparison result class.

Blocked by: 01: Materialize the progression-complete baseline.

Status: resolved

- [x] The two seeds previously used as forced-variant probes are ordinary generated scenarios in the fixed parity entry set.
- [x] The forced-variant constant, special probe execution path, probe-only report fields, and `--no-probes` behavior are removed.
- [x] The complete entry set contains sixteen field-by-field comparisons, and each entry uses the Act variant selected by its run seed under the progression-complete baseline.
- [x] Fresh execution still launches one independent menu-started shipped-game process per entry and remains the independent oracle baseline.
- [x] The report describes all sixteen entries through one result contract and no longer claims a fresh-profile Act-variant bound.
- [x] Existing offline projection/report tests cover the unified entry set and result counts.
- [x] The shipped-game fresh parity run compares all sixteen entries successfully on the supported game build.

## Comments

2026-09-23: The fixed set and unified fresh execution path were already present at the review baseline. Added an offline report test for the sixteen entries and both former probe scenarios; a complete report now rejects missing or duplicate entries. Fresh execution with `--worker-id 1100` matched 16/16 field by field on assembly `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52` and PCK `42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587`. Local report: `artifacts/parity-run/parity-run-16.json`. Offline suite: 243 passed.
