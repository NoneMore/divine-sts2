# 05: Enumerate card selections with selection-time pruning

**What to build:** Every legal non-skip selection at a card-select prompt the Ancient choice opens — adding a card, removing one, transforming one, upgrading one — becomes its own branch, because those selections are what change the run deck. Before branching, the prompt's plainly interchangeable actions are collapsed: offered copies that share a model, an upgrade level, an enchantment and a native state contribute one deterministic representative, so a deck of duplicate copies does not multiply one outcome. For removal and transformation only, when ordinary copies of a model coexist with upgraded or enchanted ones, only an ordinary copy is selected; that deliberately gives up some reachable scenarios, so it is stated where a user reads it.

Blocked by: 01 — Report copy identity for offered cards in a card-select prompt; 04 — Branch the generator at one reward or option prompt.

Status: ready-for-agent

- [ ] Each eligible card-select action at one prompt produces a branch whose actual selection is recorded and replayable; skip actions produce no branch.
- [ ] Copies sharing a model, upgrade level, enchantment and native state contribute exactly one deterministic representative action; distinct models or card states remain distinct branches.
- [ ] For removal and transformation, when ordinary and upgraded or enchanted copies of one model coexist, only an ordinary copy is selected for that model, and the omission is documented for users.
- [ ] A failed selection leaves a failure row and lets sibling selections complete; successful rows keep their complete native combat initial state with no post-generation semantic deduplication.
- [ ] Public scenario-generation and corpus behaviour is covered by fixtures or seeds that exercise duplicate copies, distinct models, distinct upgrades or enchantments and mixed ordinary/variant decks, including deterministic row order and fixed-request bytes.
