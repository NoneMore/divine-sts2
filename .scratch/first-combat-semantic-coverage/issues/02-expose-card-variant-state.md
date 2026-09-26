# 02: Expose card variant state on selectable cards

**What to build:** A card offered by a card-select prompt reports enough for a caller to tell two copies of one card model apart by upgrade level, enchantment and native card state, through the canonical observation that both generated scenario rows and the shipped-game bridge read. Today a selectable card carries only an option id and a model id, which makes the agreed interchangeable-copy rule undecidable rather than merely unimplemented.

This is the enabling ticket for selection-time pruning: the rule that copies sharing model, upgrade level, enchantment and native state are interchangeable cannot be applied, and the removal and transformation preference cannot be justified, until the offered card's own variant state is observable. The route may be new fields on the canonical choice option, or a checked derivation from the pile the card came from; either way the choice of route is recorded with what it cannot see, and generated cards that come from no pile must report a state rather than a gap.

Blocked by: None (can start immediately).

Status: ready-for-agent

- [ ] Every card offered by a card-select prompt reports its model, upgrade level, enchantment and native card state, or is resolved through a documented and checked derivation from the pile it came from.
- [ ] A card the prompt generates rather than takes from a pile reports its own state explicitly rather than an absent or guessed one.
- [ ] The published observation schema and its version carry the added information, and the bridge and the simulator agree on it; existing recorded observations are regenerated or version-bumped rather than reinterpreted.
- [ ] The parity contract still holds: equality between the simulator and the shipped game is never decided by card instance identity.
- [ ] Public tests cover an upgraded copy, an enchanted copy, two identical ordinary copies and a generated option, at the observation boundary a scenario row is read from.
