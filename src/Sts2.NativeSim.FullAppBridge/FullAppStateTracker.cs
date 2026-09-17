using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.RestSite;
using MegaCrit.Sts2.Core.Entities.Rngs;
using MegaCrit.Sts2.Core.Events;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves.Runs;

namespace Sts2.NativeSim.FullAppBridge;

public static class FullAppStateTracker
{
    private static readonly JsonSerializerOptions JsonOptions = BridgeJson.Options;

    /// <summary>
    /// The bridge's card identities, so a card reported in one observation is the same card in the
    /// next. Card instance ids are the encoder's own, so nothing else can supply them.
    /// </summary>
    private static readonly CardIdentityRegistry CardIdentities = new();

    public static (ObservationDto Observation, List<LegalActionDto> LegalActions) CreateStateSnapshot(
        string phase,
        bool isTerminal,
        bool isVictory,
        object? contextObject = null)
    {
        RunManager? runManager = RunManager.Instance;
        CombatManager? combatManager = CombatManager.Instance;
        RunState? runState = runManager?.DebugOnlyGetState();
        Player? player = runState is not null ? LocalContext.GetMe(runState) : null;

        var obs = new ObservationDto
        {
            Phase = phase,
            IsTerminal = isTerminal,
            IsVictory = isVictory,
            GameBuild = GameBuild.Current,
            Character = player?.Character.Id.Entry ?? "",
            PlayerHp = player?.Creature.CurrentHp ?? 0,
            PlayerMaxHp = player?.Creature.MaxHp ?? 0,
            PlayerBlock = player?.Creature.Block ?? 0,
            PlayerEnergy = player?.PlayerCombatState?.Energy ?? 0,
        };

        if (runState is not null)
        {
            obs.Run = RunObservation(runState, player);
            // Where the run is — the coordinate the oracle checks it drove the shipped game to, the
            // row-0 Ancient included, and absent only until the run has travelled once.
            if (runState.CurrentMapCoord is { } coord)
            {
                obs.MapCoord = new CoordObservationDto { Col = coord.col, Row = coord.row };
            }
        }

        if (player is not null)
        {
            foreach (var power in player.Creature.Powers)
            {
                obs.PlayerPowers[power.Id.Entry] = power.Amount;
            }

            foreach (var card in player.Deck.Cards)
            {
                obs.DeckCards.Add(card.Id.Entry);
            }
            obs.DeckCards.Sort();

            obs.Inventory = InventoryObservation(player);
        }

        var legalActions = new List<LegalActionDto>();

        if (phase == "combat" && combatManager is not null && combatManager.IsInProgress && player is not null)
        {
            ICombatState? combatState = combatManager.DebugOnlyGetState();
            // The player's own combat state: the scope the bridge's card identities belong to, so a
            // new fight mints its ids from the start again, and the piles this observation walks.
            PlayerCombatState? combatPlayer = player.PlayerCombatState;

            var combatObs = new CombatObservationDto
            {
                // The encounter's own id: the identity `catalog` lists, the trace exporter reports
                // and the simulator's `combat.encounter` carries. A fight that cannot name itself
                // reports none, the way the simulator reports none, rather than an empty string.
                Encounter = combatState?.Encounter?.Id.Entry,
                Turn = player.PlayerCombatState?.TurnNumber ?? 1,
                // The granular turn phase, in the shipped enum's own words — the same word the
                // simulator reports on `combat.phase`. `python/sts2_native_sim/decision_vocabulary.py`
                // is the one place that says which decision kind each word is a boundary for.
                Phase = player.PlayerCombatState?.Phase.ToString() ?? "",
                Energy = player.PlayerCombatState?.Energy ?? 0,
                MaxEnergy = player.PlayerCombatState?.MaxEnergy ?? 0,
                Stars = player.PlayerCombatState?.Stars ?? 0,
                // The five combat piles as their ordered contents. A draw pile's order is what a
                // policy learns from, and it is invisible in a count, so nothing here counts.
                Piles = combatPlayer is null
                    ? new List<PileObservationDto>()
                    : CombatPiles(combatPlayer).Select(pile => PileObservation(combatPlayer, pile.Name, pile.Pile)).ToList(),
            };

            // Every creature, the player's own row included, in the native order the simulator and
            // the trace exporter both report — the player is a creature with a side, not only a
            // set of flattened scalars.
            if (combatState is not null)
            {
                foreach (Creature creature in combatState.Creatures)
                {
                    combatObs.Creatures.Add(CreatureObservation(creature));
                }
            }

            var handCards = combatPlayer is null ? Array.Empty<CardModel>() : combatPlayer.Hand.Cards;
            for (int i = 0; i < handCards.Count; i++)
            {
                CardModel card = handCards[i];
                bool canPlay = card.CanPlay();
                if (canPlay)
                {
                    if (card.TargetType.IsSingleTarget() && card.TargetType != TargetType.Self)
                    {
                        var hittable = card.CombatState?.HittableEnemies.OrderBy(c => c.CombatId) ?? Enumerable.Empty<Creature>();
                        foreach (var enemy in hittable)
                        {
                            ulong enemyId = enemy.CombatId ?? 0;
                            legalActions.Add(new LegalActionDto
                            {
                                ActionId = $"play_card:{i}:target:{enemyId}",
                                ActionType = "play_card",
                                Description = $"Play {card.Id.Entry} targeting enemy {enemyId} ({enemy.CurrentHp}/{enemy.MaxHp})",
                                Metadata = new Dictionary<string, object?> { ["card_index"] = i, ["target_id"] = enemyId, ["card_id"] = card.Id.Entry }
                            });
                        }
                    }
                    else
                    {
                        legalActions.Add(new LegalActionDto
                        {
                            ActionId = $"play_card:{i}",
                            ActionType = "play_card",
                            Description = $"Play {card.Id.Entry}",
                            Metadata = new Dictionary<string, object?> { ["card_index"] = i, ["card_id"] = card.Id.Entry }
                        });
                    }
                }
            }

            for (int slot = 0; slot < player.PotionSlots.Count; slot++)
            {
                PotionModel? potion = player.PotionSlots[slot];
                if (potion is null) continue;
                if (potion.TargetType == TargetType.AnyEnemy)
                {
                    var hittable = player.Creature.CombatState?.HittableEnemies.OrderBy(c => c.CombatId) ?? Enumerable.Empty<Creature>();
                    foreach (var enemy in hittable)
                    {
                        ulong enemyId = enemy.CombatId ?? 0;
                        legalActions.Add(new LegalActionDto
                        {
                            ActionId = $"use_potion:{slot}:target:{enemyId}",
                            ActionType = "use_potion",
                            Description = $"Use potion {potion.Id.Entry} on enemy {enemyId}",
                            Metadata = new Dictionary<string, object?> { ["potion_index"] = slot, ["potion_id"] = potion.Id.Entry, ["target_id"] = enemyId }
                        });
                    }
                }
                else if (potion.TargetType is TargetType.AnyAlly or TargetType.AnyPlayer or TargetType.Self)
                {
                    ulong playerId = player.Creature.CombatId ?? 0;
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"use_potion:{slot}:target:{playerId}",
                        ActionType = "use_potion",
                        Description = $"Use potion {potion.Id.Entry} on player {playerId}",
                        Metadata = new Dictionary<string, object?> { ["potion_index"] = slot, ["potion_id"] = potion.Id.Entry, ["target_id"] = playerId }
                    });
                }
                else
                {
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"use_potion:{slot}",
                        ActionType = "use_potion",
                        Description = $"Use potion {potion.Id.Entry}",
                        Metadata = new Dictionary<string, object?> { ["potion_index"] = slot, ["potion_id"] = potion.Id.Entry }
                    });
                }
            }

            legalActions.Add(new LegalActionDto
            {
                ActionId = "end_turn",
                ActionType = "end_turn",
                Description = "End player turn",
            });

            obs.Combat = combatObs;
        }
        else if (phase == "map")
        {
            var roomObs = new RoomObservationDto { RoomType = "Map" };
            if (contextObject is List<MapPoint> reachablePoints)
            {
                for (int i = 0; i < reachablePoints.Count; i++)
                {
                    MapPoint point = reachablePoints[i];
                    string typeName = point.PointType.ToString();
                    int branch1Indexed = i + 1;
                    roomObs.Options.Add($"{branch1Indexed}:{typeName}");
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_map:{branch1Indexed}:{typeName}",
                        ActionType = "choose_map",
                        Description = $"{branch1Indexed} ({typeName})",
                        Metadata = new Dictionary<string, object?> { ["branch_choice"] = branch1Indexed, ["node_index"] = i, ["room_type"] = typeName }
                    });
                }
            }
            obs.Room = roomObs;
        }
        else if (phase == "card_reward")
        {
            var roomObs = new RoomObservationDto { RoomType = "CardReward" };
            if (contextObject is IReadOnlyList<CardModel> cardOptions)
            {
                for (int i = 0; i < cardOptions.Count; i++)
                {
                    CardModel card = cardOptions[i];
                    roomObs.Options.Add(card.Id.Entry);
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_card:{i}:{card.Id.Entry}",
                        ActionType = "choose_card",
                        Description = $"Choose card reward {card.Id.Entry} (Cost: {card.EnergyCost.Canonical})",
                        Metadata = new Dictionary<string, object?> { ["card_index"] = i, ["card_id"] = card.Id.Entry, ["upgrades"] = card.CurrentUpgradeLevel }
                    });
                }
                legalActions.Add(new LegalActionDto
                {
                    ActionId = "skip_card",
                    ActionType = "skip_card",
                    Description = "Skip card reward selection",
                });
            }
            obs.Room = roomObs;
        }
        else if (phase == "rewards")
        {
            var roomObs = new RoomObservationDto { RoomType = "Rewards" };
            if (contextObject is IEnumerable<object> rewards)
            {
                int idx = 0;
                foreach (var r in rewards)
                {
                    string rewardType = r.GetType().Name.Replace("Reward", "");
                    roomObs.Options.Add($"{idx}:{rewardType}");
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_reward:{idx}:{rewardType}",
                        ActionType = "choose_reward",
                        Description = $"Claim {rewardType} reward",
                        Metadata = new Dictionary<string, object?> { ["reward_index"] = idx, ["reward_type"] = rewardType }
                    });
                    idx++;
                }

            }

            legalActions.Add(new LegalActionDto
            {
                ActionId = "proceed",
                ActionType = "proceed",
                Description = "Proceed to next screen / room",
            });
            obs.Room = roomObs;
        }
        else if (phase == "rest_site")
        {
            var roomObs = new RoomObservationDto { RoomType = "RestSite" };
            if (contextObject is IReadOnlyList<RestSiteOption> restOptions)
            {
                for (int i = 0; i < restOptions.Count; i++)
                {
                    RestSiteOption opt = restOptions[i];
                    string key = opt.OptionId;
                    roomObs.Options.Add(key);
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_rest:{key}",
                        ActionType = "choose_rest",
                        Description = $"Rest Site Option: {key}",
                        Metadata = new Dictionary<string, object?> { ["option_key"] = key }
                    });
                }
            }
            obs.Room = roomObs;
        }
        else if (phase == "deck_upgrade")
        {
            var roomObs = new RoomObservationDto { RoomType = "DeckUpgrade" };
            if (contextObject is IReadOnlyList<CardModel> upgradableCards)
            {
                for (int i = 0; i < upgradableCards.Count; i++)
                {
                    CardModel card = upgradableCards[i];
                    roomObs.Options.Add(card.Id.Entry);
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_upgrade:{i}:{card.Id.Entry}",
                        ActionType = "choose_upgrade",
                        Description = $"Upgrade {card.Id.Entry}",
                        Metadata = new Dictionary<string, object?> { ["card_index"] = i, ["card_id"] = card.Id.Entry }
                    });
                }
            }
            obs.Room = roomObs;
        }
        else if (phase == "deck_card_select")
        {
            var roomObs = new RoomObservationDto { RoomType = "DeckCardSelect" };
            if (contextObject is IReadOnlyList<CardModel> selectableCards)
            {
                for (int i = 0; i < selectableCards.Count; i++)
                {
                    CardModel card = selectableCards[i];
                    roomObs.Options.Add(card.Id.Entry);
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_card_select:{i}:{card.Id.Entry}",
                        ActionType = "choose_card_select",
                        Description = $"Select {card.Id.Entry}",
                        Metadata = new Dictionary<string, object?> { ["card_index"] = i, ["card_id"] = card.Id.Entry }
                    });
                }
            }
            obs.Room = roomObs;
        }
        else if (phase == "shop")
        {
            var roomObs = new RoomObservationDto { RoomType = "Shop" };
            if (contextObject is IEnumerable<object> merchantEntries)
            {
                int idx = 0;
                foreach (var entry in merchantEntries)
                {
                    string entryType = entry.GetType().Name.Replace("MerchantEntry", "");
                    string itemId = entry switch
                    {
                        MerchantCardEntry cardEntry => cardEntry.CreationResult?.Card?.Id.Entry ?? "UNKNOWN_CARD",
                        MerchantRelicEntry relicEntry => relicEntry.Model?.Id.Entry ?? "UNKNOWN_RELIC",
                        MerchantPotionEntry potionEntry => potionEntry.Model?.Id.Entry ?? "UNKNOWN_POTION",
                        _ => entryType,
                    };
                    int? price = entry is MerchantEntry merchantEntry ? merchantEntry.Cost : null;
                    bool affordable = entry is not MerchantEntry pricedEntry || pricedEntry.EnoughGold;
                    bool stocked = entry is not MerchantEntry stockEntry || stockEntry.IsStocked;
                    roomObs.Options.Add($"{idx}:{entryType}:{itemId}:{price}");
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"shop_buy:{idx}:{entryType}",
                        ActionType = "shop_buy",
                        Description = $"Buy {itemId} ({entryType}) for {price} gold",
                        Metadata = new Dictionary<string, object?>
                        {
                            ["slot_index"] = idx,
                            ["entry_type"] = entryType,
                            ["item_id"] = itemId,
                            ["price"] = price,
                            ["affordable"] = affordable,
                            ["stocked"] = stocked,
                        }
                    });
                    idx++;
                }
            }

            legalActions.Add(new LegalActionDto
            {
                ActionId = "shop_leave",
                ActionType = "shop_leave",
                Description = "Leave merchant shop",
            });
            obs.Room = roomObs;
        }
        else if (phase == "event")
        {
            var roomObs = new RoomObservationDto { RoomType = "Event" };
            if (contextObject is IEnumerable<object> eventOptions)
            {
                int idx = 0;
                foreach (var opt in eventOptions)
                {
                    roomObs.Options.Add(idx.ToString());
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_event:{idx}",
                        ActionType = "choose_event",
                        Description = $"Choose event option {idx}",
                        Metadata = new Dictionary<string, object?> { ["option_index"] = idx }
                    });
                    idx++;
                }
            }

            legalActions.Add(new LegalActionDto
            {
                ActionId = "proceed",
                ActionType = "proceed",
                Description = "Proceed with event",
            });
            obs.Room = roomObs;
        }
        else if (phase == "treasure")
        {
            var roomObs = new RoomObservationDto { RoomType = "Treasure" };
            legalActions.Add(new LegalActionDto
            {
                ActionId = "proceed",
                ActionType = "proceed",
                Description = "Open chest, collect relics and proceed",
            });
            obs.Room = roomObs;
        }
        else if (phase == "victory" || phase == "game_over")
        {
            var roomObs = new RoomObservationDto { RoomType = phase == "victory" ? "Victory" : "GameOver" };
            legalActions.Add(new LegalActionDto
            {
                ActionId = "proceed",
                ActionType = "proceed",
                Description = phase == "victory" ? "Victory! Proceed to next Act" : "Game Over",
            });
            obs.Room = roomObs;
        }

        obs.StateHash = ComputeHash(obs);
        return (obs, legalActions);
    }

    /// <summary>
    /// The run block, worded exactly as the simulator words the same block on a combat observation,
    /// so the two compare field by field. The act index is the run's own zero-based
    /// <c>CurrentActIndex</c> — the base the map observation and the scoring features report — with
    /// the Act variant beside it, so neither has to be re-derived by a comparison.
    /// </summary>
    private static RunObservationDto RunObservation(RunState runState, Player? player)
    {
        return new RunObservationDto
        {
            Seed = runState.Rng.StringSeed,
            Ascension = runState.AscensionLevel,
            Gold = player?.Gold ?? 0,
            // The Act model in play, which the run seed rolls: two variants of one act index share
            // its map topology and not its encounter, event or boss pools.
            ActVariant = runState.Act.Id.Entry,
            ActIndex = runState.CurrentActIndex,
            ActFloor = runState.ActFloor,
            // The map points the run has travelled, so it is the floor the Ancient room advances and
            // the counter the per-encounter generator is seeded with.
            TotalFloor = runState.TotalFloor,
            RngCounters = RunRngCounters(runState),
        };
    }

    /// <summary>
    /// The run's named RNG counters, keyed by the game's own counter names — the same names the
    /// simulator's worker and the trace exporter report, because both read the same set and key it
    /// the same way. Ordered by name, as they order it, so two captures of one state read alike.
    /// </summary>
    private static SortedDictionary<string, int> RunRngCounters(RunState runState)
    {
        SortedDictionary<string, int> counters = new(StringComparer.Ordinal);
        foreach (KeyValuePair<RunRngType, int> counter in runState.Rng.ToSerializable().Counters)
        {
            counters[counter.Key.ToString()] = counter.Value;
        }
        return counters;
    }

    /// <summary>
    /// The run's relics and potions as objects, worded as the simulator's inventory block words them.
    /// A relic is reported in the order the run holds it, with the counter it shows and its own saved
    /// state; a potion is reported by the slot it sits in, and an empty slot keeps its place as a
    /// null entry so no slot index is renumbered away.
    /// </summary>
    private static InventoryObservationDto InventoryObservation(Player player)
    {
        var inventory = new InventoryObservationDto();

        foreach (RelicModel relic in player.Relics)
        {
            inventory.Relics.Add(RelicObservation(relic));
        }

        for (int slot = 0; slot < player.PotionSlots.Count; slot++)
        {
            PotionModel? potion = player.PotionSlots[slot];
            // An occupied slot carries its position and its model and nothing else, which is the whole
            // of what the shipped potion saves; the empty slot beside it keeps its place as a null.
            inventory.Potions.Add(potion is null ? null : new PotionObservationDto { Slot = slot, ModelId = potion.Id.Entry });
        }

        return inventory;
    }

    /// <summary>
    /// One relic row. The counter is present only when the relic shows one, which is how the game
    /// itself reports the two cases rather than a zero standing in for "none".
    /// </summary>
    private static RelicObservationDto RelicObservation(RelicModel relic)
    {
        return new RelicObservationDto
        {
            ModelId = relic.Id.Entry,
            Counter = relic.ShowCounter ? relic.DisplayAmount : null,
            NativeState = SavedNativeState(relic),
        };
    }

    /// <summary>
    /// One creature row, worded exactly as the simulator words the same row in its own per-combat
    /// projection, so the two compare field by field. Every member read here is a public member of
    /// the game assembly this mod already references; nothing is reached by reflection, and nothing
    /// reaches into the simulator's own assembly.
    /// </summary>
    private static CreatureObservationDto CreatureObservation(Creature creature)
    {
        var row = new CreatureObservationDto
        {
            CombatId = creature.CombatId,
            ModelId = creature.ModelId.Entry,
            Side = creature.Side.ToString(),
            Hp = creature.CurrentHp,
            MaxHp = creature.MaxHp,
            Block = creature.Block,
            Alive = creature.IsAlive,
        };

        MoveState? move = creature.Monster?.NextMove;
        if (move is not null)
        {
            var nextMove = new NextMoveObservationDto { Id = move.Id };
            foreach (AbstractIntent intent in move.Intents)
            {
                var intentRow = new IntentObservationDto
                {
                    IntentType = intent.IntentType.ToString(),
                    Implementation = intent.GetType().Name,
                };
                if (intent is AttackIntent attack)
                {
                    // The damage the shipped hook chain resolves the intent to, which is what the
                    // game displays. The simulator calls the very same method on the same intent.
                    intentRow.Damage = attack.GetSingleDamage(creature.CombatState?.Allies ?? [], creature);
                    intentRow.Repeats = attack.Repeats;
                }
                nextMove.Intents.Add(intentRow);
            }
            row.NextMove = nextMove;
        }

        foreach (PowerModel power in creature.Powers)
        {
            row.Powers.Add(new PowerObservationDto { ModelId = power.Id.Entry, Amount = power.Amount });
        }

        return row;
    }

    /// <summary>
    /// The five combat piles, in the order the simulator and the trace exporter report them: the
    /// hand first, then every pile a card can move to, and the play pile — a card mid-play, which no
    /// earlier bridge projection represented at all — last.
    /// </summary>
    private static IReadOnlyList<(string Name, CardPile Pile)> CombatPiles(PlayerCombatState state) =>
    [
        ("Hand", state.Hand),
        ("DrawPile", state.DrawPile),
        ("DiscardPile", state.DiscardPile),
        ("ExhaustPile", state.ExhaustPile),
        ("PlayPile", state.PlayPile),
    ];

    /// <summary>
    /// One pile as its ordered contents. The name is the bridge's, so a caller finds the hand or the
    /// draw pile by the same word the simulator uses; the type is the game's own word for the pile
    /// that was walked, so the pairing of a name and a type is the game's rather than the bridge's.
    /// </summary>
    private static PileObservationDto PileObservation(PlayerCombatState fight, string name, CardPile pile)
    {
        var row = new PileObservationDto
        {
            Name = name,
            Type = pile.Type.ToString(),
        };
        foreach (CardModel card in pile.Cards)
        {
            row.Cards.Add(CardObservation(fight, card));
        }
        return row;
    }

    /// <summary>
    /// One card row, worded exactly as the simulator words the same row in its own pile projection,
    /// so two encoders' cards for one situation compare field by field. Every member read here is a
    /// public member of the game assembly this mod already references; nothing reaches into the
    /// simulator's own assembly.
    /// </summary>
    private static CardObservationDto CardObservation(PlayerCombatState fight, CardModel card)
    {
        return new CardObservationDto
        {
            // The bridge's own identity, because a card instance belongs to whichever encoder
            // produced the state: a comparison treats this one structurally, not literally.
            InstanceId = CardIdentities.IdFor(fight, card),
            // An identity the game itself mints, so a comparison treats this one literally.
            NetId = NetCombatCardDb.Instance.GetCardId(card),
            ModelId = card.Id.Entry,
            CardType = card.Type.ToString(),
            TargetType = card.TargetType.ToString(),
            // The cost the other projections report — what the card would be played for, modifiers
            // included — rather than the card's own canonical number, so two projections of one card
            // cannot disagree about it.
            EnergyCost = card.EnergyCost.GetResolved(),
            CostsX = card.EnergyCost.CostsX,
            // The upgrade level the card actually carries, which the hand used to declare and never
            // populate.
            Upgrades = card.CurrentUpgradeLevel,
            Enchantment = card.Enchantment is null ? null : new EnchantmentObservationDto
            {
                ModelId = card.Enchantment.Id.Entry,
                Amount = card.Enchantment.Amount,
            },
            NativeState = SavedNativeState(card),
        };
    }

    /// <summary>
    /// A card's own saved state as the other projections report it: one entry per saved scalar
    /// property, ordered by name, so two encoders' native states for one card compare key by key.
    /// A saved property group that holds models or nested cards is not part of the projection, which
    /// is the group set the simulator's own pile projection reads.
    /// </summary>
    private static SortedDictionary<string, object?> SavedNativeState(CardModel card)
    {
        return SavedScalarState(card.ToSerializable().Props);
    }

    /// <summary>A relic's own saved state, read exactly as a card's is.</summary>
    private static SortedDictionary<string, object?> SavedNativeState(RelicModel relic)
    {
        return SavedScalarState(relic.ToSerializable().Props);
    }

    /// <summary>One model's saved scalar property groups, ordered by property name.</summary>
    private static SortedDictionary<string, object?> SavedScalarState(SavedProperties? props)
    {
        SortedDictionary<string, object?> state = new(StringComparer.Ordinal);
        if (props is null)
        {
            return state;
        }

        AddSavedProperties(props.ints, state);
        AddSavedProperties(props.bools, state);
        AddSavedProperties(props.strings, state);
        AddSavedProperties(props.intArrays, state);
        return state;
    }

    /// <summary>One saved property group's entries, by property name.</summary>
    private static void AddSavedProperties<T>(List<SavedProperties.SavedProperty<T>>? properties, SortedDictionary<string, object?> state)
    {
        if (properties is null)
        {
            return;
        }

        foreach (SavedProperties.SavedProperty<T> property in properties)
        {
            state[property.name] = property.value;
        }
    }

    private static string ComputeHash(ObservationDto obs)
    {
        string json = JsonSerializer.Serialize(obs, JsonOptions);
        byte[] bytes = SHA256.HashData(Encoding.UTF8.GetBytes(json));
        return Convert.ToHexString(bytes);
    }
}
