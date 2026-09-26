# 01: Enumerate single-prompt Ancient rewards

**What to build:** For one character, Ascension and run seed, every legal non-skip option that an offered Ancient choice opens at a single reward-set, bundle or relic option prompt becomes its own replayable first-combat scenario. Today a scenario generation element resolves each nested prompt by taking the first legal action, so one element yields one row per offered Ancient choice and nothing more; after this ticket an element yields one row per legal non-skip option, each with its own ordered recipe, at a per-branch cost that keeps deeper recursion affordable.

This ticket carries the branch mechanism itself, so it also settles and states how a sibling branch's state is obtained — a checkpoint taken at the prompt it branched from, or a replay that reaches the same prompt again — with the measured cost of each beside the cost of a whole run drive. One prompt-kind vocabulary (which action kind means card-select prompt, option pick, reward set and skip) serves the generator, the materializer and acceptance, so prompt-kind knowledge stops being repeated per call site and the kinds that follow in later tickets plug into one place.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] A reward-set, bundle or relic option prompt opened by an offered Ancient choice produces one recorded branch per legal non-skip option, in the order the run offered them; skip actions produce no branch.
- [ ] Each success row records the offered Ancient choice, the prompt kind, and the selected option's index and identity at that prompt, plus the complete pre-action combat initial state; its recipe materializes the same state.
- [ ] A failed option produces its own failure row with the recipe resolved so far and does not suppress its siblings.
- [ ] One prompt-kind vocabulary decides prompt kind, skip eligibility and option identity for generation, materialization and acceptance, and a prompt kind it does not know fails loudly rather than being treated as a default.
- [ ] The mechanism that materializes a sibling branch is stated for callers with its measured per-branch cost, and a branch state the worker can no longer restore is an explicit failure rather than a wrong row.
- [ ] Branch, row and shard order are deterministic; a fixed request, build and worker count gives byte-identical artifacts, and a different worker count leaves the row set identical.
- [ ] Existing first-combat scenarios that need no nested option stay reachable, reproducible and unchanged.
