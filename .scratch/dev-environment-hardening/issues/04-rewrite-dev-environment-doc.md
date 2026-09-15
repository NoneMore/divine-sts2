# 04: Rewrite the dev-environment document around commands and causes

**What to build:** `docs/agents/dev-environment.md` is 179 lines of numbered session history whose
first promise is that none of it is a repo defect. With the workarounds now living in
`scripts/common.ps1`, `NativeWorker` and the gate, the document becomes a short present-tense guide:
the commands that work, the two repository defects and their status, and the environment's inherent
quirks with a precise cause each. Nothing in the repository depends on its numbering — the string
"dev-environment" appears exactly once outside the file, in `AGENTS.md` — so the numbering goes.

**Blocked by:** 01, 02, 03 (the document describes the entry point, the redirect and the gate).

**Status:** done

- [x] Three sections, no item numbering, present tense, 80–110 lines: the fast path; repository defects
      and their status; inherent environment quirks (symptom → cause → what to do now).
- [x] The fast path is commands only (`scripts/bootstrap.ps1`, the build script, `doctor`) and contains
      no environment block a reader must copy — `.env` is named as the place for local overrides.
- [x] Item 12's mechanism is corrected (the `libraryfolders.vdf` *is* read; the missing piece is the
      registry lookup) and its deferral is recorded with the pointer to the single-discovery-policy
      work. Item 13 records the gate as fixed with the file list it actually matched.
- [x] The pytest entry states the measured cause: pytest creates every temporary directory with
      `mode=0o700` and this sandbox denies access to directories created that way, including to their
      creator; an in-repo `--basetemp` does not help; tests that only touch files they create are
      unaffected.
- [x] The .NET runtime entry records `DOTNET_ROLL_FORWARD=Major`, which `client.py` already sets.
- [x] `docs/architecture-review.md` B1 (`:42-54`) and its restatement (`:813`) carry a resolution note
      naming this feature; `AGENTS.md`'s description of the document matches what it now covers.
- [x] The new text contains no drive-qualified machine path: the gate that this ticket fixes would
      otherwise match the documentation that describes it.

## Comments

**2026-09-15 — implemented.**

- Final document: 110 lines, three sections, no numbering, present tense. The intro states which
  modules adapt and that each adaptation is probe-conditional, which is the one thing a reader needs
  before the sections.
- The fast path names `scripts/doctor.ps1` (added in ticket 01) and states plainly that the Python CLI
  does not read `.env`, so the CLI is reached through a script rather than a bare shell. A reader who
  follows `README.md`'s `python -m sts2_native_sim.cli doctor` on a host that needs `.env` would
  otherwise get a discovery failure with no explanation.
- Corrections carried over from the old file, each now verified against the code: the `vdf` *is* read
  (`paths.py:35-43`); `NativeWorker` pins `DOTNET_ROLL_FORWARD=Major` (`client.py`), so the old
  caller-side env block was a workaround for something already handled; the gate matched three files,
  not two; and the pytest cause is `mode=0o700`, not "the same class of denial".
- `AGENTS.md`'s summary no longer promises "build flags, toolchain installs, redirected user
  directories, pytest temp dirs" as quirks to look up — after tickets 01–03 those are repository
  behaviour, and the document is described as what it now is.
- Not grepped for a machine path by hand: the gate's path scan (non-markdown) plus an explicit
  `Select-String` over the new document both come back empty, and the review document's own quoted
  pattern is the deliberate exception (ADR-0004).
