# 14: The bridge can observe the card-select prompt it currently drops

**What to build:** One of the shipped card-select prompts produces no observation branch at all — no room and no legal actions — even though the bridge is waiting for a decision, so a shipped run that reaches it cannot be advanced by the oracle. Several Ancient choices open exactly that prompt, which bounds what a parity campaign can honestly claim. The bridge projects that prompt like every other decision: a room a caller can recognise, and legal actions that name the cards on offer, so a caller selects one by identity and the run continues.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A shipped run that reaches this card-select prompt reports a room for it rather than no room at all.
- [ ] The prompt's legal actions name the cards on offer, so a caller selects one by identity rather than guessing an index.
- [ ] Selecting one of the offered cards advances the shipped run past the prompt.
- [ ] The prompt and its resolution are observed end to end in a bridged run, not only inferred from static reading.
- [ ] The other card-select prompt the bridge already handles is unchanged.
