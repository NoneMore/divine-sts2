# STS2 Full-Application Native Control Bridge Specification & Architecture Report

> **Evidence status:** This is a dated development report, not current public
> release certification. Re-run the harness on the supported build before
> treating the GO/PROVEN language or benchmark numbers below as current.
>
> **Role:** canonical specification of the `full_application_native` bridge —
> its sandboxing, protocol, and suppression seams. `full_application_native` is
> the designated differential authority for the first-combat program, but its
> read-only projection is still incomplete (see
> `docs/first-combat-scene-generation-plan.md` §3 and the E5 unit in §5), so it
> cannot yet serve the golden differential gate. The environment contract for
> the in-process `reconstructed_native` environment lives in
> `docs/persistent-environment.md`.

## 1. Executive Summary & Architecture Verdict

- **Historical milestone verdict**: **GO (PROVEN)**
- **Architecture**: `full_application_native` (`SlayTheSpire2.exe --headless --force-steam=off` + isolated C# control mod + external TCP IPC bridge).
- **Historical outcome**: On the tested build, the shipped, unmodified
  `SlayTheSpire2.exe` binary served as the authoritative, controllable headless
  environment without synthetic mid-combat state reconstruction, synthetic
  resets, or handcrafted lifecycle reimplementation.

### Historical benchmark highlights (4 concurrent headless shipped processes)
- **State Hash Equality**: **100.0%** bit-for-bit determinism across all 4 independent OS processes across all sequential action steps.
- **Prefix Replay & Branching**: Verified 100% prefix match followed by clean counterfactual state divergence on branching actions (`play_card:0` vs `play_card:1:target:1`).
- **Synthetic State Reconstruction**: **0%** (zero synthetic resets or state injection).
- **Decision Latency (Card Plays)**: Mean = **28.28 ms** (P50).
- **Turn Latency (Full Turn + Enemy AI Turn)**: Mean = **672.40 ms** (P95).
- **Aggregate Decision Throughput**: **26.0 decisions/sec** across 4 concurrent local workers.
- **Memory Footprint**: **766.7 MB RSS** per process.

### Full-Act 1 Autonomous Control Acceptance (2026-08-23)
- **Milestone**: Full-Act 1 route (Floors 1–13) driven autonomously through combats, card rewards, events, rest sites, treasure, and pre-Boss floor.
- **Total Actions Executed**: **300** across all decision phases.
- **Phases Covered**: `combat`, `card_reward`, `rewards`, `map`, `rest_site`, `event`, `treasure`.
- **4-Worker State Hash Equality**: **100%** (zero divergences across all 300 steps).
- **Independent Worker 5 Prefix Replay**: **100% bit-for-bit identical** (300/300 steps matched).
- **Decision Latency (Act 1 Full Route)**: Mean = **244.45 ms** (includes map transitions, combat turns, reward screens).
- **Max Steps Budget**: 300 (raised from 120 in trajectory exporter).

### Multi-Worker Trajectory Export Pipeline (2026-08-23 — 100-Run Hardened Corpus)
- **Runs Collected**: **100 complete runs** (4 workers × 25 runs each, 100% completion rate).
- **Total Transitions Exported**: **22,063** JSONL records to `artifacts/trajectories/`.
- **Character Stratification**: Exactly 20 runs per character across all 5 characters (`IRONCLAD: 20`, `SILENT: 20`, `DEFECT: 20`, `NECROBINDER: 20`, `REGENT: 20`).
- **Episode Depth Quality**: **88.0%** of runs (88/100) produced >= 150 transitions (mean depth = 220.6 transitions/run).
- **Wall Time**: **1,585.58 s** (~26.4 min total wall time across 4 concurrent workers).
- **Aggregate Throughput**: **13.91 transitions/sec** sustained across 4 parallel workers.
- **Latency Profile**: P50 = 35.59 ms, P95 = 714.38 ms, Mean = 234.62 ms.
- **Label Provenance & Authority**:
  - `v_win`: `full_application_native_terminal_outcome` (Gold Native Authority)
  - `v_hp_loss`: `full_application_native_terminal_hp` (Gold Native Authority)
  - `v_relic_ev`: `full_application_native_relic_count` (Gold Native Authority)
  - `v_boss_readiness_heuristic`: `python_approximate` (Clearly marked non-authoritative heuristic)

---

## 2. Pinned Executable & Binary Integrity

- **Installed Directory**: `<STS2_GAME_ROOT>`
- **Application Binary**: `SlayTheSpire2.exe` (Godot .NET single-file host)
- **Engine Version**: `0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314`
- **Assembly SHA-256 (`sts2.dll`)**: `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`
- **Package SHA-256 (`SlayTheSpire2.pck`)**: `42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587`

---

## 3. Sandboxing & Isolation Model

Each worker process runs within a strictly isolated sandbox directory:
1. **Hardlinks** to `SlayTheSpire2.exe` and `SlayTheSpire2.pck`.
2. **Directory Junctions** for large asset folders:
   - `data_sts2_windows_x86_64`
   - `controller_config`
3. **Dedicated Isolated Directories**:
   - `userdata/` (stores profile, saves, logs, port discovery token)
   - `local_userdata/`
   - `mods/` (contains `sts2-full-app-bridge.dll` and `sts2-full-app-bridge.json`)
4. **Isolated Environment Variables**:
   - `APPDATA=<sandbox_dir>\userdata`
   - `LOCALAPPDATA=<sandbox_dir>\local_userdata`
   - `STS2_FULL_APP_BRIDGE_PORT=<dynamic_or_fixed_port>`
   - `STS2_FULL_APP_BRIDGE_PORT_FILE=<sandbox_dir>\userdata\bridge_port.txt`
5. **CLI Flags**:
   `--headless --force-steam=off`

---

## 4. Bridge Protocol Specification

The bridge exposes a line-delimited JSON-RPC TCP protocol over UTF-8 without BOM.

### Supported RPC Methods
1. `hello`: Returns worker metadata, PID, Godot version, bridge mod version, isolation confirmation, the exact build fingerprint (assembly and PCK SHA-256), and the frozen run-start configuration.
2. `start_run(seed, character, ascension, act1, pin_profile, nested_choices, combat_complete)`: Pins the sandbox profile, applies the requested ascension through the shipped lobby seam, pins Act 1, starts a run, and advances the game state to the first decision boundary. See "Run-start pinning" below.
3. `observe()`: Returns the canonical `ObservationDto` snapshot (combat state, player HP, energy, hand, draw/discard/exhaust piles, enemy intents, modifiers, state hash).
4. `legal_actions()`: Returns the exact list of `LegalActionDto` objects available at the current decision boundary.
5. `step(action_id)`: Enqueues and executes the specified action (`play_card:<idx>:target:<combat_id>`, `use_potion:<idx>:target:<combat_id>`, `end_turn`, `choose_node:<idx>`, `choose_rest:<id>`), waits for action execution to finish, and returns the next observation.
6. `history()`: Returns the trace of executed action IDs and intermediate SHA-256 state hashes.
7. `close()`: Cleanly shuts down the remote game process.

### Read-only first-combat root projection (`schema_version` 3)

`observation.game_build`, `observation.run` and `observation.combat` are the projection
`docs/first-combat-scene-generation-plan.md` E5 requires for the golden differential:

- `game_build`: `version`, `assembly_sha256`, `pck_sha256`, read from the loaded assembly and the
  PCK beside the executable — never from configuration.
- `run`: `seed`, `character`, `ascension`, `gold`, `current_hp`, `max_hp`, `rng_counters` (every
  Run RNG stream from the shipped serializable), `deck`, `relics` (identity, counter, native saved
  state), `potions` (slot-indexed array whose length is the capacity), `potion_capacity`,
  `act_index`, `act_floor`, `act_id`.
- `combat`: native `turn` and native `PlayerCombatState.Phase` (the root boundary is
  `turn == 1 && phase == "Play"`; the bridge-level `phase == "combat"` string is not a substitute),
  `energy`, `max_energy`, `stars`, `encounter` (model id, room type, declared monster list, slots),
  `creatures` (native order, HP/max/block/alive, next move with intents, powers), `piles` (Hand,
  DrawPile, DiscardPile, ExhaustPile, PlayPile in native order, each card with model, type, target
  type, resolved cost, upgrades, enchantment and native saved state), and `orbs` when the character
  has an orb queue.

The projection only reads shipped objects. It never mutates the game, never touches a visible
window, and never depends on presentation state. Environment-local handles (`net_id`,
`instance_id`, `combat_id`, list indices) are projected for diagnostics but are not cross-environment
identities; `docs/first-combat-scene-generation-plan.md` E5 records which fields the comparator
actually compares.

A boundary is *combat-bearing* when its ambient room phase is a combat phase, or when a pending nested
choice is interrupting a combat room. The second case matters because a relic obtained at Neow can open
a card choice during combat start, before `CombatManager` reports itself in progress: the combat
projection then comes from the state still attached to the player's creature, and the reconstructed
environment's matching boundary carries the same hand and piles. Every other boundary keeps the
phase-only classification, so a combat room's reward screens still project as rewards.

### Run-start pinning

A fresh sandbox profile has no revealed epochs, so it has no Neow (the starting map point is forced
to `Monster`) and every requested ascension is clamped to 0. With `pin_profile` (default on) the
bridge pins the sandbox profile in a postfix on `SaveManager.InitProgressData` — after the profile
loads, before the main menu reads it:

- every epoch in `EpochModel.AllEpochIds` is revealed, matching the reconstructed environment's
  `UnlockState.all` run-start profile;
- every encounter is recorded as seen;
- the run count is kept non-zero (a zero run count makes `Overgrowth` present Act 1 rooms in a fixed
  tutorial order and changes unknown-node rolls);
- per-character `MaxAscension` is raised so the shipped lobby clamp cannot silently lower the
  request.

The requested ascension is then applied with `StartRunLobby.SyncAscensionChange` (E0 §6 seam 2)
immediately before the run begins, and Act 1 is pinned with `StartRunLobby.Act1 = "overgrowth"` so
the two environments describe the same act for the same seed. `hello.run_start.provenance` reports
the pinned profile, the revealed-epoch count, the run count, the requested and observed lobby
ascension, and `StartedWithNeow`. The bridge does not verify the observed ascension itself; that is
the caller's assertion, and the differential treats a mismatch as a gate failure.

### Run lifecycle: one run start per process is a bridge constraint

The bridge starts the shipped autoplay driver once, when the main menu first appears, and that driver
exits the process when its run ends, so the current bridge serves exactly one run start per process.
That is an implementation constraint of this bridge, not a property of the shipped application: the
shipped driver itself abandons an in-progress run and starts another from the main menu,
`NGame.ReturnToMainMenu()` runs the complete shipped teardown (`RunManager.CleanUp()`, including the
`CombatManager.Reset(graceful)` that the reconstructed worker needs for the same reason), and
`NGame.StartNewSingleplayerRun` is the production run-start seam the reconstructed `neow_run_reset`
already models. The E5 differential therefore keeps one fresh process per entry as a conservative
measurement choice rather than a necessity. Measurements, the source evidence and the open decision are
recorded in [e5-differential-run-cost-and-process-reuse-report.md](e5-differential-run-cost-and-process-reuse-report.md).

### Nested-choice seam

`CardSelectCmd.Selector` is the single seam every nested card choice goes through (a Neow blessing
such as New Leaf, Pomander, Precise Scissors, Precarious Shears, Hefty Tablet or Lead Paperweight, a
relic's `AfterObtained`, or an in-combat discard choice). With `nested_choices` (default on) the
bridge wraps the selector AutoSlay installs and exposes the choice to the protocol as a
`card_choice` decision instead of letting it auto-pick. Bundle choices have no selector branch, so
`ChooseABundleScreenHandler` is patched and exposed as `option_choice`. Legal actions for both mirror
the reconstructed environment's shape (`choose_cards` / `choose_option` with `option_ids`), and
`observation.outstanding_choice` carries each option's semantic identity. Card *reward* selection
stays with the wrapped selector and the existing reward screens.

With `combat_complete` the combat loop additionally reports one terminal `combat_complete` boundary
after the action that leaves the encounter with no living enemy and the player alive, before the run
generates room rewards. That is the differential's unified endpoint; without the flag the run flows
straight into the reward screens as before.

### Reward-screen seam

Neow's blessings are relics (`Neow.PositiveOptions` / `Neow.CurseOptions` are all
`RelicOption<T>`), and several of them offer a reward set when obtained: `Kaleidoscope` offers two
`CardReward`s, `Neow's Bones` offers two `RelicReward`s and adds a curse, `SmallCapsule`/`LostCoffer`
offer capsule rewards. `RewardsCmd.OfferCustom` shows them on `NRewardsScreen`, which is *not*
terminal (no proceed button; the screen closes itself once every reward is taken).

Two properties of that screen are decisions, and the bridge projects both:

- **Proceed/skip is only legal while the shipped game enables it.** `NRewardsScreen` shows a
  skip-labelled `NProceedButton` for a custom reward set, but disables it when the set was offered
  with `RewardsSet.WithSkippingDisallowed()` (Neow's Bones needs both relics) or when the room cannot
  be left yet. The projection therefore emits `proceed` only when that button is enabled, and reports
  `room.details.proceed_enabled` / `proceed_is_skip` so the boundary is self-describing.
- **A card reward names its cards up front.** The shipped game needs two native steps for a
  `CardReward` (click the reward, then pick on `NCardRewardSelectionScreen`), while the reconstructed
  environment exposes the offered cards directly. The bridge fuses the pair into one coordinator
  action, `choose_reward:{reward}:Card:{option}:{CARD}`, whose `metadata.model_id` is the card — the
  same semantic claim the reconstructed side exposes. `step` records the claim and the card reward
  screen handler consumes it, pressing the matching holder instead of asking the caller again. The
  unfused form (`choose_reward:{reward}:Card` and then a `card_choice`) still works, so existing
  callers are unaffected. A *state-changing* card reward alternative (reroll, or a relic-granted
  sacrifice) is projected as its own `card_reward_alternative` action, which the differential refuses
  to map: it is a decision the reconstructed environment does not model and must fail loudly rather
  than be silently dropped. The plain `Skip` alternative only closes the sub-screen and leaves the
  reward claimable, so it is a coordinator step, not a decision.

---

## 5. Presentation Suppression

To maximize throughput and prevent headless Godot scene-graph null-pointer exceptions, the bridge applies presentation-only Harmony patches:
- `MegaCrit.Sts2.Core.Commands.VfxCmd.*`: Bypasses 2D combat visual effects and particles.
- `MegaCrit.Sts2.Core.Audio.Debug.NDebugAudioManager.*`: Bypasses audio clip playback and bus routing.
- `MegaCrit.Sts2.Core.Commands.SfxCmd.*`: Bypasses sound effect commands.
- `MegaCrit.Sts2.Core.Commands.ThinkCmd.*`: Bypasses speech bubble UI delays.
- `MegaCrit.Sts2.Core.Commands.CardPileCmd.*`: Bypasses card pile tween animations.
- `MegaCrit.Sts2.Core.Nodes.Screens.Map.NNormalMapPoint.SetAngle`: Bypasses 2D map node icon rotation.
- `MegaCrit.Sts2.Core.Commands.Builders.AttackCommand`: Clears custom visual VFX node generators while preserving 100% authentic damage calculations and history hooks.
- `NonInteractiveMode.AutoSlayerCheck = () => true`: Ensures game loop runs at maximum non-interactive compute speed.

---

## 6. Authority & Environment Hierarchy

The project defines three operational environments with strict authority boundaries:

| Environment | Binary / Host | Lifecycle Control | State Reconstruction | Authority | Usage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`full_application_native`** | Shipped `SlayTheSpire2.exe` | Shipped Engine Run Loop | **None (0%)** | **Primary Gold Authority** | Trajectory generation, policy evaluation, rollout verification |
| **`reconstructed_native`** | `Sts2.NativeSim.GodotHost` | In-process Direct Invocation | Synthetic Combat Reset | **Diagnostic / Accelerator** | Fast local unit tests, micro-benchmarks, state diffing |
| **`python_approximate`** | `sts2_headless_gym.py` | Python Script | Handcrafted Simulator | **Approximate (Legacy)** | Rapid prototyping only; frozen from production data |
