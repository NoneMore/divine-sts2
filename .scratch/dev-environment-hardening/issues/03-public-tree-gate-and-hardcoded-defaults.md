# 03: A public-tree gate that can run on the tree it gates

**What to build:** `scripts/test-public-tree.ps1` fails on a pristine `main` with "Machine-specific
path or token found", matching three tracked files: `Directory.Build.props`, a smoke-test project
file, and `docs/architecture-review.md` — the B1 finding that records the defect. CI runs the script,
so CI is red. The gate's two checks are separated so that documentation may quote the pattern it
describes while secret scanning keeps covering every tracked file, and the two hardcoded game paths
are replaced by a dependency on `STS2_GAME_ROOT` that fails with a usable message.

**Blocked by:** 01 (the same script and the shared `dotnet` entry point).

**Status:** done

- [x] The machine-path scan excludes tracked markdown (`:(exclude)*.md`), and the secret-token scan
      still runs over every tracked file. The script's header states which scan has which scope and
      why, pointing at ADR-0004.
- [x] A failure names the scan that failed and prints the matching lines, as it does today.
- [x] `Directory.Build.props` no longer hardcodes a game path: `GameDataDir` derives from
      `$(STS2_GAME_ROOT)` and nothing else. The same hardcoded default is removed from
      `tests/Sts2.NativeSim.TraceExporterSmoke/Sts2.NativeSim.TraceExporterSmoke.csproj`.
- [x] A game-dependent project (`TraceExporter`, `TraceExporterSmoke`, `FullAppBridge`,
      `AutoTraceDriver`, `ApiProbe`) declared `RequiresGameData` fails, when `STS2_GAME_ROOT` is
      unset, with a message naming the variable and the property — not with a missing-reference
      error from `$(GameDataDir)\sts2.dll`.
- [x] `Protocol` and `Core` still build with `STS2_GAME_ROOT` unset, which is what CI does
      (`.github/workflows/ci.yml:31-32`).
- [x] `pwsh scripts/test-public-tree.ps1` exits 0 on this tree, and did not before the change.

## Comments

**2026-09-15 — implemented.**

- Reproduced first, unchanged: the gate failed at its first build with
  `Access to the path '<profile>\.dotnet' is denied` (ticket 01's subject) and, once that was worked
  around, failed at the scan on six lines in three files — including
  `docs/architecture-review.md:44,47,48,49`, which the ticket's original one-line description did not
  name. That self-inflicted match is the argument for the scope split, and the review document keeps
  its quoted pattern as the demonstration (ADR-0004).
- `Directory.Build.props` now defines `GameDataDir` from `$(STS2_GAME_ROOT)` only and carries a
  `RequireGameDataDir` target that fires `BeforeTargets="ResolveAssemblyReferences"` when a project
  declared `<RequiresGameData>true</RequiresGameData>` and the variable is empty. Verified both ways
  on this host: `TraceExporter` without `STS2_GAME_ROOT` fails with
  `error STS2001: STS2_GAME_ROOT is not set, so Sts2.NativeSim.TraceExporter cannot reference the
  shipped game assemblies.`, while `Protocol` builds with 0 errors. CI builds only `Protocol` and
  `Core`, so nothing in CI depends on the removed fallback.
- The two hardcoded paths were the only matches outside markdown: `F:\SteamLibrary\...` in
  `Directory.Build.props:10` and in `tests/Sts2.NativeSim.TraceExporterSmoke/...csproj:4`.
- Gate output after the change: `Public-tree checks passed.` with exit 0, run repeatedly and with the
  new tickets, spec and ADRs present (they are tracked markdown, so they are exempt from the path scan
  by design — this feature's own documents are what the exemption protects).
