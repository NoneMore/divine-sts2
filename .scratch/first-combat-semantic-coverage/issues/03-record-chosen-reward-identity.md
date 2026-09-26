# 03: Record the chosen reward's identity at each reward step

**What to build:** Every nested reward-set step in a recipe records which reward the branch took, not only the index it took it at, so a retained branch is reproduced and replayed by identity rather than by position in a list that a build change can reorder. Reward-set steps are the one nested kind that records an index only, which the existing record states as a gap rather than hiding.

This closes a requirement the coverage spec now makes explicit: the retained choice indices and the offered option identities are recorded in order. It changes a row's shape, so the nested-choice key order, the materializer that consumes it and the corpus artifacts that serialize it move together, and a row written before the change is refused or read under its own version instead of silently meaning something else.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] A reward-set step in a recipe records the selected reward's index and its identity, at every reward depth a branch can reach.
- [ ] The materializer takes a recorded reward step by identity, and fails explicitly when the prompt no longer offers that reward.
- [ ] Row and nested-choice key order are updated together with every artifact that depends on them, and a fixed request on a fixed build still produces reproducible bytes.
- [ ] Rows written before the change are refused or read under their own version; no recorded row silently changes meaning.
- [ ] Public tests cover a reward set opened inside another reward set and assert that the recorded identity is the reward the run actually offered.
