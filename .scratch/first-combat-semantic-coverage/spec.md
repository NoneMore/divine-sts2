# NoSL first-combat scenario coverage

Status: ready-for-agent

## Problem Statement

For a fixed character, Ascension and run seed, the first-combat generator currently resolves each offered Ancient choice through only one default path. It misses legal nested choices that can change the deck, relics, potions and combat state. Gathering more seeds alone wastes the variation already available within each seed. The user needs a reproducible collection of real first fights for NoSL combat AI training, with the character's own card pool covered before generation stops.

## Solution

Enumerate the legal, non-skip Ancient choice branches and their nested decisions for each scenario generation element, then capture the combat initial state before the player acts. Prune plainly equivalent card-selection actions before branching, while preserving a replayable recipe for every retained branch. Generate game-like random run seeds across successive fixed-seed corpora until every eligible character card model occurs in the run deck of at least one successful first-combat scenario. Train at A10; allow lower Ascensions as experiments. Report coverage and failures without claiming an exact count of globally unique NoSL scenarios. Validate representative new branches field by field against the shipped game.

## User Stories

1. As a combat AI practitioner, I want first-combat scenarios reachable from a stated character, Ascension and run seed, so that training starts from real runs.
2. As a combat AI practitioner, I want the combat initial state captured before my first action, so that each scenario is a usable episode start.
3. As a combat AI practitioner, I want all legal non-skip Ancient choices explored, so that one run seed yields more of its useful variation.
4. As a combat AI practitioner, I want every legal non-skip nested choice explored recursively, so that card bundles, reward picks, removals, transformations and upgrades can lead to their own scenarios.
5. As a combat AI practitioner, I want choices that lead to another prompt resolved through that prompt, so that compound Ancient effects are covered.
6. As a combat AI practitioner, I want both legal reward orders of `NeowsBones` explored initially, so that its ordered effects are not silently collapsed.
7. As a combat AI practitioner, I want no artificial per-seed scenario limit, so that a seed with many legal branches is not arbitrarily truncated.
8. As a combat AI practitioner, I want the retained choice indices and offered option identities recorded in order, so that I can reproduce each scenario in the shipped game.
9. As a combat AI practitioner, I want a deterministic representative for interchangeable copies of the same card in one prompt, so that choosing an equivalent instance does not multiply output.
10. As a combat AI practitioner, I want removal or transformation to prefer an ordinary copy when the same card model also has upgraded or enchanted copies, so that those prompts spend their branch budget on likely new content.
11. As a combat AI practitioner, I want different card models, counts, upgrades, enchantments and native card states retained as meaningful deck differences, so that the corpus does not erase training variation.
12. As a combat AI practitioner, I want held relic identities retained as meaningful differences even if a relic has no immediate combat effect, so that the state I train on reflects the run.
13. As a combat AI practitioner, I want potion identity and slots, monster composition, HP and visible intents retained as meaningful differences, so that distinct first fights remain available.
14. As a NoSL policy developer, I want opening hand, hidden draw or shuffle order, card instance identity and hidden RNG alone excluded from the diversity criterion, so that random hidden outcomes are not counted as new tasks.
15. As a NoSL policy developer, I want the full native combat initial state still recorded, including ordered piles and RNG state, so that a selected scenario replays exactly.
16. As a corpus user, I want rows from different run seeds retained even when their visible content matches, so that the provenance and natural seed frequency are preserved.
17. As a corpus user, I want generated rows allowed to contain some semantic duplicates, so that generation needs only the agreed selection-time pruning and remains auditable.
18. As a corpus user, I want the first row-one node chosen by the established deterministic rule, so that map coordinates alone do not expand the scenario set.
19. As a corpus user, I want a campaign that generates game-like random canonical seeds, so that the seed stream resembles ordinary play and can be replayed exactly.
20. As a corpus user, I want the seed sequence and fixed generation requests recorded, so that a coverage campaign can be resumed and audited.
21. As a corpus user, I want canonical-seed collisions handled explicitly, so that duplicate seeds do not silently distort coverage or row counts.
22. As a corpus user, I want coverage computed per character and Ascension from the successful scenarios' run decks, so that the stopping rule has a precise denominator and numerator.
23. As a corpus user, I want a character card model counted after its first appearance regardless of copy count or frequency, so that coverage measures reachability first.
24. As a corpus user, I want the eligible character pool derived from the active game build and fully unlocked single-player progression, so that game updates do not leave stale hard-coded card counts.
25. As a corpus user, I want multiplayer-only, Ancient and other-character cards excluded from character card coverage, so that the reported target matches the intended training pool.
26. As a corpus user, I want other-character cards still represented in scenario decks, so that legal cross-class Ancient rewards are not discarded.
27. As a corpus user, I want seed generation to continue until character card coverage reaches 100%, so that the campaign has a clear completion condition.
28. As a combat AI practitioner, I want A10 used for the training campaign and lower Ascensions available for experiments, so that experimental runs cannot be mistaken for the training distribution.
29. As a corpus user, I want relic, potion and monster coverage reported without hard completion thresholds, so that I can inspect them without blocking the card target.
30. As a corpus user, I want scenario row counts, failed branch counts and coverage by content type reported without an unsupported exact global semantic-uniqueness count, so that reports say only what the generator measures.
31. As a corpus user, I want a failure row for every failed opening branch with its recipe resolved so far, so that failures cannot silently bias coverage.
32. As a corpus user, I want fixed requests to remain resumable and byte-identical for a fixed game build and worker count, so that corpus regeneration remains trustworthy.
33. As a corpus user, I want the row set unchanged when worker count changes, so that parallelism cannot change which scenarios exist.
34. As a maintainer, I want every retained recipe to follow legal shipped-game choices under a progression-complete baseline, so that generated scenarios satisfy the project's parity contract.
35. As a maintainer, I want the full-app oracle to drive option picks as well as card-select prompts, so that nested reward branches can be checked against the shipped game.
36. As a maintainer, I want representative scenarios from every newly explored nested choice kind compared field by field with the shipped game, so that enumeration and replay defects are visible.
37. As a maintainer, I want a parity failure to name the differing field path, so that the cause can be investigated without comparing opaque hashes.

## Implementation Decisions

- **Reachability and scope.** A scenario generation element is one character, Ascension and canonical run seed. Drive the shipped game's Ancient-room and first-combat path in the simulator under the progression-complete baseline. Only offered, legal choices are eligible. Exclude skip actions from enumeration, including a top-level skip choice and skippable nested reward options. Capture the first combat before any player action; do not synthesize loadouts or encounters.
- **Branch traversal.** Expand all eligible Ancient choices and nested decisions recursively. A compound reward retains its legal order, including both `NeowsBones` orders at baseline. There is no fixed row cap per seed. Preserve deterministic traversal, row identity and recipe order. A failure on one branch yields a failure row and does not suppress sibling branches.
- **Pre-branch pruning.** In each card-select prompt, copies with the same model, upgrade level, enchantment and native state are interchangeable; explore one deterministic representative. For removal or transformation only, if ordinary and upgraded or enchanted copies of one model coexist, explore ordinary copies and omit the variants as targets. This latter rule deliberately sacrifices some reachable, semantically distinct outcomes. Do not merge different relic reward orders or run a semantic deduplication pass over completed rows.
- **NoSL diversity.** Count a difference in deck contents, card variants, held relics, potions or visible combat state as a scenario difference. A relic's identity counts even if its effect is dormant. Opening hand and hidden draw/shuffle order alone do not count; neither do card instance IDs, map coordinate or hidden RNG alone. Preserve the complete native combat initial state in each success row for replay and parity. Retain output rows from distinct seeds even if visible content coincides. Reports must distinguish generated rows from measured coverage; they must not label row count as an exact count of globally unique NoSL scenarios.
- **Map and recipe.** Continue selecting the first legal row-one map action in the environment's order. Record its coordinate, the encounter and the ordered Ancient and nested selections. The recipe must support materializing the same branch and human replay in the shipped game. The act variant remains seed-derived.
- **Coverage target.** For each character and Ascension, the denominator is the active build's fully unlocked, single-player pool of that character's card models, excluding Ancient and multiplayer-only cards. A model is covered when it appears at least once in a successful scenario's run deck. Count each model once. Do not count other-character cards in either coverage statistics or the stopping rule, though they remain in rows. The training campaign is A10; lower Ascensions are experimental and tracked separately. Character card coverage of 100% ends the campaign. Relic, potion and monster coverage are descriptive counts with no minimum. Frequency balancing is deferred.
- **Seed campaign.** Draw seeds with the shipped game's random-seed convention, canonicalize them and retain the exact accepted sequence. Reject or redraw canonical collisions before assigning a new scenario generation element. Orchestrate generation through immutable finite-seed requests so the existing corpus can resume and retain its fixed-request guarantees. Persist enough campaign progress and coverage counts to resume without changing an accepted seed or reinterpreting completed rows. Stop scheduling seeds when the character card target is reached; a batch already in flight may finish. Any such excess seeds remain recorded.
- **Artifact contract.** Keep deterministic row and shard ordering, failure rows and the corpus summary. For a fixed request, build and worker count, all corpus-owned bytes remain identical on rerun. Across worker counts, the row set remains identical. Corpus artifacts contain counts and identities, not wall-clock times or floating-point values. Report coverage from successful rows; failures do not cover cards.
- **Oracle.** Extend the existing full-app interaction seam to choose options in bundle and relic prompts, while reusing its card-select handling. Compare representative retained branches against the shipped game using the established field-by-field parity contract. Choice legality and offering are part of parity; the enumerator is free to pick any legal non-skip choice. Do not substitute simulator-only consistency for shipped-game evidence.
- **Performance policy.** Keep full `NeowsBones` enumeration unless measured branch frequency or cost is excessive. Only after such measurement, a follow-up may restrict its two rewards to removal/transformation before addition when both orderings are legal. Such a restriction must remain explicit because it loses reachable scenarios; no silent generic branch cap is permitted.

## Testing Decisions

- Test behavior at the public scenario-generation and corpus interfaces. Assert on emitted rows, recipes, failure rows, coverage and artifact bytes, not private traversal helpers. The existing offline scenario tests provide the pattern.
- Use fixed seeds whose offered Ancient choices exercise each nested choice kind: card selection, upgrade, removal, transformation, card bundles, relic and potion rewards, chained selections and `NeowsBones`. Check that every retained branch is legal, ordered and materializable, while skip options are absent.
- Test selection-time pruning with duplicate ordinary copies, distinct card models, distinct upgrades or enchantments, and mixed ordinary/variant copies. Verify a deterministic representative and the agreed removal/transformation preference. Check that rows from distinct seeds remain even when their visible content matches.
- Test coverage through successful public output: single appearance counts once, duplicates do not increase the numerator, other-character, Ancient and multiplayer-only cards never enter the character-card statistic, and failures do not count. Check that the eligible denominator comes from the active build. The current build has 83 eligible Ironclad models and 84 for each other playable character; these are evidence for the present build, not constants to encode.
- Test a seed campaign's observable resume behavior: accepted seed sequence, canonical collisions, incremental coverage, target completion and any finished in-flight batch are reproducible. Test A10 training and lower-Ascension experimental results independently.
- Test a fixed request twice on the same build and worker count for byte-identical corpus artifacts, including summaries and compressed shards. Check that a different worker count gives the same row set. The existing corpus determinism tests are prior art.
- Use the shipped game through the existing full-app bridge as the acceptance oracle. First close its option-pick gap. Then take a bounded sample covering each newly explored nested choice kind and representative `NeowsBones` orderings, across characters and Ascensions as appropriate. Compare the established combat initial-state contract field by field, with field paths on mismatch. The existing scenario-record and Ancient-choice acceptance runs are prior art. A full-app run for every corpus row is not required.
- Preserve parity for the existing first-combat sample as a regression gate. The sample must state which choice kinds it actually covers; a passing subset cannot be reported as complete nested-choice parity.

## Out of Scope

- Synthetic decks, relics, potions, monsters, Act variants or unreachable first-combat states.
- Combat turns after the initial state, policy behavior and save/load probing of hidden outcomes.
- Skip actions, alternate row-one nodes selected only for their map coordinate, and later acts.
- Post-generation semantic deduplication or an exact global unique-scenario count.
- Card frequency balancing and minimum relic, potion or monster coverage targets.
- Coverage statistics for other-character cards, Ancient cards or multiplayer-only cards.
- A10-versus-low-Ascension training comparison; lower Ascensions serve experiments only.
- A fixed per-seed branch cap or proactive `NeowsBones` order restriction without measured need.
- Shipped-game validation of every emitted row.

## Further Notes

- This spec supersedes the previous one-row-per-offered-Ancient-choice and default-nested-choice cardinality in the implemented first-combat spec. It preserves that spec's reachability, record, replay, determinism and parity contracts, together with ADR-0003 and ADR-0008. ADR-0009 records the revised branch policy.
- Source inspection found that fully unlocked `NeowsBones` can pair addition and removal/transformation relic effects. That interaction can expand a seed sharply, but the anticipated frequency is low enough to enumerate first and measure before changing the policy.
- The existing full-app bridge can drive card-select prompts but cannot yet drive option picks opened by bundles or relic rewards. That gap must be closed for the stated acceptance sample.
- The current eligible-card counts are build-specific. An updated game build can change the denominator, offered choices and parity evidence; each corpus and campaign must identify its build.
