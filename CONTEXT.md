# STS2 Gym

STS2 Gym exposes isolated native Slay the Spire 2 runs for simulation and full-application automation without treating profile completion as simulation state.

## Language

**Fully unlocked run**:
A new run whose legal gameplay content pools have every progression unlock gate open, while still obeying game-mode constraints. Every simulator run starts fully unlocked; this does not imply discovered compendium entries, achievements, tutorial completion, badges, or fabricated career statistics.
_Avoid_: Completed profile, all-unlocked profile

**Full-app sandbox**:
An isolated single-player full-game session whose user-data directories are separate from the player's real profile and saves.
_Avoid_: Test profile, real profile
