# 04: Branch the generator at one reward or option prompt

**What to build:** One scenario generation element stops producing one row per offered Ancient choice and starts producing one row per legal non-skip option at the reward or option prompt that choice opens — a bundle pick or a relic pick — so one run seed yields more of the variation it already offers. Every such row is an ordinary corpus row: a fixed-request row, replayable, and a first-combat scenario whose combat initial state is captured before the player acts. A prompt opened downstream of a selected option is still resolved by the current fixed rule and is not yet fully enumerated; this ticket establishes the branching machinery, not the whole traversal.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] For one element, every legal non-skip option at a reward or option prompt opened by the Ancient choice produces its own branch, and the skip option produces no branch.
- [ ] Each branch's row records the Ancient choice, the ordered nested selections that led to it including the selected option's identity, the node, and the complete pre-action combat initial state; replaying the recorded recipe reaches that same state.
- [ ] An option that fails produces its own failure row carrying the recipe resolved so far, and its sibling options still complete.
- [ ] Branch, row and shard order are deterministic; a fixed request, build and worker count produces byte-identical artifacts, and changing the worker count changes the shard boundaries and not the row set.
- [ ] Interrupting a batch part-way and resuming it produces the same rows as an uninterrupted run of the same request.
- [ ] First-combat scenarios reachable before this change remain reachable and reproducible, and rows that need no prompt option are unchanged.
