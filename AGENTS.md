# Agent guide

## Related repositories

When work needs Slay the Spire 2 decompiled source, mod frameworks, or implementations from related
projects, inspect the sibling directories under `..`.

## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/`, tracked in git. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Dev environment

The commands that work on this repository's Windows host, and the one requirement a build has — MSBuild
needs named pipes, so builds and tests run only with the file sandbox off: `docs/agents/dev-environment.md`.
