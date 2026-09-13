# Persistent native environment — verification evidence

**Role.** Dated verification evidence, fault-injection results, and measured performance for the environment specified in [persistent-environment.md](persistent-environment.md). The contract document owns behaviour and interfaces; this document owns what was observed, when, and against which build.

**Provenance rule.** Every result below was produced on the build pinned in [version-compatibility.md](version-compatibility.md). A result is evidence for the transitions it actually observed and nothing more: it never establishes global simulator certification, policy quality, or another axis of project capability. See the claims discipline in [project-status-and-review-guide.md](project-status-and-review-guide.md).

**Freshness caveat.** Sections that do not carry an explicit date are snapshots recorded before this document was split out of the contract document. Treat their numbers as recorded evidence, not as a current measurement, and re-run the named gate before relying on them.

## Gate index

| Script | What it gates |
| :--- | :--- |
| `python/acceptance.py` | persistent replay baseline; run-only/combat-only construction boundary |
| `python/choice_acceptance.py` | blocking native card choices |
| `python/option_choice_acceptance.py` | shipped bundle/relic ABI boundaries |
| `python/run_option_reward_acceptance.py` | recorded Scroll Boxes reward selection; local and cross-worker portable pending-handle replay |
| `python/run_map_acceptance.py` | map graph, routing, and restore |
| `python/run_reward_acceptance.py`, `python/run_item_reward_acceptance.py` | card and item reward coordinators |
| `python/run_rest_acceptance.py` | rest-site options and effects |
| `python/run_event_acceptance.py` | event options and effects |
| `python/run_room_entry_acceptance.py`, `python/run_room_cycle_acceptance.py` | composed room entry and the two-room cycle |
| `python/run_composed_utility_rooms_acceptance.py` | merchant, shop removal, rest, treasure, exits on a generated path |
| `python/portable_modes_acceptance.py` | all eight reset modes end to end; portable-restore fail-closed rules |
| `python/combat_breadth_acceptance.py` | upgrades, enchantments, saved mutable card/relic state, RNG counters, potions, multi-enemy targeting, death/removal, terminal victory, fork, restore |
| `python/neow_run_acceptance.py` | run-start (E3) gate |
| `python/first_combat_root_acceptance.py` | first-combat root (E4) gate |
| `python/first_combat_differential_acceptance.py` | first-combat golden differential against the shipped application (E5 authority gate) |
| `python/search_coordinator_acceptance.py` | multi-ply native beam expansion and dedup |
| `python/differential_campaign.py` | exact shipped-game differential aggregation |

`tests/test_portable_branches.py`, `tests/test_first_combat.py` and `tests/test_first_combat_differential.py` cover the same validation, enumeration and comparison rules offline, without a game process or the pinned build, so schema, build, provenance, mode rejection, branch scheduling, failure reasons, caps, ordering, canonical byte stability, action-key translation, wrapper normalization and divergence reporting stay covered in a plain test run.

## Construction boundary (run-only vs combat-only)

`python/acceptance.py` and `python/portable_modes_acceptance.py` assert the run-only/combat-only construction boundary. On the pinned build the run-only phase reports no combat-state transition, no player combat state, and zero counters for all eight combat RNG streams (`Shuffle`, `MonsterAi`, `CombatCardGeneration`, `CombatPotionGeneration`, `CombatCardSelection`, `CombatEnergyCosts`, `CombatTargets`, `CombatOrbs`); the combat phase then installs the `CombatState`, populates the player combat state, and consumes `Shuffle` (9 for the 10-card acceptance deck, 10 for the A10 native starting loadout, which also proves the native starter deck plus one `ASCENDERS_BANE`). Four workers agree on the audit and a repeat construction on one worker reproduces it exactly.

Two temporary fault injections showed the assertions discriminate rather than merely mirror the implementation:

- moving combat construction inside the run-only phase reported `run_phase_created_combat_state: true` with `Shuffle: 9` at the boundary;
- a single run-phase `Shuffle` draw reported `run-only construction consumed combat RNG: {'Shuffle': 1}`.

Both injections were fully reverted, and the second left both `CombatState` assertions passing, which shows the RNG assertion holds independently.

The eight reset modes divide by provenance. The seven combat-owning modes (`combat`, `map`, `card_reward`, `item_reward`, `custom_reward`, `rest`, `event`) still construct the run and then their own combat, and report the audit above. `run_reset` reports the run phase alone: `combat_phase_constructed: false`, no combat-state transition, no player combat state, and zero counters for all eight combat RNG streams.

A third fault injection routed `ResetMode.Run` through combat construction and the run-mode assertions failed as intended, reporting `combat_phase_constructed: true` with `Shuffle: 9` for the reset and `synthetic_combat_installed: true` with `Shuffle: 9`/`Niche: 1` for the restore, against `false`/`false`/zero on the pinned behaviour; the injection was fully reverted.

## Reset-mode coverage and portable-restore fail-closed rules

`python/portable_modes_acceptance.py` covers all eight modes end to end: each reset is followed by a real step, a portable export, and a cross-worker restore that must reproduce the exact hash, observation, and legal actions, and each branch's recorded provenance must equal the mode its reset method names. The matrix also covers the shipped ranged `GoldReward` constructor and native gold selection.

Portable restore is fail-closed on the record itself. The acceptance tampers with a valid branch in turn — provenance, reset method, an unknown method, assembly SHA-256, schema version, action history, and expected hash — and requires `reset_provenance_mismatch`, `unknown_reset_mode`, `build_mismatch`, `unsupported_portable_branch_schema`, and `replay_divergence` respectively; validation happens before any reset RPC reaches the target worker. A schema-less copy of both a combat branch and a composed-run map branch still restores exactly through the version-0 compatibility path.

Local restore covers the same three stages as cross-worker portable restore: a composed-run map handle and a run-combat handle both reconstruct through the run-only path (`last_restore.path == "replay"`, `synthetic_combat_installed: false`, `player_has_combat_state: false`, zero combat RNG), and a standalone `event_reset` branch that suspends on Brain Leech's five-card nested choice restores exactly before and after the choice.

## Regression comparison across the E1/E2 refactor

A sweep of sixteen acceptance scripts before and after the E2 change produced identical exit codes and identical hash sets for every script that does not observe a composed run: the direct-combat, choice, bundle, card-reward, item-reward, reward-option, rest, event, and map-reset acceptances are bit-identical, including the direct reset hash `CEE9B22A0D5E3FC2B3A0C66E2C5E694E54540059B9C27E9EEA77F3D840DBEF7B`.

The composed-run scripts (`run_room_cycle`, `run_composed_utility_rooms`) keep every content, route, reward, and event assertion and change only hashes, because run-mode observations include the RNG counter map the synthetic combat used to advance.

A direct differential of `run_reset` observations for a custom 10-card deck and the A10 native starting loadout found zero non-RNG differences in the map observation — the map, its points, and its legal actions are identical — and differences confined to the first real combat's shuffle order and monster HP, exactly the two consumed streams.

Three scripts carry recorded expectations rather than silently adjusted ones:

- `python/run_event_combat_acceptance.py` (the route's Unknown node no longer rolls `DENSE_VEGETATION`) and `python/run_custom_reward_acceptance.py` (a later reset evicts the pre-reset `ordinary_handle`, because handles stay content-addressed per construction and are not preserved across resets) already failed on the pinned build before E1 and still fail in the same place with the same reason. Their stale expectations remain recorded here rather than silently adjusted.
- `python/run_room_entry_acceptance.py` previously failed because it hardcoded a `NIBBIT` encounter for seed `NATIVE-COMPOSED-ROOM-ENTRY`; the shipped build rolls `TWIG_SLIME_S`/`LEAF_SLIME_M`/`LEAF_SLIME_S` for it, so E2 replaced that stale model id with four-worker agreement, a real-enemy check, deck conservation, and instance-id set equality, and the script now passes.

## Run-start (E3) gate

`python/neow_run_acceptance.py` is the E3 gate. On four workers and the pinned build it covers twelve run-start fixtures: Ironclad at A0 offering Large Capsule, Phial Holster, Small Capsule, New Leaf, Leafy Poultice, Precise Scissors, Scroll Boxes, Neow's Bones, and Lost Coffer, Defect offering Winged Boots, Silent offering Lost Coffer, and Ironclad at A10 offering Scroll Boxes. Each fixture is asserted to actually offer its named blessing, so a build whose Neow roll changes fails loudly instead of silently testing something else.

- **Determinism.** For every fixture the four workers return an identical Neow decision — same state hash, same `choose_event` actions with their shipped `text_key` identity, and identical `event`, `run_start`, and run-inventory blocks.
- **Slice.** Every fixture reaches `combat.turn == 1 && phase == Play` with combat legal actions, with identical root hash, observation, legal actions, and ordered decision trace on all four workers, and within each worker the `diagnostics.run_identity` snapshot taken at the Neow decision equals the one taken at the root, which is the object-continuity evidence for the run-start seam.
- **Ascension.** The A10 fixture reports exactly one `ASCENDERS_BANE` in the starting deck and the A0 fixtures none; the twelve A0/A10 fixtures all report zero counters for every combat RNG stream at the decision, and their run-start construction audit reports `combat_phase_constructed: false` with no combat state and no combat RNG.
- **Fork isolation.** A handle taken at the Neow decision forks cleanly. Restoring it after another branch has been advanced reproduces the hash, observation, and legal actions byte-identically through the `replay` path — not a resident-prefix hit — with `synthetic_combat_installed: false`, `player_has_combat_state: false`, and zero combat RNG; a branch then advanced on that contaminated worker matches the same branch advanced on a worker that never saw the other branch, and the decision's run RNG counters are unchanged.
- **Replay.** Moving the resident state off a run-start root and restoring the root rebuilds it with a positive replayed-action count, and the exported branch (`provenance: neow_run`, reset request carrying exactly the four start fields) restores on a different worker to the same hash, observation, and legal actions.
- **Fail-closed.** A tampered assembly hash, a tampered version, `ascension: 11`, and an empty seed are rejected as `build_mismatch`/`invalid_reset` without disturbing the resident run; an unknown character is rejected during construction as `unknown_model` and the worker recovers on the next valid run start. A record carrying forged `deck`, `relics`, `potions`, `current_hp`, `max_hp`, `gold`, `rng_counters`, `initial_hand`, `enemies`, and `use_character_starting_loadout` fields produces a decision byte-identical to the plain record, so the wire record cannot express a forged post-Neow state.

Two temporary fault injections showed the run-start assertions discriminate rather than mirror the implementation. Building the Neow mode from the synthetic empty unlock profile reported `neow_unavailable: The pinned unlock profile did not set ExtraRunFields.StartedWithNeow, so this run start would silently skip Neow and force the starting point to Monster.` Resolving `MapPointType.Ancient` through a renamed member reported `unsupported_build_contract: Pinned MapPointType has no member 'AncientRenamed'.` Both injections were fully reverted.

Two boundaries are recorded rather than claimed. The suspendable map-entry combat start is evidenced by a branch that previously hung silently — Neow's Bones granting Large Capsule, which pulls Gambling Chip, whose turn-start discard selection suspended the combat start until the client timed out with no protocol error — and that now exposes a `card_choice` at `phase == Start` and reaches turn 1 / Play once the choice is resolved. And on the pinned Act 1 sample the starting Ancient point connects to every row-1 node, so `MapTravel.GetTravelablePointsFrom` and the point's `Children` return the same set: the implementation uses the shipped travel seam the map screen uses, but this sample cannot distinguish it from children enumeration, and Winged Boots' free travel is therefore not observable at the starting Ancient point.

## First-combat root (E4) gate

`python/first_combat_root_acceptance.py` is the E4 root gate. On four workers and the pinned build it enumerates nine run starts — the plan's seven high-risk blessings (Large Capsule, Phial Holster, Small Capsule, New Leaf, Leafy Poultice, Scroll Boxes, Neow's Bones), the Ironclad A10 Scroll Boxes fixture, and one Defect breadth case — producing 656 roots from 882 decision-node expansions: 15, 9, 8, 36, 108, 16, 340, 16, and 108 respectively. Each fixture is listed twice through the pool, in two rotations that place the same fixture on two different workers, and the two enumerations must agree on every branch identity, root hash, action trace, and canonical uncompressed record byte; the first fixture is additionally enumerated twice on the same worker with the same result.

Every recorded root is at `combat.turn == 1 && combat.phase == Play` with `play_card` and `end_turn` legal actions, all eight combat RNG streams present in the run counter map, the full build identity, a first-floor `Monster` route with its enemies, and a portable branch whose provenance is `neow_run`, whose history equals the recorded trace, whose expected hash equals the root hash, and whose reset request carries exactly the four run-start fields.

Nothing is deduplicated on surface state: the fixtures record 656 branches but only 5/3/4/12/27/4/68/4/27 distinct root hashes, so routes that converge on the same combat state remain separate records.

Same-worker replay, local fork restore, and cross-worker portable restore were each exercised on four sampled roots per fixture (36 roots in total) and reproduced the recorded hash, observation, and legal actions exactly. The restore evidence is the worker's own audit — `path: "replay"` with `replayed_actions` equal to the trace length (3–6) and `synthetic_combat_installed: false` — not a resident-prefix hit, since the helper moves the worker off the root before restoring and refuses a move that did not change the state.

The caps fail closed: `max_actions_per_branch=1` and `max_roots=2` both mark the seed incomplete with `action_cap`/`root_cap` failures and `assert_complete()` raises, while every root the capped walk does emit is still a real boundary state; the gate also rejects the Neow decision state as a root, and a root branch whose `expected_hash` is tampered fails as `replay_divergence`, poisoning only the worker that attempted it; the pool replaces that worker and the untampered recipe restores on it, so the tamper is the only cause.

The root record is a replay recipe, not a native memory snapshot: restoring it currently replays the Neow prefix and cannot be described as keyframe or low-cost restore. This gate says nothing about mechanical fidelity against `full_application_native` (E5's differential) and nothing about policy quality.

## Exact shipped-game differential evidence

### First-combat golden differential (E5, 2026-09-13)

`python/first_combat_differential_acceptance.py` replays one frozen manifest on the reconstructed
environment (`reconstructed_native`) and on the shipped application (`full_application_native`,
`SlayTheSpire2.exe --headless --force-steam=off` plus the Harmony bridge), one sandboxed game process
per entry because the shipped game serves exactly one run start per process. Both sides follow the same
recorded branch or, where a branch is not recorded, the same deterministic smallest-semantic-key
policy. Every boundary compares the semantic legal-action sets and the schema-aligned state projection
(build, run RNG counters, deck and combat piles with upgrades and native state, relics, potions,
encounter, creatures, intents, powers, resources, native `combat.turn` and `PlayerCombatState.Phase`).
Each entry settles where it says it settles: `stop=root` ends at the first-combat root after both
environments prove `combat.turn == 1 && combat.phase == Play` (including the shipped side's declared ==
observed encounter), and `stop=endpoint` continues from that same asserted root to the unified endpoint —
player death, or the encounter cleared before `generate_room_rewards`. Every entry reports the action
kinds it actually took, and the aggregate reports `stops`, `compared_roots` and `decision_kind_counts`.

> **Correction (2026-09-13, evidenced in [e5-differential-run-cost-and-process-reuse-report.md](e5-differential-run-cost-and-process-reuse-report.md)).**
> The sentence above ("one sandboxed game process per entry because the shipped game serves exactly one
> run start per process") states a constraint of the current bridge, not of the shipped application:
> the bridge starts the shipped autoplay driver once and that driver exits the process when its run
> ends, while the game itself tears a run down (`NGame.ReturnToMainMenu()` → `RunManager.CleanUp()`) and
> starts another through `NGame.StartNewSingleplayerRun` — the seam the reconstructed `neow_run_reset`
> already models. The recorded per-entry fresh-process measurement is unchanged and remains the
> conservative choice; only the stated reason is corrected.

The decision policy is fixed and symmetric, not the shipped application's own preference: the recorded
trace where one is supplied, otherwise the lexicographically smallest semantic action key with
coordinator wrappers excluded. In combat that policy selects `end_turn` whenever it is legal, so the
trajectories compare root boundary, per-boundary legality/projection and endpoint classification but do
**not** execute card or potion effects on the shipped side; that axis belongs to
`differential_campaign.py` (49/49 traces) and to the optional E7 work.

Targeted manifest on the pinned build (`python scripts/run-e5-differential.ps1 -Mode targeted`), thirteen
fixtures — the seven high-risk blessings, an Ironclad A10 case, and one further run start per character —
sampled three roots each: **39/39 match, 0 error, 0 mismatch, 0 cap**, 504 compared boundaries and 355
compared combat steps in 516.9 s at two workers, every endpoint `player_death`. The report pins
`assembly_sha256 A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`,
`pck_sha256 42520EB8B0911C6C0F0BD102D92B33F41ABD4D26B83489817D0A6DBD7DD48587`,
`version 0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314`, and lists `discard_potion` as the single
unsupported action kind: the reconstructed environment exposes a potion discard in the turn decision
surface and the bridge does not, so the comparator reports it instead of silently dropping it. No
compared trajectory took that action. **This 39/39 run predates the root-comparison fix recorded below**:
it was produced by a comparator whose `trajectory=False` path settled at the first non-wrapper boundary
and whose trajectory path never asserted the root boundary, so it must not be cited as the E5 authority
result until the manifests are re-run.

The breadth manifest is frozen at 100 distinct seeds, each pinning one (character, ascension) cell so the
ten cells hold ten seeds each; ten entries (one per cell) run `stop=endpoint` for the plan's
"one step-by-step replay per character/ascension cell" requirement, and the remaining 90 run `stop=root`,
which drives the shared policy to the first-combat root and proves the boundary there. Run it with
`python scripts/run-e5-differential.ps1 -Mode breadth`; the report lands in
`artifacts/e5-differential/breadth.json`. Until that report exists on the fixed comparator, the breadth
half of the E5 authority gate is unproven, and any report already on disk was produced by the pre-fix
comparator and is superseded.

### Root-comparison defect in the E5 comparator (found and fixed 2026-09-13)

`run_entry` returned at the first non-wrapper boundary whenever `trajectory=False`. For a fresh run start
that boundary is the **Neow event decision**, so the 90 breadth entries that were supposed to compare a
first-combat root compared only the three Neow options: both sides took zero steps, `combat.turn` was
`None`, and the result was still reported as a match. The breadth description above, and E5's own
requirement that a root comparison explicitly prove `turn == 1 && phase == Play`, were therefore not met
by the code, and the frozen 100-seed breadth manifest could not have closed the gate as written. Two
further consequences of the same driver were measured rather than assumed: the recorded traces produced
by `FirstCombatEnumerator.expand` stop at the root (the enumerator returns there and never steps inside
combat), and the smallest-semantic-key policy picks `end_turn` over any `play_card`, so every compared
combat trajectory consisted of `end_turn` decisions only — the targeted run's 355 combat steps are 355
`end_turn`s.

The fix renames the mode to `run_entry(..., stop="root" | "endpoint")`. Reaching the root is now proven
with `assert_root_boundary` on **both** environments (`stop="root"` settles there, `stop="endpoint"`
records `root_status` and continues), an unknown `stop` fails loudly, an unreachable root fails at the
`budget` stage instead of reporting a match, and each record carries `stop` and `decision_kinds` so a
report states what was executed. Offline tests
(`tests/test_first_combat_differential.py`: root-stop settling, shipped-side root proof, unreachable
root, endpoint root proof, `end_turn` policy pinning, schema/stops declaration) pass, together with the
full suite and `scripts/test-public-tree.ps1`. Game-dependent verification is partial and outstanding:
a 13-entry breadth smoke (ten endpoint cells plus the first three root entries) and a 2-entry endpoint
smoke with the root assertion both matched, but neither frozen manifest has been re-run on the fixed
comparator, so no breadth report exists and the E5 authority gate remains open.

Three projection defects were found and fixed while building this gate, all of them on the shipped side
and all strictly read-only (`docs/full-application-control-bridge.md`): a nested card choice opened by a
Neow relic during combat start dropped the live combat projection; the `NRewardsScreen` skip button that
`RewardsSet.WithSkippingDisallowed()` disables (Neow's Bones) was advertised as a legal `proceed`; and a
`CardReward`'s offered cards needed a fused `choose_reward:{reward}:Card:{option}:{CARD}` action to line
up with the reconstructed environment's claims. The rejected alternative — matching the reconstructed
side's fused claims against the shipped side's opaque reward screen — was discarded because it would have
required the comparator to compare across two different decision granularities.

Local-invariant and independent-worker validation is supplemented by exact shipped-game differential traces. The original manual `NIBBITS_WEAK` trace matched reset, nine native card plays, three complete turns, and terminal victory across 13 checkpoints, with final hash `1FEA2F670B6BE0064F0510C2402B823BA5010F7FC322F38BDAC74B3153A327CA`; this exact replay still passes after the room-lifecycle correction. The strict replay comparator and the opt-in read-only shipped-game exporter are implemented; the system remains non-certifying outside those checkpoints.

Isolated AutoTrace now generates additional candidate combats without manipulating the visible game. Candidates become certifying evidence only after strict replay succeeds.

`python/differential_campaign.py` discovers both standard trace locations, pins every input by SHA-256, requires exact replay, and emits `artifacts/differential-campaign-report.json` plus the exact build-keyed `artifacts/differential-coverage-inventory.json`. As of 2026-08-23, the pinned campaign passes 49/49 traces and 904 exact checkpoints, including 41 terminal victories. It covers all five characters and 14 encounters across hallway, elite, and boss tiers. The artifact exactly enumerates actions, observed/played cards, enemies, moves, intents, both-side powers/debuffs, relics, potions, energy/stars/orbs, and terminal outcomes. Its aggregate deliberately sets `global_certification` to false: only those checkpoints and mechanics are certified.

The reset protocol's `invoke_combat_entry_hooks` capability is exercised by exporter traces; four independent workers reproduce Gorget's native 4 Plating result with state hash `8EAD712CCB8FC1939106E85DEB12AB84153230A2C2C9110B83C01D50C32978C8`.

The automated differential-breadth gate has advanced but has not fully passed: the campaign is at 14 of the target 40+ encounters, although all five characters and hallway/elite/boss tiers are now exact. Bounded unique-path choice replay, Cracked Core turn-start lifecycle, exact Defect orb snapshots/RNG, generated-card identity, and Cubex post-start block reconstruction are verified. Remaining legacy pre-hook/pre-block candidates stay quarantined. V9 schema and corpus work remains a later milestone; Transformer training has not begun.

Trace-format, exporter, and launcher contracts are owned by [differential-trace-format.md](differential-trace-format.md), [trace-exporter.md](trace-exporter.md), and [isolated-autotrace.md](isolated-autotrace.md). The trace-exporter document previously recorded an eight-complete-victory-trace / 177-checkpoint snapshot for the same campaign; the 49/49-trace figure above is the later aggregate and supersedes it.

## Recorded execution breadth

Undated snapshot, recorded before this document was split from the contract document.

The environment supports bounded search across composed native map paths containing combat, room rewards, events, rest sites, merchants, treasures, and nested event-created combats, in addition to isolated native coordinator experiments. The utility-room acceptance follows a real generated nine-floor path and exercises merchant card purchase, blocking shop card removal, rest-site selection, treasure gold/relic award, room exits, and deep restore across four workers. A second real map path exercises Dense Vegetation's shipped rest continuation, nested encounter, combat/rewards, and return to the map.

Automated corpora catalog 578 card models, 80 encounters, and 57 events. In deterministic baselines, all 518 runtime-playable cards executed without error, every encounter completed a full enemy/start-turn cycle, and 41 currently eligible events initialized without adapter errors. An automated catalog census initialized 41 of 57 shipped events in the baseline state; the other 16 rejected themselves through native eligibility rather than adapter errors. This is broad native execution coverage, not differential certification.

The portable-mode matrix takes one native action after each of eight reset modes — combat, composed run, map, card reward, item reward, custom reward, rest, and event — then exports and reconstructs the branch on another worker with an exact hash gate.

The seeded full-Act corpus completes sixteen distinct generated Act 1 routes through floor 16 and the native boss. It exercises 2,994 native decisions across combat, events, blocking card choices, custom rewards, shops, rests, treasures, elites, and bosses. A 196-decision route repeated in four independent workers produced the identical final hash `068A5B8B4A6C416313314AFB7CFDAE5D84C2C43A5585466D2E00B60E9F24F8C2`.

Run-level coordinator acceptances recorded the following four-worker agreements:

- map: an identical 56-point map, an identical 16-coordinate route, and the final hash reproduced after a depth-four restore;
- rewards: identical card, Candelabra, and Swift Potion outcomes with exact pre/post restore, plus an independently replayed pending choice caused by a predetermined Scroll Boxes reward — recorded as an ordinary `choose_reward` action and restored through action replay on four workers, with identical resumed hashes and a distinct alternate-bundle hash; real event acceptances cover a single potion reward and Trial's two sequential card rewards; an isolated native reward scenario covers `LinkedRewardSet`, blocking `CardRemovalReward`, linked-alternative skipping, and alternate potion selection, with exact deep replay across all stages;
- rest: agreement on options and effects, with selected states restoring exactly;
- events: a `THIS_OR_THAT` acceptance applied native damage and gold effects exactly;
- composed run: agreement at every checkpoint, from the shipped encounter roll through a full turn, native room-end gold/card rewards, the return to the child map choices, and a Brain Leech Unknown node that suspends on its five-card Share Knowledge choice, mutates the deck, exits `EventRoom`, and returns to the map with two visited nodes; deep reconstruction of reward-stage and event-choice handles is exact.

## Measured performance

Corrected measurements on 2026-08-22 include the JSON protocol and complete observations:

- resident native `PlayCardAction` plus observation: 2.47 ms mean;
- resident complete end-turn/enemy-turn/start-turn plus observation: 4.46 ms mean;
- reset: 24.54 ms mean;
- non-resident restore at depth 0: 24.25 ms;
- restore after one card play: 25.64 ms;
- restore after card play plus complete turn: 25.14 ms;
- full search-style fork/play/restore/end-turn sequence: 15.54 ms;
- small-payload protocol round trip: 0.085 ms; full observation round trip: 0.603 ms.

The previous 493.5 ms depth-2 result was presentation delay, not native mechanic cost. The native noninteractive switch removed it.

A short three-cycle scaling run measured the reconstruction-heavy `restore -> PlayCardAction -> observe` boundary at 24.1, 30.4, 62.1, and 101.7 aggregate transitions/second for 1, 2, 4, and 8 workers. These are search-boundary figures, not resident native-step throughput. All hashes agreed.

The full-Act search benchmark uses a deterministic 196-action route and reports action composition at each checkpoint. With three samples per checkpoint, non-resident reconstruction/replay plus observation measured 187.39 ms at depth 0, 191.23 ms at depth 16, 322.65 ms at depth 64, 515.52 ms at depth 128, and 718.10 ms at depth 195. At the same checkpoints, the resident native transition plus observation measured 10.59, 3.76, 3.65, 3.37, and 1.75 ms respectively. Complete `fork -> resident step -> non-resident restore` search cycles measured 211.56, 177.22, 304.31, 582.41, and 746.71 ms. These reconstruction-heavy figures are not described as native step throughput. Protocol round trips measured 0.068 ms for diagnostics and 0.478 ms for a complete observation. Twenty sustained depth-64 search cycles held branch metadata well within the 8192-entry cap and grew working set by 5.0 MB.

Fresh workers can report roughly 2.1 GB working set. In the post-composition sustained stress test, 1,000 observations left durable branch count unchanged at one. After 50 warm-up resets followed by 300 unique resets and 300 native steps, branch metadata remained well within the 8192-entry cap and post-warmup working-set growth was 26.5 MB, below the 256 MB retention gate. Handles are content-addressed, deduplicated by branch_identity (reset_request + action history + expected_hash), and evicted FIFO at the fixed cap.

## Worker lifecycle audit

A worker start/hello/close audit exited zero with no surviving process and no new Windows crash event.

## Related evidence owned elsewhere

- Critic and value-model experiment records, including rejected and demoted candidates, are in [native-rollout-farm.md](native-rollout-farm.md).
- The `full_application_native` milestone verdict and its historical benchmarks are in [full-application-control-bridge.md](full-application-control-bridge.md).
- The headless-Godot feasibility results that selected this architecture are in [phase-1b-headless-godot-report.md](phase-1b-headless-godot-report.md), with the plain-console negative result in [phase-1-feasibility-report.md](phase-1-feasibility-report.md).
