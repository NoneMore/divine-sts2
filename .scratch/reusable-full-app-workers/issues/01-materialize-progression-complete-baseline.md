# 01: Materialize the progression-complete baseline

**What to build:** Every full-app sandbox materializes the project's progression-complete baseline before it can start a run. Missing progress is provisioned through the shipped game's progress APIs, existing progress is accepted only when its canonical semantic fingerprint matches, and the ready handshake proves which baseline and game build the process will use.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] The project-owned completion policy marks cards, relics, potions, monsters, encounters, Acts, and events discovered; obtains epochs; completes character and multiplayer Ascension progression, total unlocks, and tutorials; and creates the enemy/encounter statistic rows required by the shipped game.
- [ ] The policy does not synthesize achievements, real career totals, existing run saves, the player's real profile, or multiplayer session state, and it has no runtime dependency on the reference Workshop Mod or a pre-generated save.
- [ ] Provisioning a sandbox with missing baseline progress produces the canonical semantic fingerprint, and provisioning/validation is idempotent.
- [ ] Existing progress whose semantic fingerprint differs fails closed instead of being silently overwritten; non-semantic metadata such as timestamps does not affect the fingerprint.
- [ ] Before progress is loaded and validated, the bridge reports `initializing` and rejects `start_run`; once ready, the handshake reports progression policy, canonical profile fingerprint, PID, bound port, and game build.
- [ ] Requested character and Ascension still override stored profile preferences.
- [ ] Shipped-game acceptance demonstrates that an already-discovered Act follows the run seed rather than the first-discovery override.
- [ ] All existing full-app acceptance entry points receive the same progression-complete baseline and remain green.

