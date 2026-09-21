# STS2 Gym

STS2 Gym exposes isolated native Slay the Spire 2 runs for simulation and full-application automation under one progression-complete baseline.

## Language

**Progression-complete baseline**:
The project-wide premise that every run has all progression unlock, content discovery, epoch, and tutorial gates complete. It excludes achievements and career totals and is not a selectable run input: the simulator represents its gameplay effects directly, while each full-app sandbox materializes it as deterministic isolated progress data.
_Avoid_: Completed profile, unlock mode, progression configuration

**Fully unlocked run**:
A new run whose legal gameplay content pools follow the progression-complete baseline while still obeying game-mode constraints. Character, run seed, and Ascension remain run inputs; profile progression and discovery do not.
_Avoid_: Progression-locked run, configurable-unlock run, all-unlocked profile

**Full-app sandbox**:
An isolated single-player full-game session whose user-data directories are separate from the player's real profile and saves and materialize the progression-complete baseline.
_Avoid_: Test profile, real profile

**Shipped game**:
A legally installed, unmodified Slay the Spire 2 client, as distinct from this project's simulator.
_Avoid_: Real game, original game, vanilla game, production build

**Run seed**:
The string that identifies a run's randomness, as a player would enter it in the shipped game.
_Avoid_: Seed index, seed prefix, numeric seed

**Ancient**:
The event room that begins every act and offers a set of run-start choices.
_Avoid_: Neow (except for act 1's own Ancient), shrine, blessing room

**Neow**:
The Ancient of act 1.
_Avoid_: Neow as a general name for Ancients or for the Ancient room type

**Ancient choice**:
One of the choices an Ancient room offers at run start, including the nested choice — a card select, reward set, or bundle pick — that some choices open before the run continues.
_Avoid_: Neow blessing, blessing, boon

**Card-select prompt**:
A decision in which the shipped game offers a flat set of cards and waits for the player to choose from them — a removal, an upgrade, a transform, a discard, or a card to add — as distinct from an option pick, which offers bundles or relics. The game asks the card selector the run installed before it would push a selection screen, so a bridged run reports the prompt as one stage of its own wherever it was opened from, with the cards on offer named so a caller selects one by identity.
_Avoid_: Card select screen, simple card select screen, choose-cards prompt

**Option pick**:
A decision in which the shipped game offers whole options rather than single cards — a bundle of cards, or a relic to choose — and which no card selector answers, so a bridged run reports no stage of its own for it yet.
_Avoid_: Bundle pick, mixed with card-select prompt

**Combat initial state**:
The state of a combat at the moment it has begun and before the player has made any decision.
_Avoid_: Starting state, opening state, run-start state

**Act variant**:
One of the interchangeable models for the same act index — for act 1, `Overgrowth` and `Underdocks` — which share the act's map topology but not its encounter, event, or boss pools.
_Avoid_: Map variant, act 1 variant (the map itself does not vary)

**Generated scenario**:
A recorded run-start situation together with the choices that produced it, such that the shipped game can reproduce it from the same run seed.
_Avoid_: Sample, fixture, seed dump

**Failure row**:
A row of a generated corpus standing in for one element the generator could not turn into a scenario: the stage the run stopped at, an error kind and message, and the recipe resolved so far — never a combat initial state.
_Avoid_: Error record, dropped seed, skipped element

**Corpus shard**:
One worker's contiguous block of a generated corpus's expanded request, written as a single compressed JSONL file beside its siblings under the corpus's artifact root. Which elements a shard holds follows from the request and the worker count alone, never from which worker finished first, and two runs of one request on one game build with one worker count produce byte-identical shards — compressed bytes included — so a regenerated corpus diffs cleanly. Changing the worker count moves the shard boundaries and leaves the rows alone.
_Avoid_: Chunk, partition, worker file

**Corpus summary**:
The file beside a generated corpus's shards that names the request, the game build, the worker count, the shards and the rows by type. It is also what a resumed batch reads to learn which shards are already written, and it is written by declaration like a row, so regenerating one request on one game build with one worker count rewrites it byte for byte.
_Avoid_: Index file, metadata, sidecar
