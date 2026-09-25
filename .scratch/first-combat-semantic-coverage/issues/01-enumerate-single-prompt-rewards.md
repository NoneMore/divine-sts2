# 01: Enumerate single-prompt Ancient rewards

**What to build:** For one character, Ascension and run seed, produce a replayable first-combat scenario for every legal non-skip option of an offered Ancient reward that opens one reward or option prompt. Other prompt kinds can retain their current deterministic resolution until later tickets. The added rows remain ordinary fixed-request corpus rows.

Blocked by: None (can start immediately).

Status: done

- [x] Every offered non-skip Ancient choice and every legal non-skip option at a single reward or option prompt produces a recorded branch; skip choices produce none.
- [x] Each success row records the offered Ancient choice, selected option index and identity, node and complete pre-action combat initial state; its recipe materializes the same state.
- [x] A failed option produces its own failure row with the resolved recipe and does not suppress sibling options.
- [x] Branch, row and shard order are deterministic; a fixed request, build and worker count produces byte-identical artifacts, and worker count changes do not change the row set.
- [x] Existing first-combat scenarios that need no nested reward option remain reachable and reproducible.

## Comments

Implemented single-prompt reward and option-pick enumeration in the public scenario generator. Reward recipes now retain the selected reward's identity; failed branches retain their nested selection. The offline suite passed (286 tests), including replay, skip, failure-isolation and corpus-determinism coverage.
