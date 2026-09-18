# Deep modules for STS2 Gym

## Purpose

Restructure the repository around deep modules without changing simulator behaviour. The immediate
hotspot is `PersistentNativeCombatEnvironment`: it repeats the current run state across mode flags,
action dispatch, capture, legal-action construction and branch projection. Python scenario generation,
protocol models and observation contracts are the later seams.

The work is complete when callers learn smaller interfaces, behaviour and verification concentrate
behind those interfaces, and the repository remains a useful base for later NoSL combat-algorithm
research. File count and line count are diagnostic only, never acceptance criteria.

## Frozen behaviour

- Existing Python CLI and documented command behaviour.
- Both current RPC wire encodings, method names, JSON fields and error behaviour.
- Canonical observation compatibility during structural moves; intentional future schema changes are
  versioned explicitly.
- State-hash behaviour during the active-state migration.
- Generated-scenario recipe and row formats, corpus ordering, shard layout, resume behaviour and
  compressed byte reproducibility.
- Generated-scenario parity with the shipped game and the Fully unlocked run baseline.

Internal interfaces, file layout and session-scoped branch handles may change. A branch restore must
still reproduce its expected hash.

## Core target

`PersistentNativeCombatEnvironment` becomes a coordinator over an internal `RunSession` module. The
coordinator owns branch history, state hashing, RPC result envelopes and timing. The module exposes one
small interface: read the current `DecisionFrame`, then apply an action id.

The implementation uses a closed active-state union. Exactly one state is active; a Card-select prompt
replaces its parent as the active state and holds an in-memory typed continuation. A frame atomically
projects the observation, legal actions, terminal status and compatibility kernel data. Its hidden
action table maps each advertised id to its executor, so invalid actions fail before native mutation.

Shipped-game reflection is a true external dependency behind a semantic command/query port. The
production adapter owns reflection objects, Harmony callbacks, native tasks and selectors; a scripted
fake adapter drives offline tests. Branch restore continues to replay the reset recipe and action
history against an expected hash. Combat remains behind a temporary legacy adapter in this effort.

The module lives under `Sts2.NativeSim.Core/RunSession/`, with internal `States/` and `Native/`
organization. Room-specific classes are implementation details, not caller-visible interfaces.

## Test strategy

Add an xUnit project at `tests/Sts2.NativeSim.Core.Tests`. Tests cross the same coordinator seam as
callers and inject the scripted native adapter. They protect reset, legal actions, step, capture,
nested prompts, collision and error atomicity, event/combat/reward transitions, and fork/restore.

Before moving non-combat states, characterize the path from a Generated scenario recipe through its
Ancient choice, nested choices and map node to the recorded Combat initial state. Once equivalent C#
interface tests exist, remove Python tests that merely match the old C# source structure; retain
cross-language schema, consumer, parity and shipped-game acceptance tests.

## Scenario and research seam

The current `generate_rows` and `generate_corpus` functions remain two independent public interfaces.
The former drives request elements; the latter additionally owns deterministic sharding, worker
lifecycle, resume and atomic byte-identical output.

Split `sts2_native_sim.scenarios` into model, generation, corpus, driver, codec and store implementation
files without expanding its public surface. Add `materialize_scenario(scenario, worker)`, which validates
a Generated scenario, replays its recipe into a live worker, reaches its recorded first combat and
checks the resulting identity/hash. Add a thin Combat episode facade exposing only current observation,
legal actions, forward `step(action_id)`, combat completion and outcome/HP loss.

This facade is not a NoSL algorithm. It is the post-refactor guarantee that later research can read a
corpus, materialize a scenario and finish one combat without depending on room flags, private generator
helpers, branch handles, fork or restore.

## Python structure

Use four support levels:

- `python/sts2_native_sim/`: supported library and formal CLI.
- `python/tools/`: maintained generation, training, diagnosis and benchmark commands.
- `python/experiments/`: isolated research with no compatibility promise.
- `tests/acceptance/`: shipped-game verification.

Published script paths keep thin launchers for a documented deprecation period. Shared implementation
must not remain in launchers, and supported code must not import tools, experiments or acceptance code.
Broken learned/neural commands are removed from public documentation and classified as experiments;
this effort does not reconstruct their deleted model stack.

## Protocol and observation

Per ADR-0005, headless and FullAppBridge share internal request, response, error and legal-action models
while retaining adapters for their existing wire JSON. Wire convergence requires a separate versioned
migration.

`Sts2.NativeSim.Protocol` becomes the owner of typed canonical observation records and generated JSON
Schema. Runtime-specific host adapters encode into those records. Parity compares canonical fields by
path; host hashes remain intentionally different because the headless hash also protects its transition
kernel.

## Delivery order

1. Audit the supported surface and protect future combat-research inputs.
2. Establish the C# test and scenario-replay safety net.
3. Introduce the active-session seam, continuation and non-combat states incrementally.
4. Publish scenario materialization and the Combat episode facade, then split scenario/corpus code.
5. Reorganize Python with compatibility launchers.
6. Share protocol models, then type the canonical observation contract.
7. Dispose of edge tools from evidence and run the full gates.

The issue files are the executable breakdown and dependency graph.

## Out of scope

- Rewriting the combat kernel or designing a NoSL combat algorithm.
- Changing either existing wire JSON contract or creating wire v2.
- A cross-host state hash.
- Serializable native continuations, portable snapshots or a second long-lived restore mechanism.
- A third-party room plugin system.
- Restoring the deleted learned/neural model stack.
- Deleting tools before their consumers and unique capabilities are audited.
- Any change to scenario parity, corpus bytes or Fully unlocked run semantics.

## Decisions

- [ADR-0005](../../docs/adr/0005-share-rpc-contracts-while-keeping-host-encoders.md)
- [ADR-0006](../../docs/adr/0006-model-run-decisions-as-one-active-state.md)
- [`CONTEXT.md`](../../CONTEXT.md) remains unchanged: this plan introduces engineering interfaces, not
  new game-domain vocabulary.
