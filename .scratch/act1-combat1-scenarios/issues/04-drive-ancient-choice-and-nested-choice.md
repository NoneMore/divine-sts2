# 04: Drive an Ancient choice and any nested choice to completion

**What to build:** Choosing one of the Ancient's offered options completes through the game's own option path, so the relic is obtained by the game and whatever randomness that consumes is the game's, not a reimplementation's. Some choices open a second, blocking prompt — a card select, a reward set or a bundle pick. That prompt is answerable through the same headless decision loop as every other run-mode decision, so a caller can resolve it and carry on to the map without a graphical tree and without replaying the run.

**Blocked by:** 03: Offer and enter the act-1 Ancient room at run start.

**Status:** done

- [x] Choosing an offered Ancient option obtains the relic that option reported, through the game's own option-completion path.
- [x] Choosing an offered Ancient option consumes only randomness the game itself consumes, so the run's RNG counters afterwards are the ones a shipped run has.
- [x] An Ancient choice that opens a nested prompt produces a further observable decision whose legal actions a caller can select.
- [x] Each nested-prompt kind the shipped Ancient choices open — card select, reward set and bundle pick — is reachable and completable.
- [x] An Ancient choice that opens no nested prompt proceeds straight to the map with no extra decision.
- [x] The nested prompt resolves headlessly, with no reliance on presentation or a scene tree.

## Comments

**2026-09-16 — a concrete nested-prompt gap found while landing 03.**

Sweeping all offered choices over 37 seeds with a de-risking probe while landing 03 (the probe is not
kept; 03's acceptance script only takes a choice that opens no second prompt), one choice fails to
complete:
`NEOWS_BONES`. Its pick-up offers a reward set that itself begins a second reward set, and
`CaptureRewardsScreen` refuses the second with `nested_reward_collision` ("a second native reward set
began before the first was resolved"), so the choice cannot be driven to the map. Every other choice
completed, walking the first legal action at each step: plain relic pick-ups, `card_choice`
(`FromDeckForRemoval`, `FromChooseACardScreen`, `FromDeckForTransform`, `FromDeckForUpgrade`),
`option_choice` and custom-reward chains up to four reward sets deep. Before ticket 03 the Ancient
room was never entered, so none of this was reachable.

**2026-09-16 — implemented.**

- **Native reward sets are a stack, because the shipped synchronizer's are.** `RewardsSetSynchronizer`
  keeps a `rewardsStack` per player and says why: "relics, when taken from a rewards screen, may
  themselves spawn new rewards screens. This acts like a stack." The environment modelled that as one
  `_pendingRewardsSet` slot and threw when a second set arrived; it now keeps `_rewardSets`, and
  `CaptureRewardsScreen` pushes instead of refusing. `NeowsBones.AfterObtained` is the shipped case
  that reaches it: choosing `NEOWS_BONES` offers a two-relic reward set, and `LOST_COFFER`,
  `KALEIDOSCOPE` or `SMALL_CAPSULE` taken from it offer rewards of their own.
- **Each frame records two things**: the set, and the task the run was suspended on when that set
  became the decision — the transition that offered it for the outermost set, the enclosing reward
  selection for a nested one. `SettleRewardSetsAsync` walks the stack from the top down: when a
  nested set is resolved it pops, and the enclosing set becomes the decision again, which is safe
  because the enclosing selection has unwound by then and the loop waits on exactly that. A set that
  is only partly taken leaves `_continuationTask` back on the task the run was suspended on, so the
  next `choose_custom_reward` starts from the same place.
- **Waiting on the right task is the whole fix.** A nested frame's suspension is the *enclosing
  selection*, and awaiting that from inside the unwinding chain deadlocks: the selection completes
  only once the nested set's own `Offer` returns, which is the thing that resumes past the await.
  What does settle the run is, in order, the enclosing selection (the loop's await) and — once the
  stack empties — the transition that offered the outermost set, which is what the single-set code
  already awaited. A first attempt also read the set's own `Offer` task out of the synchronizer's
  `completionSource`; that turned out to be redundant, since a set is only finalised once the
  synchronizer has already completed it, so the reflection into `_rewardStates` was dropped. The
  path was pinned down by walking `ACTVARIANT04`/`NEOWS_BONES` with per-step stderr tracing, and the
  fixed nested sample's `driven_hash` is unchanged by the simplification.
- **A nested prompt now reports its own decision kind.** `_pendingChoice` describes the decision more
  specifically than the reward set whose reward opened it, so a card select inside a reward set
  reports `card_choice` with `choose_cards` actions instead of `custom_reward_choice` with
  `choose_cards` actions — the mislabelling the sweep found on `LEAD_PAPERWEIGHT` and friends. One
  `DecisionKind`/`DecisionActions` pair now decides both the kind and the legal actions in every
  capture that can hold a nested decision (combat, rest, event, the standalone reward seam, shop,
  room rewards, treasure), which is also what the custom-reward capture already did; room rewards and
  treasure previously reported their own stage's actions while `legal_actions` reported the nested
  set's, and combat reported `combat_action` while its actions were reward actions. Kind and actions
  agreeing is the point, so the vocabulary had to move everywhere a nested decision can appear rather
  than only in the Ancient room. Consumers that switch on the kind see the corrected routing:
  `native_rollout_policy.py` sends a nested card select to its `card_choice` branch, where the
  `choose_cards` actions are ones it knows how to score, instead of to `custom_reward_choice`.
- `CustomRewardsSnapshot` gained `depth`, the number of reward sets open with this one included, and
  the room-reward and treasure captures gained the `outstanding_choice`/`outstanding_rewards` blocks
  the other captures already had. `depth` is what names *which* set a nested choice resolved — the
  spec wants each nested choice in a record's identity, and two sets can be open at once — so a
  caller cannot mistake an answer to the outer set for an answer to the one it opened.
- New shared Python: `sts2_native_sim/ancient.py` gains `drive_choice`, `DrivenChoice`/`NestedDecision`
  and `choice_actions`. `drive_choice` applies one offered choice and answers every prompt it opens on
  the same headless loop, taking the first legal action unless the caller passes `choose`; it returns
  each nested decision *with the action the caller took from it*, which is what a record needs and
  what the skip pass below uses. `leave_ancient` is now that plus `leave_event`, so ticket 03's
  reachability rule and this ticket's driver are one implementation; `ancient_room_acceptance.py` uses
  the same helper instead of carrying its own copy of the loop.
- New `python/ancient_choice_acceptance.py` drives **every offered choice on all 37 offer-sweep
  seeds** (111 choices, both Act variants) and asserts, per choice: the reported relic is in the run's
  relic list with the untouched relics ahead of it and only the chosen relic's own effect adding
  more; the choice reaches `event_complete` and the room then yields the map; each nested decision's
  kind and action kinds agree, it offers at least one selectable action, and the action the driver
  took is one of them; the prompts it opened are the ones declared for its relic and no others; a
  prompt-free relic opens nothing at all; and the run's counters moved exactly as the relic's own
  shipped code draws. Sweep-wide it asserts that every declared prompt kind — `card_choice`,
  `custom_reward_choice`, `option_choice` — is reached somewhere, that the reachability rule's
  `PROMPT_FREE_CHOICES` is a subset of the relics that really are prompt-free, and that at least one
  choice drove a reward set inside a reward set (`depth` 2). It then re-drives four choices whose
  pick-up offers a *skippable* reward set — `KALEIDOSCOPE`, `LOST_COFFER`, `SMALL_CAPSULE`, and the
  `NEOWS_BONES` sample that nests one — resolving each by `skip_custom_rewards` and checking the
  choice still hands back and reaches the map, which covers the other half of the reward-set loop
  including a depth-2 skip. Finally it re-drives the nesting sample on a second worker and checks the
  relics, the counters, both hashes and a restore agree, and it fails closed if the shipped assembly
  is not the one the tables were observed against.
- **Observed** with the shipped game (assembly
  `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`) through the Godot-hosted
  native worker, by `python/ancient_choice_acceptance.py --workers 4`: 111 choices driven, 55 of them
  prompt-free, 38 card-select, 38 reward-set and 4 bundle-pick decisions answered, 4 of them reaching
  reward-set depth 2, and 4 reward sets resolved by skipping (including a depth-2 skip on
  `ACTVARIANT04#2`), with no failures; `repeat_driven_hash`
  `F68A9BE6252B58EF90FE5FF5B835FB073970AA2F2EA412BBA08FCEE9E02A79DB` for `ACTVARIANT04#2`.
- **What each offered relic opens**, over these 37 seeds. No prompt at all: `BOOMING_CONCH`,
  `CURSED_PEARL`, `FISHING_ROD`, `GOLDEN_PEARL`, `LARGE_CAPSULE`, `LAVA_ROCK`, `LEAFY_POULTICE`,
  `NEOWS_TALISMAN`, `NEOWS_TORMENT`, `NUTRITIOUS_OYSTER`, `PHIAL_HOLSTER`, `SILKEN_TRESS`,
  `SILVER_CRUCIBLE`, `STONE_HUMIDIFIER`, `WINGED_BOOTS`. A card select: `HEFTY_TABLET`,
  `LEAD_PAPERWEIGHT`, `NEW_LEAF`, `POMANDER`, `PRECARIOUS_SHEARS`, `PRECISE_SCISSORS`. A reward set:
  `KALEIDOSCOPE`, `LOST_COFFER`, `SMALL_CAPSULE`. A bundle pick: `SCROLL_BOXES` (the shipped
  `CardSelectCmd.FromChooseABundleScreen` branch; no offered Ancient relic reaches
  `RelicSelectCmd.FromChooseARelicScreen`, which reports the same `option_choice` kind). Both:
  `NEOWS_BONES`. `ARCANE_SCROLL` is a `Neow` positive relic these seeds never draw, so the table does
  not describe it — the acceptance script says so and fails loudly if a sweep meets a relic the table
  has no entry for.
- **Observed, and the ticket's claim about randomness.** Only four of the 26 offered relics move a
  counter the run counts, and the acceptance asserts the exact deltas: `KALEIDOSCOPE` `Niche` +6,
  `NEW_LEAF` `Niche` +1, `PHIAL_HOLSTER` `CombatPotionGeneration` +4, `NEOWS_BONES` `Niche` +1.
  `NEOWS_BONES` is then checked *compositionally*: its cost is its own curse draw plus exactly what
  each relic its reward set granted costs when the Ancient offers that relic directly — `Niche` +7
  when it grants `KALEIDOSCOPE`, +2 with `NEW_LEAF`, +1 with `LOST_COFFER`/`SILKEN_TRESS`. That is
  the ticket's point made checkable: the nested reward set is not a reimplementation, so a relic
  taken inside one draws what the same relic draws from the Ancient's own offer. This is the
  simulator-side claim only; the shipped-game field-by-field comparison is ticket 15's. The same
  limit applies to criterion 1: the acceptance shows the relic the run holds is the relic the option
  reported and that it arrived with the effect's own extra relics, not that a shipped client's relic
  list is byte-identical.
- **Not changed, deliberately.** The published canonical-state schema still describes only the
  combat shape and has `additionalProperties: false`, so it rejects every run-mode capture, new
  fields included; ticket 05 owns bringing it in line. No schema or hash-schema version was bumped,
  for the same reason. `PROMPT_FREE_CHOICES` was left as the conservative 11-relic subset ticket 03's
  reachability rule uses rather than expanded to the full 15, because expanding it would change which
  choice `leave_ancient` takes and therefore the states several other acceptance scripts record; the
  acceptance script asserts it stays a subset of the relics that really are prompt-free.
- **Acceptance scripts.** All sixteen run-driving scripts were run against the change.
  `ancient_room_acceptance.py`, `run_rest_acceptance.py`, `run_reward_acceptance.py`,
  `run_item_reward_acceptance.py`, `run_option_reward_acceptance.py`, `run_event_acceptance.py`,
  `run_event_combat_acceptance.py`, `run_room_entry_acceptance.py`, `run_room_cycle_acceptance.py`,
  `run_composed_utility_rooms_acceptance.py`, `run_map_acceptance.py`, `portable_modes_acceptance.py`,
  `act_variant_acceptance.py` and `choice_acceptance.py` all pass. One does not:
  `run_custom_reward_acceptance.py` fails at its first `worker.restore(ordinary_handle)` with
  `unknown_state_handle`, and **it fails identically on `HEAD` without this change** — verified by
  stashing the change, rebuilding, and reproducing the same failure at the same line. A branch handle
  is invalidated by the `Reset` that every later `_reset` performs (`_branches.Clear()`), and the
  script restores handles minted before two such resets; that is a separate defect in the
  branch/restore contract, not a nested-choice one, and it is recorded here rather than absorbed.
  `python -m pytest tests -q` gives 9 passed, 22 errors, where every error is the documented
  `tmp_path` sandbox refusal and not a test failure; `python -m compileall -q python tests` and
  `pwsh scripts/test-public-tree.ps1` pass.
- **A host fact worth recording for whoever runs these next.** The Godot worker loads GodotHost's
  **Debug** output on this machine, so `scripts/build-persistent-server.ps1 -Configuration Debug` is
  what makes a Core change take effect for `*_acceptance.py`; the default `Release` build alone
  leaves the worker running the previous code. Both were built here.


