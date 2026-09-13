# Shipped-DLL rollout farm

**Role.** Canonical home for the shipped-DLL rollout farm, its compile/train pipeline, the native critic and value-model experiment record (including rejected and demoted candidates), and the promotion gates that guard model promotion.

**Scope boundary.** Environment behaviour and reset/branch contracts live in [persistent-environment.md](persistent-environment.md); dated environment measurements live in [persistent-environment-evidence.md](persistent-environment-evidence.md); policy-quality status and the active milestone order live in [project-status-and-review-guide.md](project-status-and-review-guide.md) and [holistic-solver-roadmap.md](holistic-solver-roadmap.md).

## Current capability

`native_rollout_farm.py` runs complete seeded runs in persistent headless Godot
workers. Each worker loads the shipped `sts2.dll` once and is reused across a
dynamic episode queue. Run setup, maps, encounters, rewards, relics, events,
shops, campfires, act transitions, the A10 second boss, and the Architect terminal
event execute through shipped game models. Presentation, audio, save writes, and
UI waits are suppressed at explicit headless seams.

This is not the old handwritten approximate simulator. Output records declare
`mechanics_source: shipped_sts2_dll` and include the installed game build hashes.

Measured on 2026-08-23 with six workers and 100 A1 episodes:

- 4,955 total episodes/hour including a 17-second cold start
- 210.9 native decisions/second
- 98 terminal episodes and two presentation failures; both exact failing seeds
  were subsequently fixed and replayed successfully
- a separate post-fix 50-episode soak completed 50/50 with no errors, caps, or
  worker restarts at 3,758 episodes/hour including a 23-second cold start
- running workers can consume about 2.1 GB each during trajectory capture, so
  available RAM—not a single-threaded scheduler—is the present scale limit

These numbers establish thousands of runs/hour on this machine. They do not
establish good play. The promoted policy still usually dies in Act 1; simulator
capacity and policy strength are separate acceptance gates.

A subsequent full 1,000-episode trajectory capture completed in 568 seconds:
6,338 episodes/hour, 303.7 decisions/second, 992 valid terminals, zero worker
restarts, 111,148 compiled combat samples, and 47,360 compiled macro samples.
The eight invalid pre-fix episodes were excluded and their exact seeds were used
to repair full-belt rewards/shops, noncombat death termination, and internally
triggered end turns.

An outcome-weighted v11 smoke candidate was trained separately and rejected on
an untouched paired 200-seed evaluation. V10 averaged floor 7.91 and reached Act
2 once; v11 averaged floor 6.09 and never reached Act 2. V11 remains an
unpromoted artifact. This is evidence that self-imitation, even outcome-weighted,
is insufficient; the next data source must be native branch/search comparisons.

## Generate trajectories

```powershell
python python/native_rollout_farm.py `
  --episodes 1000 `
  --workers 6 `
  --ascension 1 `
  --output-dir artifacts/native_rollouts/a1-1000
```

Use `--start-index` and a distinct output directory to resume with nonoverlapping
deterministic episode IDs. `--summary-only` is for throughput/soak tests and does
not create training transitions.

## Compile outcome-weighted data

```powershell
python python/compile_native_rollouts.py `
  artifacts/native_rollouts/a1-1000 `
  --combat-output artifacts/training/a1-1000-combat.jsonl.gz `
  --macro-output artifacts/training/a1-1000-macro.jsonl.gz
```

The compiler accepts only valid terminal episodes. It assigns an episode return,
computes a character/ascension/floor baseline, and writes clipped AWR weights.
This prevents failed on-policy runs from being mislabeled as expert wins while
still allowing better-than-peer trajectories to carry more weight.

## Train without episode leakage

```powershell
python python/train_v10_combat_policy.py `
  --shards artifacts/training/a1-1000-combat.jsonl.gz `
  --epochs 15 `
  --output models/v11_native_combat_policy.pt
```

Validation is grouped by episode/seed. Do not compare its numbers to the old
random-transition split: that split leaked neighboring states from the same run
into training and validation.

The macro output preserves card draft, map, rest/smith, event, shop, potion,
upgrade/remove, and other choice records with the same outcome weights. The live
rollout policy currently consumes exact option-aligned examples, 42,143-run
sample-shrunk card outcome statistics and synergies, and the 742 A10-win routing
corpus. It contains no binary health gate that forbids elites.

## Full-run mechanics acceptance

```powershell
python python/run_seeded_full_act_corpus.py `
  --seeds 2 --start 101 --repeat --ascension 10 --step-limit 2500
```

The current acceptance result is deterministic victory twice with the same final
hash, 847 decisions per run, 46 map rooms, four A10 bosses, three act transitions,
and the Architect terminal event. This forced-survivability corpus validates
mechanical reachability, not policy competence.

## Promotion gates

Never promote a checkpoint from imitation accuracy alone. Require all of:

1. deterministic full-run mechanics acceptance at A1 and A10;
2. zero protocol errors, step caps, and worker restarts in a meaningful soak;
3. held-out episode/seed validation, not transition-level leakage;
4. improved native-run survival, Act 2/3 reach, elite count, and win rate against
   the current checkpoint on identical seed sets;
5. per-character reporting so one character cannot conceal collapse in another.

## Native critic and value-model experiment record

This section is the preserved record of native critic and value-model candidates, including
rejected and demoted ones, so that disproven approaches are not repeated. All transition labels
and candidate states came from shipped native mechanics; rollout policy only chooses among native
legal actions.

### Scorer checkpoint requirements

The Torch scorer requires `mechanics_source=shipped_native`, `label_source=native_terminal_rollouts`,
the exact feature list, and matching assembly/PCK hashes inside the checkpoint. Existing project
checkpoints trained on the manual `RealisticRunEnvironment` are rejected. Unpromoted checkpoints are
also rejected by default; the smoke acceptance must request its integration-only override
explicitly. The default loader requires both the sibling-state gate and the fresh-encounter
search-lift gate.

`native-value-matrix.pt` passed the predeclared sibling-state gate but failed the subsequent
fresh-encounter search-lift gate and is demoted. Acceptance loads a schema-current rejected
candidate only with the explicit experimental override, verifies deterministic four-worker ranking,
and confirms that neither it nor the smoke checkpoint can silently become the search default.

### Value-corpus and critic results

- The earlier 72-episode value corpus remains marked `native_corpus_candidate_not_promoted`; its
  weaker deck/encounter generalization was correctly treated as a rejection signal.
- Its replacement matrix uses shipped-native terminal rollouts across all five characters and
  Strength, Exhaust, Poison, Shiv, Orb, Summon, and Star archetypes; 10- and 35-card decks; full,
  40%, and 15% HP starts; greedy, heuristic, and epsilon-random rollout policies; and native Act
  1/2/3 hallway, elite, and boss metadata.
- Training produced 336 terminal episodes (30 victories, 306 losses), 2,468 state labels, 144
  sibling rollouts, and 36 training ranking pairs. The encounter split is three-way: training
  encounters, a validation encounter per Act/tier stratum, and a different promotion-test
  encounter per stratum whose labels were not inspected while choosing the fixed 0.02 return gap,
  90% accuracy threshold, or 50-pair minimum. Validation achieved 94.25% (82/87 comparable pairs).
  The untouched promotion test achieved 90.91% (70/77), initially passing the sibling-state gate.
  Near-ties below the declared return gap were excluded before scoring (102 validation and 112
  promotion pairs).
- A stricter policy-level test then ran critic-guided depth-two search, greedy, and heuristic
  policies on five encounter IDs absent from every corpus split, with new seeds and equal
  250-decision episode caps. Every episode terminated, but critic search returned 0.2548 mean
  return and 0.0125 mean survival versus greedy's 0.2943 and 0.0850. Its observed lift was -0.0395
  against a predeclared +0.02 requirement, so the checkpoint is demoted. Four Act 2/3 elite/boss
  cells have no fourth distinct encounter in the shipped catalog after the three-way corpus split
  and are explicitly recorded as coverage gaps in `artifacts/native-value-search-evaluation.json`.
- Deeper on-policy ranking supervision raised one rejected candidate to 4,193 state labels and 125
  ranking pairs but reached only 84.70% validation. Adding native next-move intent, damage, and
  repeat features under scoring schema 3 produced 4,091 labels and 150 ranking pairs but reached
  only 81.40%; its promotion labels were never generated. Future promotion generation is
  conditional on validation passing.
- The robust v7 corpus used 1,008 episodes, 12,460 state labels, and nine native continuations per
  sibling action. Validation-selected removal of absolute hashed enemy identity reached 90.17%,
  but its untouched promotion split achieved only 84.56%, so it was rejected.
- The breadth v8 corpus then trained on every non-reserved native encounter rather than only one
  selected encounter per stratum: 61 training encounter IDs, 2,562 episodes, 35,244 labels, 4,779
  sibling continuations, and 444 ranking pairs. Its fixed MLP reached only 72.32% validation; an
  offline validation-only loss sweep topped out at 79.66%. No promotion labels were generated.

That sustained breadth run also corrected three simulator boundaries: terminal loss now follows the
actual native player creature rather than treating a surviving summon as the player; zero-star
`Stardust` is a legal shipped no-op, so rollout policies use state/action cycle detection to choose
another native legal action without modifying the card; and Fabricator's spawned bots retain native
spawn/RNG/power/AI mechanics while their `TestMode.IsOff` node-positioning blocks are suppressed as
presentation-only.

### Architecture verdict

The hashed-bag MLP is rejected as the general architecture. The v8 breadth artifact contains only
fixed 344-float features, so it is retained as an immutable baseline/task manifest rather than
misrepresented as token-model training data. The next critic requires a newly generated, versioned
v9 corpus with action-conditioned, permutation-aware card/creature/action tokens. Every subsequent
policy gate requires a new seed namespace. The simulator remains non-certifying outside exact
real-game replay checkpoints. Replay reconstruction remains a separate optimization target, and no
incremental manual gameplay scraping is part of this plan.

No critic is currently authorized as the application-wide default.
