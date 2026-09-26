# 01: Report copy identity for offered cards in a card-select prompt

**What to build:** A caller handed a card-select prompt can tell the offered cards apart by more than their model: each offered card reports its upgrade level, its enchantment and its evolving native state beside the model and the stable option identity the prompt already reports. The added facts are what lets a caller decide that two offered copies of one model are interchangeable rather than guessing it, and nothing existing changes shape — a consumer that reads only the model keeps working, and a recorded first-combat scenario keeps its recorded hashes.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] Every offered option of a card-select prompt reports its card model, upgrade level, enchantment and native state beside the stable option identity it already carries, in the order the game offered them.
- [ ] The published canonical-state schema describes the added fields, is regenerated from its source, and its observation schema version is bumped with it; a captured card-select prompt validates against the regenerated schema.
- [ ] Two offered copies of one card model that differ in upgrade level, enchantment or native state are distinguishable through the public observation, and a caller cannot be forced to treat them as one.
- [ ] Recorded hashes and fixtures pinned at a state with an outstanding choice are re-pinned in the same change, and the hash of a recorded first-combat scenario is verified unchanged because its recorded state carries no outstanding choice.
- [ ] The same prompt captured twice reports byte-identical option identities and card facts.
