# Agent guide

Agents use the same development environment and commands as human contributors. The development
contract lives in `CONTRIBUTING.md`; do not add agent-only build wrappers, cache layouts, sandbox
workarounds, or reduced test modes. A runner that cannot provide normal Windows process and named-pipe
behavior does not satisfy this repository's development-host requirements.

## Related repositories

When work needs Slay the Spire 2 decompiled source, mod frameworks, or implementations from related
projects, inspect the sibling directories under `..`.

## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/`, tracked in git. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
