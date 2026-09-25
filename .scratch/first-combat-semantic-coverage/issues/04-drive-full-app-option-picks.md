# 04: Drive option picks in the shipped-game bridge

**What to build:** Let a caller select the options offered by the shipped game's Ancient reward prompts through the existing full-app bridge, alongside its current card-select support. This makes bundle and relic choice branches directly verifiable against the game.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] The bridge reports the legal option identities for blocking card-bundle and relic option prompts and accepts a selected legal option rather than allowing autoplay to answer it.
- [ ] Selecting each offered option advances the shipped run through the corresponding native reward effect; illegal or stale selections are rejected explicitly.
- [ ] A focused full-app acceptance run proves caller-driven option picks for representative bundle and relic prompts, including a subsequent prompt when one opens.
- [ ] Existing card-select prompts and the prior first-combat bridge sample continue to work.
