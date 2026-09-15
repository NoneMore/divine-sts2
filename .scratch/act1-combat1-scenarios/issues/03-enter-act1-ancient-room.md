# 03: Offer and enter the act-1 Ancient room at run start

**What to build:** A run started in the simulator can be taken through the act-1 Ancient room the way the shipped game takes one: the Ancient node is a legal map action before anything else, travelling to it opens the Ancient's run-start choice, and the choice is a decision the caller can see, with one option per offered choice carrying its index and the relic it grants. Because the room is a real travelled map point rather than a synthesized state, the run's floor bookkeeping advances exactly as the shipped game's does — which is what makes the first combat after it randomised the way the shipped game randomises it.

**Blocked by:** None (can start immediately). Best sequenced after 02, since the Act variant decides which act-1 room set the run plays.

**Status:** done

- [x] At run start, before any other node, the Ancient node is offered among the legal map actions and can be travelled to.
- [x] Entering the Ancient node opens the Ancient's run-start choice as an observable decision, with one legal action per offered choice.
- [x] Each offered choice reports its index and the relic model id it grants, in the order the run offered them.
- [x] For a given run seed, the options offered are the ones a fully unlocked shipped-game run on that seed is offered.
- [x] The Ancient room is entered through the game's own map-point entry, so the run appends the same map-point history entry a shipped run appends.
- [x] After travelling to the Ancient node and then to a row-1 node, the run's floor bookkeeping matches a shipped-game run at the same point, and the first combat's randomised monster composition matches.
- [x] The player's HP when leaving the Ancient room is what a fully unlocked shipped-game run has, including the Ascension that reduces the Ancient's heal.
- [x] Entering the Ancient room consumes no randomness shared with the map, the encounter choice or a combat stream.

## Comments

**2026-09-16 — implemented.**

- `BuildMapActions` now offers `ActMap.StartingMapPoint` while the run has not travelled, instead of
  the starting point's children. That is the shipped map screen's own rule
  (`NMapScreen.RecalculateTravelability` marks the starting node travelable while
  `VisitedMapCoords` is empty, then `MapTravel.GetTravelablePointsFrom` marks its children), and the
  starting point is the act's Ancient on a fully unlocked run — `StandardActMap` types it `Ancient`
  and `RunManager.GenerateMap` only retypes it to `Monster` when the act's Ancient is not spawned.
  No new travel path was added: `choose_map:3:0` goes through `EnterMapPointInternal(1, Ancient, ...)`,
  which is what appends the history entry, advances `ActFloor` to 1 and creates the room through
  `CreateRoom(RoomType.Event, Ancient) → ActModel.PullAncient()`.
- The entry could return before the event had generated its first page: `EventRoom.EnterInternal`
  starts the event with `TaskHelper.RunSafely`, so `AwaitEventStartedAsync` yields until the event is
  decidable (an option is offered or it has finished), and fails the entry with
  `event_not_started` if it never becomes so. It runs on every run-mode Event-room entry, because
  "wait until the event is decidable" is a property of entering an event room rather than of the
  Ancient.
- `BuildEventActions` and the event observation now report `relic_model_id` for every offered choice
  (`EventOption.Relic`, the relic the choice grants), alongside the `option_index` they already
  reported. A legal action per selectable offered choice, in the order `CurrentOptions` offers them.
  The field is reported for every event, not only the Ancient's, because it is a fact about an
  `EventOption`; the ticket's claim is about the Ancient's choices.
- `scoring_features.total_floor` (`RunState.TotalFloor`) is new: it is the floor counter the Ancient
  room advances, and it is what `EncounterModel.GenerateMonstersWithSlots` seeds the per-encounter
  generator with. Ticket 05 still owns putting it on the combat observation and bumping the schema
  versions; this is the additive scoring-features field the acceptance reads it from, so no published
  observation shape changed.
- **Observed** with the shipped game (assembly `A1F9E653F1E28E4076558FEE1E60D218619CB7E057B887C6417F62C62C6D7A52`)
  through the Godot-hosted native worker, by the new `python/ancient_room_acceptance.py`, on 15 sample
  runs (13 seeds, one at Ascension 2, one wounded start) plus a 37-seed offer sweep:
  - a run at its start offers exactly one legal action, `choose_map:3:0` with `point_type: "Ancient"`;
    the room it opens is `NEOW` with three choices, each carrying its index and relic in offer order,
    and the legal actions are one per selectable offered choice;
  - the offered relics are the ones an independent port of `Neow.GenerateInitialOptions` produces —
    `Neow`'s declared option pools, the single-player `MassiveScroll` exclusion, the four
    curse/pair conditionals, the three `NextBool` pairs and `UnstableShuffle`, over the event
    generator `EventModel.BeginEvent` keys on the run seed. The script checks that port against the
    live run for 37 seeds (`_OFFER_SWEEP`: the 24 `ANCIENT*` seeds and the 13 `ACTVARIANT*` seeds,
    both Act variants included), and it agrees on all of them;
  - every one of the run's named RNG counters and the map it generated are identical before and after
    entering the Ancient room, while `TotalFloor` goes 0 → 1, and 2 after the row-1 node;
  - `SlimesWeak` seeds' first fight is the composition the ported generator produces at
    `TotalFloor == 2`, and the port reproduces the recorded `TotalFloor == 1` composition of the same
    seeds (a second, independent observation of the same generator), so the composition moved because
    the floor did; fixed-composition encounters are unchanged, and one seed's composition legitimately
    stays put because the generator yields the same order at both floors;
  - the HP is read from the map state the run reaches *after* leaving the room: full at Ascension 0,
    `WearyTraveler`'s 0.8 × max (80 → 64) at Ascension 2, and 80 from a start of 10 for the wounded
    sample, which is the only sample where healing to full is distinguishable from not healing;
  - a second worker reaches the same state hashes, and restoring the Ancient-room and first-fight
    branches reproduces them.
- **Observed**, and worth recording for ticket 15: entering the Ancient room advances `eventsVisited`,
  because the room is an `EventRoom` and `RunManager.EnterRoomInternal` calls
  `State.Act.MarkRoomVisited(room.RoomType)`. It consumes no RNG draw, so the spec's "skipping the
  Ancient room does not shift any RNG stream" still holds, but the act's ordered event pool is one
  entry further along: with the Ancient room entered, the first unknown node opens the second event
  the pool offers. That is the shipped behaviour, and it is why `run_room_cycle_acceptance.py` and
  `run_event_combat_acceptance.py` meet a different event than before.
- **A nested prompt the simulator cannot yet drive.** Choosing `NEOWS_BONES` reaches a
  `custom_reward_choice` and then a second reward set, which `CaptureRewardsScreen` refuses with
  `nested_reward_collision` ("a second native reward set began before the first was resolved"). Before
  this ticket the Ancient room was never entered, so the path was unreachable; it is ticket 04's
  nested-choice work. That came out of a de-risking probe that took every offered choice on 37 seeds
  and walked the first legal action each step; the probe is not kept, and every choice except
  `NEOWS_BONES` reached the map — plain relic pick-ups, card selects
  (`FromDeckForRemoval`, `FromChooseACardScreen`, `FromDeckForTransform`, `FromDeckForUpgrade`),
  bundle picks and custom-reward chains four reward sets deep.
- **Acts 2 and 3 change with it.** `StandardActMap` types every act's starting point `Ancient`, and
  the map each new act generates clears the visited coordinates, so advancing an act now offers that
  act's Ancient as the first map action too — which is what the shipped game shows, and which the
  spec leaves out of scope for this feature's claims. Verified by
  `run_seeded_full_act_corpus.py --seeds 1`, which completes an act and then walks the next one's
  Ancient and fourteen further rows without a protocol error. Standalone map mode shares
  `BuildMapActions`, so its first offer is the map's starting point too.
- **Acceptance scripts.** `run_room_entry_acceptance.py`, `run_room_cycle_acceptance.py`,
  `run_composed_utility_rooms_acceptance.py`, `run_event_combat_acceptance.py` and
  `search_coordinator_acceptance.py` all drove a run from its start, so all five had to leave through
  the Ancient room. All five were already failing on `HEAD` — verified by running each `HEAD` copy
  against the pre-change build — because the fully-unlocked baseline and the Act-variant roll had
  invalidated their recorded expectations; they now pass, except `search_coordinator_acceptance.py`,
  which this host cannot finish because `NativeTorchValueScorer.load` needs the optional `torch`
  extra. `run_map_acceptance.py` (the standalone map mode) and `portable_modes_acceptance.py` also
  still pass. `run_room_cycle_acceptance.py` no longer names the event its unknown node opens, or
  asserts that it opens a nested card select: the event that seed now meets is a different one, so it
  drives whatever it opens and asserts the run comes back to the map.
- New shared Python: `sts2_native_sim/shipped_rng.py` holds the seed-hash/`MegaRandom`/`Rng` ports
  that `act_variant_acceptance.py` used to carry privately (it now imports them and still passes), and
  `sts2_native_sim/ancient.py` holds what every run-driving script needs — finding the Ancient map
  action, leaving the room and resetting a pool of workers past it.

