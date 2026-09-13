using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Orbs;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.RestSite;
using MegaCrit.Sts2.Core.Entities.Rewards;
using MegaCrit.Sts2.Core.Events;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves.Runs;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// Read-only projection of the shipped application's run and combat state.
///
/// Everything here only reads shipped objects; nothing mutates the game, touches a visible window,
/// or depends on presentation state. The `run` and `combat` projections are field-for-field
/// comparable with the reconstructed fast path's observation, which is what
/// `docs/first-combat-scene-generation-plan.md` E5 requires for the golden differential.
/// </summary>
public static class FullAppStateTracker
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = false };

    private static readonly string[] PileNames = { "Hand", "DrawPile", "DiscardPile", "ExhaustPile", "PlayPile" };

    /// <summary>
    /// Boundaries whose state must include the combat projection even after the shipped combat
    /// manager has finished: the post-combat terminal boundary and the run's end after a death.
    /// </summary>
    private static bool IsCombatBearingPhase(string phase) =>
        phase is "combat" or "combat_complete" or "game_over" or "victory";

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

        // A nested choice can open while a room decision is still live (a Neow blessing inside the
        // event, a relic's card choice during combat start), so the ambient room projection is built
        // from the last non-choice phase. A choice that interrupts a combat room is combat-bearing even
        // before the shipped combat manager reports itself "in progress", which is why the live room is
        // part of the test; every other boundary keeps the phase-only classification so a combat
        // room's reward screens still project as rewards.
        BridgePendingChoice? pendingChoice = FullAppBridgeServer.PendingChoice;
        string roomPhase = pendingChoice is not null ? FullAppBridgeServer.CurrentPhase : phase;
        bool combatBearing = IsCombatBearingPhase(roomPhase)
            || (pendingChoice is not null && runState?.CurrentRoom is CombatRoom);

        ICombatState? combatState = combatManager is not null && combatManager.IsInProgress ? combatManager.DebugOnlyGetState() : null;
        if (combatState is null && combatBearing && player?.Creature.CombatState is { } attachedCombat)
        {
            // The combat state stays attached to the player's creature after the shipped combat manager
            // finishes (the terminal boundary) and while a pre-turn choice interrupts it at combat start.
            combatState = attachedCombat;
        }

        var obs = new ObservationDto
        {
            GameBuild = FullAppBuildIdentity.Value,
            Phase = phase,
            IsTerminal = isTerminal,
            IsVictory = isVictory,
            Seed = runState?.Rng.StringSeed ?? "",
            Character = player?.Character.Id.Entry ?? "",
            Ascension = runState?.AscensionLevel ?? 0,
            Act = (runState?.CurrentActIndex ?? 0) + 1,
            Floor = runState?.TotalFloor ?? 0,
            Gold = player?.Gold ?? 0,
            PlayerHp = player?.Creature.CurrentHp ?? 0,
            PlayerMaxHp = player?.Creature.MaxHp ?? 0,
            PlayerBlock = player?.Creature.Block ?? 0,
            PlayerEnergy = player?.PlayerCombatState?.Energy ?? 0,
        };

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

            foreach (var relic in player.Relics)
            {
                obs.Relics.Add(relic.Id.Entry);
            }

            for (int slot = 0; slot < player.PotionSlots.Count; slot++)
            {
                var pot = player.PotionSlots[slot];
                if (pot is not null)
                {
                    obs.Potions.Add(pot.Id.Entry);
                }
            }
        }

        var legalActions = new List<LegalActionDto>();
        string decisionKind = pendingChoice?.DecisionKind ?? (phase == "combat" ? "combat_action" : phase);

        if (runState is not null && player is not null)
        {
            obs.Run = BuildRunProjection(runState, player);
        }

        if (pendingChoice is not null)
        {
            obs.OutstandingChoice = BuildChoiceProjection(pendingChoice);
            foreach (var action in BuildChoiceActions(pendingChoice))
            {
                legalActions.Add(action);
            }
        }

        // A nested choice can open while a room decision is still live (a Neow blessing inside the
        // event, a relic's card choice during combat start), so the ambient room projection is built
        // from the last non-choice phase; `combatBearing` above resolves both cases.
        if (combatBearing && combatState is not null && player is not null)
        {
            BuildCombatProjection(obs, combatState, player);
            if (roomPhase == "combat" && pendingChoice is null)
            {
                legalActions.AddRange(BuildCombatActions(combatState, player));
            }
        }
        else if (roomPhase == "map")
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
                    roomObs.Details[$"option_{i}"] = new Dictionary<string, object?>
                    {
                        ["coord"] = new Dictionary<string, object?> { ["col"] = point.coord.col, ["row"] = point.coord.row },
                        ["point_type"] = typeName,
                    };
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_map:{branch1Indexed}:{typeName}",
                        ActionType = "choose_map",
                        Description = $"{branch1Indexed} ({typeName})",
                        Metadata = new Dictionary<string, object?>
                        {
                            ["branch_choice"] = branch1Indexed,
                            ["node_index"] = i,
                            ["room_type"] = typeName,
                            ["col"] = point.coord.col,
                            ["row"] = point.coord.row,
                        }
                    });
                }
            }
            obs.Room = roomObs;
        }
        else if (roomPhase == "card_reward")
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
                        Metadata = new Dictionary<string, object?>
                        {
                            ["card_index"] = i,
                            ["card_id"] = card.Id.Entry,
                            ["upgrades"] = card.CurrentUpgradeLevel,
                            ["native_state"] = SavedNativeState(card),
                        }
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
        else if (roomPhase == "rewards")
        {
            var roomObs = new RoomObservationDto { RoomType = "Rewards" };
            RewardsRoomContext? rewardsContext = contextObject as RewardsRoomContext;
            IReadOnlyList<object>? rewards = rewardsContext?.Rewards
                ?? (contextObject is IEnumerable<object> legacyRewards ? legacyRewards.ToList() : null);
            bool proceedEnabled = rewardsContext?.ProceedEnabled ?? true;
            roomObs.Details["proceed_enabled"] = proceedEnabled;
            roomObs.Details["proceed_is_skip"] = rewardsContext?.ProceedIsSkip ?? false;
            if (rewards is not null)
            {
                int idx = 0;
                foreach (var r in rewards)
                {
                    string rewardType = r.GetType().Name.Replace("Reward", "");
                    roomObs.Options.Add($"{idx}:{rewardType}");
                    var metadata = new Dictionary<string, object?> { ["reward_index"] = idx, ["reward_type"] = rewardType };
                    if (RewardModelId(r) is { } modelId) metadata["model_id"] = modelId;

                    if (r is CardReward cardReward)
                    {
                        // A card reward is a second screen: the shipped game opens it with `choose_reward`
                        // and then waits for one of the offered cards. The reconstructed environment
                        // exposes the offered cards directly as claims, so project the same fused decision
                        // here; the two native steps stay a coordinator detail of `step`.
                        var offered = CardRewardCards(cardReward);
                        if (offered.Count == 0)
                        {
                            throw new InvalidOperationException(
                                $"card reward {idx} is not populated, so its claim actions cannot be projected");
                        }
                        for (int option = 0; option < offered.Count; option++)
                        {
                            CardModel card = offered[option];
                            var claimMetadata = new Dictionary<string, object?>(metadata)
                            {
                                ["option_index"] = option,
                                ["card_id"] = card.Id.Entry,
                                ["model_id"] = card.Id.Entry,
                                ["upgrades"] = card.CurrentUpgradeLevel,
                            };
                            legalActions.Add(new LegalActionDto
                            {
                                ActionId = $"choose_reward:{idx}:{rewardType}:{option}:{card.Id.Entry}",
                                ActionType = "choose_reward",
                                Description = $"Claim {rewardType} reward card {card.Id.Entry}",
                                Metadata = claimMetadata,
                            });
                        }
                        foreach (var alternative in CardRewardAlternatives(cardReward))
                        {
                            // A state-changing alternative (reroll, or a relic-granted sacrifice) is a real
                            // decision the reconstructed environment does not model. Project it under its own
                            // action type so the comparator fails loudly instead of silently ignoring it.
                            legalActions.Add(new LegalActionDto
                            {
                                ActionId = $"card_reward_alternative:{idx}:{alternative}",
                                ActionType = "card_reward_alternative",
                                Description = $"Card reward {idx} alternative {alternative}",
                                Metadata = new Dictionary<string, object?>
                                {
                                    ["reward_index"] = idx,
                                    ["alternative"] = alternative,
                                },
                            });
                        }
                        idx++;
                        continue;
                    }

                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_reward:{idx}:{rewardType}",
                        ActionType = "choose_reward",
                        Description = $"Claim {rewardType} reward",
                        Metadata = metadata,
                    });
                    idx++;
                }
            }

            if (proceedEnabled)
            {
                legalActions.Add(new LegalActionDto
                {
                    ActionId = "proceed",
                    ActionType = "proceed",
                    Description = "Proceed to next screen / room",
                });
            }
            obs.Room = roomObs;
        }
        else if (roomPhase == "rest_site")
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
        else if (roomPhase == "deck_upgrade")
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
                        Metadata = CardActionMetadata(i, card)
                    });
                }
            }
            obs.Room = roomObs;
        }
        else if (roomPhase == "deck_card_select")
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
                        Metadata = CardActionMetadata(i, card)
                    });
                }
            }
            obs.Room = roomObs;
        }
        else if (roomPhase == "shop")
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
        else if (roomPhase == "event")
        {
            var roomObs = new RoomObservationDto { RoomType = "Event" };
            if (contextObject is EventRoomContext eventContext)
            {
                roomObs.Details["model_id"] = eventContext.ModelId;
                roomObs.Details["finished"] = eventContext.Finished;
                for (int i = 0; i < eventContext.Options.Count; i++)
                {
                    var option = eventContext.Options[i];
                    roomObs.Options.Add(option.TextKey);
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"choose_event:{i}",
                        ActionType = "choose_event",
                        Description = $"Choose event option {i} ({option.TextKey})",
                        Metadata = new Dictionary<string, object?>
                        {
                            ["option_index"] = i,
                            ["text_key"] = option.TextKey,
                            ["is_proceed"] = option.IsProceed,
                        }
                    });
                }
            }
            else if (contextObject is IEnumerable<object> eventOptions)
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
        else if (roomPhase == "treasure")
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
        else if (roomPhase == "victory" || phase == "game_over")
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

        obs.Decision = new DecisionDto { Kind = decisionKind };
        obs.StateHash = ComputeHash(obs);
        return (obs, legalActions);
    }

    /// <summary>The event room's own decision boundary, including every option's shipped `text_key`.</summary>
    public sealed record EventRoomOption(string TextKey, bool IsProceed, bool IsLocked, bool WasChosen);

    public sealed record EventRoomContext(string ModelId, bool Finished, IReadOnlyList<EventRoomOption> Options);

    /// <summary>
    /// The rewards room's decision boundary.
    ///
    /// `NRewardsScreen` exposes one claim button per reward plus one proceed/skip button. That button is
    /// its own decision (it ends the whole reward set), but the shipped game disables it when the set
    /// demands every reward (`RewardsSet.WithSkippingDisallowed`, e.g. the Neow's Bones blessing) or
    /// when the room may not be left yet, so the projection must only advertise it when it is live.
    /// </summary>
    public sealed record RewardsRoomContext(
        IReadOnlyList<object> Rewards,
        bool ProceedEnabled,
        bool ProceedIsSkip);

    private static RunProjectionDto BuildRunProjection(RunState runState, Player player)
    {
        var projection = new RunProjectionDto
        {
            Seed = runState.Rng.StringSeed,
            Character = player.Character.Id.Entry,
            Ascension = runState.AscensionLevel,
            Gold = player.Gold,
            CurrentHp = player.Creature.CurrentHp,
            MaxHp = player.Creature.MaxHp,
            ActIndex = runState.CurrentActIndex,
            ActFloor = runState.ActFloor,
            TotalFloor = runState.TotalFloor,
            ActId = runState.Act?.Id.Entry ?? "",
            PotionCapacity = player.PotionSlots.Count,
        };

        SerializableRunRngSet rngSet = runState.Rng.ToSerializable();
        foreach (var counter in rngSet.Counters)
        {
            projection.RngCounters[counter.Key.ToString()] = counter.Value;
        }

        for (int index = 0; index < player.Deck.Cards.Count; index++)
        {
            projection.Deck.Add(BuildCard(player.Deck.Cards[index], index, "Deck"));
        }

        for (int index = 0; index < player.Relics.Count; index++)
        {
            RelicModel relic = player.Relics[index];
            projection.Relics.Add(new RelicProjectionDto
            {
                Index = index,
                ModelId = relic.Id.Entry,
                Counter = relic.ShowCounter ? relic.DisplayAmount : null,
                NativeState = SavedNativeState(relic),
            });
        }

        for (int slot = 0; slot < player.PotionSlots.Count; slot++)
        {
            PotionModel? potion = player.PotionSlots[slot];
            projection.Potions.Add(potion is null
                ? null
                : new PotionProjectionDto
                {
                    Slot = slot,
                    ModelId = potion.Id.Entry,
                    NativeState = SavedNativeState(potion),
                });
        }

        return projection;
    }

    private static void BuildCombatProjection(ObservationDto obs, ICombatState combatState, Player player)
    {
        PlayerCombatState combatStateForPlayer = player.PlayerCombatState
            ?? throw new InvalidOperationException("The player has no PlayerCombatState during a live combat.");

        var combatObs = new CombatObservationDto
        {
            Turn = combatStateForPlayer.TurnNumber,
            Phase = combatStateForPlayer.Phase.ToString(),
            Energy = combatStateForPlayer.Energy,
            MaxEnergy = combatStateForPlayer.MaxEnergy,
            Stars = combatStateForPlayer.Stars,
        };

        EncounterModel? encounter = combatState.Encounter;
        if (encounter is not null)
        {
            var encounterProjection = new EncounterProjectionDto
            {
                ModelId = encounter.Id.Entry,
                RoomType = encounter.RoomType.ToString(),
            };
            if (encounter.HaveMonstersBeenGenerated)
            {
                foreach (var monster in encounter.SpawnedEnemies)
                {
                    encounterProjection.MonsterModels.Add(monster.Id.Entry);
                }
            }
            encounterProjection.Slots.AddRange(encounter.Slots);
            combatObs.Encounter = encounterProjection;
        }

        IReadOnlyList<Creature> creatures = combatState.Creatures;
        for (int index = 0; index < creatures.Count; index++)
        {
            Creature creature = creatures[index];
            var creatureProjection = new CreatureProjectionDto
            {
                CombatId = creature.CombatId ?? 0,
                Index = index,
                Side = creature.Side.ToString(),
                ModelId = creature.ModelId.Entry,
                Hp = creature.CurrentHp,
                MaxHp = creature.MaxHp,
                Block = creature.Block,
                Alive = creature.IsAlive,
                IsPlayer = creature.IsPlayer,
            };

            MoveState? nextMove = creature.Monster?.NextMove;
            if (nextMove is not null)
            {
                var moveProjection = new NextMoveProjectionDto { Id = nextMove.Id };
                foreach (AbstractIntent intent in nextMove.Intents)
                {
                    int? damage = null;
                    int? repeats = null;
                    if (intent is AttackIntent attack)
                    {
                        damage = attack.GetSingleDamage(combatState.Allies, creature);
                        repeats = attack.Repeats;
                    }
                    moveProjection.Intents.Add(new IntentProjectionDto
                    {
                        IntentType = intent.IntentType.ToString(),
                        Implementation = intent.GetType().Name,
                        Damage = damage,
                        Repeats = repeats,
                    });
                }
                creatureProjection.NextMove = moveProjection;
            }

            foreach (PowerModel power in creature.Powers)
            {
                creatureProjection.Powers.Add(new PowerProjectionDto { ModelId = power.Id.Entry, Amount = power.Amount });
            }

            combatObs.Creatures.Add(creatureProjection);
        }

        foreach (string pileName in PileNames)
        {
            CardPile pile = pileName switch
            {
                "Hand" => combatStateForPlayer.Hand,
                "DrawPile" => combatStateForPlayer.DrawPile,
                "DiscardPile" => combatStateForPlayer.DiscardPile,
                "ExhaustPile" => combatStateForPlayer.ExhaustPile,
                "PlayPile" => combatStateForPlayer.PlayPile,
                _ => throw new InvalidOperationException($"Unknown pile {pileName}."),
            };
            var pileProjection = new PileProjectionDto { Name = pileName, Type = pile.Type.ToString() };
            for (int index = 0; index < pile.Cards.Count; index++)
            {
                pileProjection.Cards.Add(BuildCard(pile.Cards[index], index, pileName));
            }
            combatObs.Piles.Add(pileProjection);
        }

        OrbQueue? orbQueue = combatStateForPlayer.OrbQueue;
        if (orbQueue is not null)
        {
            var orbs = new OrbQueueProjectionDto { Capacity = orbQueue.Capacity };
            foreach (OrbModel orb in orbQueue.Orbs)
            {
                orbs.Entries.Add(new OrbProjectionDto
                {
                    ModelId = orb.Id.Entry,
                    Passive = orb.PassiveVal,
                    Evoke = orb.EvokeVal,
                    NativeState = SavedNativeState(orb),
                });
            }
            combatObs.Orbs = orbs;
        }

        // Legacy fields kept for the existing AutoSlayer-driven tooling.
        CardPile hand = combatStateForPlayer.Hand;
        for (int i = 0; i < hand.Cards.Count; i++)
        {
            CardModel card = hand.Cards[i];
            combatObs.Hand.Add(new CardObservationDto
            {
                Index = i,
                CardId = card.Id.Entry,
                Cost = card.EnergyCost.Canonical,
                CanPlay = card.CanPlay(),
                TargetType = card.TargetType.ToString(),
                Upgrades = card.CurrentUpgradeLevel,
            });
        }
        combatObs.DrawPileCount = combatStateForPlayer.DrawPile.Cards.Count;
        combatObs.DiscardPileCount = combatStateForPlayer.DiscardPile.Cards.Count;
        combatObs.ExhaustPileCount = combatStateForPlayer.ExhaustPile.Cards.Count;

        foreach (Creature enemy in combatState.Enemies.OrderBy(e => e.CombatId))
        {
            var enemyDto = new EnemyObservationDto
            {
                CombatId = enemy.CombatId ?? 0,
                ModelId = enemy.ModelId.Entry,
                Hp = enemy.CurrentHp,
                MaxHp = enemy.MaxHp,
                Block = enemy.Block,
                IsAlive = enemy.IsAlive,
                Intent = enemy.Monster?.NextMove.Id ?? "",
            };
            foreach (PowerModel power in enemy.Powers)
            {
                enemyDto.Powers[power.Id.Entry] = power.Amount;
            }
            combatObs.Enemies.Add(enemyDto);
        }

        obs.Combat = combatObs;
    }

    private static List<LegalActionDto> BuildCombatActions(ICombatState combatState, Player player)
    {
        var legalActions = new List<LegalActionDto>();
        PlayerCombatState combatStateForPlayer = player.PlayerCombatState!;

        for (int i = 0; i < combatStateForPlayer.Hand.Cards.Count; i++)
        {
            CardModel card = combatStateForPlayer.Hand.Cards[i];
            bool canPlay = card.CanPlay();
            if (!canPlay) continue;

            if (card.TargetType.IsSingleTarget() && card.TargetType != TargetType.Self)
            {
                foreach (Creature enemy in combatState.HittableEnemies.OrderBy(c => c.CombatId))
                {
                    ulong enemyId = enemy.CombatId ?? 0;
                    var metadata = CardActionMetadata(i, card);
                    metadata["target_id"] = enemyId;
                    metadata["target_index"] = IndexOfCreature(combatState, enemy);
                    metadata["target_model_id"] = enemy.ModelId.Entry;
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"play_card:{i}:target:{enemyId}",
                        ActionType = "play_card",
                        Description = $"Play {card.Id.Entry} targeting enemy {enemyId} ({enemy.CurrentHp}/{enemy.MaxHp})",
                        Metadata = metadata,
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
                    Metadata = CardActionMetadata(i, card),
                });
            }
        }

        for (int slot = 0; slot < player.PotionSlots.Count; slot++)
        {
            PotionModel? potion = player.PotionSlots[slot];
            if (potion is null) continue;
            if (potion.TargetType == TargetType.AnyEnemy)
            {
                foreach (Creature enemy in combatState.HittableEnemies.OrderBy(c => c.CombatId))
                {
                    ulong enemyId = enemy.CombatId ?? 0;
                    legalActions.Add(new LegalActionDto
                    {
                        ActionId = $"use_potion:{slot}:target:{enemyId}",
                        ActionType = "use_potion",
                        Description = $"Use potion {potion.Id.Entry} on enemy {enemyId}",
                        Metadata = new Dictionary<string, object?>
                        {
                            ["potion_index"] = slot,
                            ["potion_id"] = potion.Id.Entry,
                            ["target_id"] = enemyId,
                            ["target_index"] = IndexOfCreature(combatState, enemy),
                            ["target_model_id"] = enemy.ModelId.Entry,
                        }
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
                    Metadata = new Dictionary<string, object?>
                    {
                        ["potion_index"] = slot,
                        ["potion_id"] = potion.Id.Entry,
                        ["target_id"] = playerId,
                        ["target_index"] = IndexOfCreature(combatState, player.Creature),
                        ["target_model_id"] = player.Creature.ModelId.Entry,
                    }
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

        return legalActions;
    }

    private static int IndexOfCreature(ICombatState combatState, Creature creature)
    {
        IReadOnlyList<Creature> creatures = combatState.Creatures;
        for (int index = 0; index < creatures.Count; index++)
        {
            if (ReferenceEquals(creatures[index], creature)) return index;
        }
        return -1;
    }

    private static Dictionary<string, object?> CardActionMetadata(int index, CardModel card) => new()
    {
        ["card_index"] = index,
        ["card_id"] = card.Id.Entry,
        ["model_id"] = card.Id.Entry,
        ["upgrades"] = card.CurrentUpgradeLevel,
    };

    private static string? RewardModelId(object reward) => reward switch
    {
        MerchantCardEntry cardEntry => cardEntry.CreationResult?.Card?.Id.Entry,
        _ => reward.GetType().GetProperty("Relic")?.GetValue(reward) is RelicModel relic ? relic.Id.Entry
            : reward.GetType().GetProperty("Potion")?.GetValue(reward) is PotionModel potion ? potion.Id.Entry
            : null,
    };

    /// <summary>
    /// The cards a `CardReward` offers, read from its public `Cards` property. Reading them does not
    /// populate or modify the reward: `RewardsSet.GenerateWithoutOffering` has already populated every
    /// reward before the screen is shown.
    /// </summary>
    private static IReadOnlyList<CardModel> CardRewardCards(object cardReward)
    {
        if (cardReward is not CardReward reward) return Array.Empty<CardModel>();
        return reward.Cards.ToList();
    }

    /// <summary>
    /// The card reward's non-card options that change state (reroll, or a relic-granted alternative).
    /// The plain "Skip" alternative only closes the sub-screen and leaves the reward claimable, so it is
    /// a coordinator step rather than a decision and is not projected.
    /// </summary>
    private static IReadOnlyList<string> CardRewardAlternatives(object cardReward)
    {
        if (cardReward is not CardReward reward) return Array.Empty<string>();
        return CardRewardAlternative.Generate(reward)
            .Where(alternative => alternative.AfterSelected != PostAlternateCardRewardAction.EndSelectionAndDoNotCompleteReward)
            .Select(alternative => alternative.OptionId)
            .ToList();
    }

    internal static CardProjectionDto BuildCard(CardModel card, int index, string pileName)
    {
        ulong netId = 0;
        try
        {
            netId = NetCombatCardDb.Instance?.GetCardId(card) ?? 0;
        }
        catch (Exception)
        {
            netId = 0;
        }

        return new CardProjectionDto
        {
            Index = index,
            NetId = netId,
            InstanceId = netId != 0 ? $"net-{netId}" : $"{pileName}-{index}-{card.Id.Entry}",
            ModelId = card.Id.Entry,
            CardType = card.Type.ToString(),
            TargetType = card.TargetType.ToString(),
            EnergyCost = card.EnergyCost.GetResolved(),
            CostsX = card.EnergyCost.CostsX,
            Upgrades = card.CurrentUpgradeLevel,
            Enchantment = card.Enchantment is { } enchantment
                ? new EnchantmentProjectionDto { ModelId = enchantment.Id.Entry, Amount = enchantment.Amount }
                : null,
            NativeState = SavedNativeState(card),
        };
    }

    internal static SortedDictionary<string, object?> SavedNativeState(object model)
    {
        var result = new SortedDictionary<string, object?>(StringComparer.Ordinal);
        MethodInfo? toSerializable = model.GetType().GetMethod(
            "ToSerializable",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
            Type.EmptyTypes);
        if (toSerializable is null) return result;
        object? serializable = toSerializable.Invoke(model, null);
        if (serializable is null) return result;
        if (serializable.GetType().GetProperty("Props", BindingFlags.Public | BindingFlags.Instance)?.GetValue(serializable) is not SavedProperties props)
        {
            return result;
        }
        foreach (var entry in props.ints ?? new List<SavedProperties.SavedProperty<int>>()) result[entry.name] = entry.value;
        foreach (var entry in props.bools ?? new List<SavedProperties.SavedProperty<bool>>()) result[entry.name] = entry.value;
        foreach (var entry in props.strings ?? new List<SavedProperties.SavedProperty<string>>()) result[entry.name] = entry.value;
        foreach (var entry in props.intArrays ?? new List<SavedProperties.SavedProperty<int[]>>()) result[entry.name] = entry.value;
        return result;
    }

    internal static BridgeChoiceProjectionDto BuildChoiceProjection(BridgePendingChoice choice)
    {
        var projection = new BridgeChoiceProjectionDto
        {
            ChoiceId = choice.ChoiceId,
            Kind = choice.ActionKind,
            MinSelect = choice.MinSelect,
            MaxSelect = choice.MaxSelect,
            Options = choice.Options,
        };
        return projection;
    }

    internal static List<LegalActionDto> BuildChoiceActions(BridgePendingChoice choice)
    {
        var actions = new List<LegalActionDto>();
        foreach (string[] selection in EnumerateSelections(choice.OptionIds, choice.MinSelect, choice.MaxSelect, 4096))
        {
            string suffix = selection.Length == 0 ? "skip" : string.Join('+', selection.Select(Uri.EscapeDataString));
            actions.Add(new LegalActionDto
            {
                ActionId = $"{choice.ActionKind}:{choice.ChoiceId}:{suffix}",
                ActionType = choice.ActionKind,
                Description = $"{choice.ActionKind} {suffix}",
                Metadata = new Dictionary<string, object?>
                {
                    ["choice_id"] = choice.ChoiceId,
                    ["option_ids"] = selection,
                    ["min_select"] = choice.MinSelect,
                    ["max_select"] = choice.MaxSelect,
                }
            });
        }
        return actions;
    }

    /// <summary>
    /// All subsets of size <c>min..max</c> in the same depth-first order the reconstructed fast
    /// path enumerates, so two environments offer the same semantic selection set.
    /// </summary>
    internal static IEnumerable<string[]> EnumerateSelections(string[] options, int min, int max, int limit)
    {
        var result = new List<string[]>();
        var current = new List<string>();
        void Visit(int index)
        {
            if (result.Count > limit) return;
            if (current.Count >= min && current.Count <= max) result.Add(current.ToArray());
            if (current.Count == max) return;
            for (int i = index; i < options.Length; i++)
            {
                current.Add(options[i]);
                Visit(i + 1);
                current.RemoveAt(current.Count - 1);
            }
        }
        Visit(0);
        if (result.Count > limit)
        {
            throw new InvalidOperationException($"Native choice expands beyond {limit} legal combinations.");
        }
        return result;
    }

    private static string ComputeHash(ObservationDto obs)
    {
        string json = JsonSerializer.Serialize(obs, JsonOptions);
        byte[] bytes = SHA256.HashData(Encoding.UTF8.GetBytes(json));
        return Convert.ToHexString(bytes);
    }
}
