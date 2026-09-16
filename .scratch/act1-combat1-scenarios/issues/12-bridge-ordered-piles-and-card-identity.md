# 12: Ordered piles and per-card identity on the bridge

**What to build:** The bridge currently reports how many cards are in a pile and nothing about what they are, so a draw pile's order — the thing a policy actually learns from — is invisible to the oracle. Every pile becomes an ordered list of contents: hand, draw, discard, exhaust, and play, which today has no representation at all. Each card reports its instance id, model id, card type, target type, energy cost, cost-x flag, upgrade count, enchantment and native state. Because card instance ids are minted by whichever encoder produced the state, the bridge needs its own identity registry, and the comparison treats identity structurally — position within an ordered pile plus the card's other attributes — while ids the game itself mints stay literal. Two fields that today look right but are not are repaired in passing: the hand's reported energy cost comes from the same accessor the repository's other projections use, and the hand's upgrade count is populated instead of always reading zero.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] All five piles are reported as ordered contents, and the play pile exists.
- [x] Every card carries an instance id stable within one observation, a model id, a card type, a target type, an energy cost, a cost-x flag, an upgrade count, an enchantment with model id and amount, and its native state.
- [x] The hand's energy cost comes from the same accessor the repository's other state projections use, so the two agree for the same card.
- [x] The hand's upgrade count reflects real upgrades instead of always reading zero.
- [x] Card instance ids are minted by the bridge's own registry and are comparable structurally — position within an ordered pile plus the card's other attributes — while ids the game itself mints are comparable literally.
- [x] The card shape converges on the repository's existing rich per-card projection rather than becoming a third shape.
- [x] A bridged shipped run reports an ordered draw pile whose order is stable across two observations of the same state.

## Comments

**2026-09-16 — implemented.**

- **A fight is five ordered piles of cards, not a hand and three counts.** `combat.piles` replaces
  `combat.hand`, `combat.draw_pile_count`, `combat.discard_pile_count` and
  `combat.exhaust_pile_count`. Each pile row is `{name, type, cards}`: `name` is the word every
  projection uses (`Hand`, `DrawPile`, `DiscardPile`, `ExhaustPile`, `PlayPile`, in that order — the
  play pile had no representation at all before), and `type` is the game's own word for the pile that
  was walked (`pile.Type.ToString()`), so the pairing of a name and a type is never the bridge's
  invention. The order and the pairing are stated three times on purpose — once by
  `FullAppStateTracker.CombatPiles`, once by the offline shape test and once by the acceptance — so a
  projection that stops agreeing with another fails instead of being normalised.
- **Every card is the simulator's own card row, key for key.** `instance_id`, `net_id`, `model_id`,
  `card_type`, `target_type`, `energy_cost`, `costs_x`, `upgrades`, `enchantment` (present only when
  the card carries one, so the null member is dropped the way every other projection drops it) and
  `native_state`. The bridge's older card row — `index`, `card_id`, `cost`, `can_play` — is gone, so
  there is no third shape; a legal play still names its `card_index` in the action metadata, which is
  the position in the hand pile.
- **The two fields that looked present while reading the wrong thing are repaired.** `energy_cost` is
  `CardEnergyCost.GetResolved()` — the accessor the simulator's pile projection and the trace
  exporter both read — rather than `CardEnergyCost.Canonical`, which the hand alone read; and
  `upgrades` is `CardModel.CurrentUpgradeLevel`, where the hand's field had been declared and never
  assigned, so it always read zero.
- **The bridge mints its own card identities, in `CardIdentity.cs`.** `instance_id` is
  `dynamic-<ordinal>-<model id>` from a registry keyed by card object identity, which recalls the id
  it minted for a card it has already seen and starts its ordinals again when a new fight's combat
  state appears. That is what makes an id stable across observations of one fight while staying the
  encoder's own; `net_id` is `NetCombatCardDb.Instance.GetCardId`, an identity the game mints, and is
  reported literally. `native_state` is one entry per saved scalar property (`ints`, `bools`,
  `strings`, `intArrays`), ordered by name, which is the group set the simulator's own projection
  reads. `net_id` is the one member read through a game API that can refuse: `GetCardId` throws for a
  card the game has not registered, and the bridge calls it for every card of every pile where the
  old hand row called it for none. That is the same call the simulator's pile projection and the
  trace exporter make, and a card reaches a combat pile through the game's own registration, so the
  acceptance observes it for all ten cards rather than the bridge carrying a fallback the other two
  projections do not have.
- **The bridge's own `schema_version` moved 3 → 4** with the shape, as the previous ticket's comment
  said it would, and the DTO's doc comments say so. The bridge's state hash covers its DTO, so its
  hashes move with the shape; that is expected of a DTO-covering hash and it is not compared against
  the simulator's.
- **One `BridgeJson.Options` writer still serves both** the observation and the hash, so the new
  nullable member (`enchantment`) is absent rather than `null` in both.
- **Observed with the shipped game** (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`), by the extended
  `python/bridge_combat_observation_acceptance.py`: one headless worker, seed `A1B2C3D4E5`,
  `IRONCLAD`, Ascension 0, driven `event → event → map → combat` by the first legal action at each
  boundary. The row-1 fight reports the five piles in order — `Hand` 5, `DrawPile` 5, `DiscardPile`
  0, `ExhaustPile` 0, `PlayPile` 0 — holding all ten cards of the deck; the hand is four
  `STRIKE_IRONCLAD` at `energy_cost` 1 and one `BASH` at 2, each with the game's own `net_id` 0–4,
  `costs_x: false`, `upgrades: 0`, `native_state: {}` and a `dynamic-N-…` instance id; the draw pile
  is four `DEFEND_IRONCLAD` and one `STRIKE_IRONCLAD`. Reading the same state twice returns the draw
  pile in the same order with the same identities, and after the first turn ends — a rebuilt
  observation — the opening hand's cards keep the identities they were minted with: the acceptance
  requires at least the opening hand, because ending a turn moves the hand rather than replacing it,
  and that run kept all ten cards of the deck. Bridge state hash
  `2E5DC5C5453C879FB06AABFD8222918E1E30B1FF8F1C15D7D019AA31870583B9` at the fight, and
  `FD5A4EEE77C864880AC002DEB2350DAED2FC51F365443A44DE2E928FCCA55ACB` on turn 2 with the player's
  `WEAK_POWER` reported.
- **Two checklist items are pinned offline rather than measured at runtime, and the acceptance says
  so.** "The two agree for the same card" needs two projections of one hand card, which only the
  field-by-field parity run has (ticket 15) — the bridge no longer has a second hand-only cost field
  to compare against — and a real upgrade count needs an upgraded card, which a starting deck does
  not contain. Both accessors are pinned by
  `tests/test_bridge_observation_shape.py::test_a_bridge_card_row_reads_the_accessors_the_repositorys_other_projections_read`,
  and the acceptance observes the fields present, typed and non-zero where the game charges energy
  (a cost that always read the canonical number would still pass, so the accessor itself is the
  offline pin's business).
- **Offline, `tests/test_bridge_observation_shape.py` (16 tests)** compares the bridge's DTO
  declarations against the recorded capture `run_combat_action` in
  `tests/fixtures/canonical-observations.json` and against the simulator's own projections in
  `PersistentNativeCombatEnvironment.cs`: the pile row is word for word the recorded pile row, the
  card row is word for word the recorded card row plus the `enchantment` a capture only carries when
  a card is enchanted, the card row names nothing the simulator's `Pile` projection does not, the
  five piles are declared in the recorded order with the recorded name/type pairing, the older hand
  seam is gone, and the card row reads `GetResolved()`/`CurrentUpgradeLevel` from the registry and
  the game's own `NetCombatCardDb`.
- **The one bridge-fed Python consumer was migrated.** `full_act_bridge_acceptance.py` read
  `combat.hand[].index/cost/target_type`; it now reads the hand pile through a `pile_cards` helper.
  `pure_neural_agent.py`, `train_combat_policy.py` and `expert_combat_retriever.py` also mention
  `combat.hand`, but none of them imports the bridge client — they read the V10 supervision corpus's
  `card_id` key, which the bridge never emitted.
- **Deliberately not in this ticket.** The run block (RNG counters, act floor, act index base, map
  coordinate, game build) and the inventory (relics and potions as objects) stay for ticket 13;
  `orbs`, which the trace exporter and the simulator report, are in neither the bridge nor the parity
  contract, so no ticket owns them. The legal actions keep their index-shaped `play_card:<n>` ids,
  because nothing in this ticket changes how a caller names a card to play.
- **The two one-line pile lookups stay duplicated.** "The cards of this pile, by name" lives in the
  acceptance script and in the bridge-fed driver, and they are two lines in two scripts outside the
  package; a helper in `sts2_native_sim` would be a module neither script otherwise uses, which is
  the same call the previous ticket made about the two `side == "Enemy"` filters.
- **Gates.** `python -m pytest tests -q` gives **152 passed, 22 errors**, where all 22 are the
  documented `tmp_path` sandbox refusal in `test_dev_environment.py`/`test_sandbox*.py` — files this
  change does not touch. `ruff check` and `mypy` are clean on everything this change adds or touches
  (`full_act_bridge_acceptance.py` keeps the 20 pre-existing findings it had before), the bridge
  builds in `Release` with 0 warnings and 0 errors under `TreatWarningsAsErrors`, and
  `pwsh scripts/test-public-tree.ps1` passes.
