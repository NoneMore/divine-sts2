# 08: Drive option picks and card copy identity in the shipped-game bridge

**What to build:** A caller can answer the shipped game's bundle and relic option prompts through the existing full-app bridge instead of letting autoplay pick — including the prompt that opens after an answer — so those branches can be checked against the game. The bridge also names the offered cards of a card-select prompt the way the canonical observation now does, so a prompt described by the game and by the simulator can be compared card by card rather than as a bag of models.

Blocked by: 01 — Report copy identity for offered cards in a card-select prompt.

Status: ready-for-agent

- [ ] The bridge reports the legal option identities of a blocking bundle or relic option prompt and accepts a selected legal option rather than allowing autoplay to answer it.
- [ ] Selecting each offered option advances the shipped run through that option's native effect; an illegal, stale or unavailable selection is refused with an explicit error rather than silently answered.
- [ ] A prompt opened after an answered option is reported and answerable within the same run.
- [ ] The bridge reports each offered card's model, upgrade level, enchantment and native state for the card-select prompts it already drives, matching the simulator's record of the same prompt (01), and still lets a caller answer a prompt whose choices name no cards.
- [ ] A focused full-app acceptance run proves caller-driven option picks for representative bundle and relic prompts, and the existing card-select and first-combat bridge samples still pass.
