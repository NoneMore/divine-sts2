using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// Projects the bridge's shipped-game DTO into the canonical observation contract. The bridge keeps
/// its legacy wire DTO and hash; this adapter is the explicit boundary between that runtime dialect
/// and the shared, typed state used by schema validation and parity.
/// </summary>
public static class FullAppCanonicalObservationEncoder
{
    public static CanonicalObservation Encode(ObservationDto observation, IReadOnlyList<LegalAction> legalActions)
    {
        if (observation.Run is null)
        {
            throw new InvalidOperationException("A full-app observation cannot enter the canonical contract without a run.");
        }

        (string decisionKind, object? stageBlock, CanonicalChoice? choice) = ProjectStage(observation);
        object runtimeProjection = new
        {
            schema_version = ProtocolConstants.ObservationSchemaVersion,
            game_build = observation.GameBuild,
            run = observation.Run,
            combat = observation.Combat,
            inventory = observation.Combat is not null ? observation.Inventory : null,
            map = observation.Phase == "map" ? stageBlock : null,
            reward = observation.Phase == "card_reward" ? stageBlock : null,
            rest_site = observation.Phase == "rest_site" ? stageBlock : null,
            @event = observation.Phase == "event" ? stageBlock : null,
            treasure = observation.Phase == "treasure" ? stageBlock : null,
            shop = observation.Phase == "shop" ? stageBlock : null,
            room_rewards = observation.Phase == "rewards" ? stageBlock : null,
            custom_rewards = choice is not null ? new CanonicalCustomRewards
            {
                Rewards = [],
                CanSkip = true,
                Depth = 0,
            } : null,
            outstanding_choice = choice,
            decision = new
            {
                kind = observation.IsTerminal && observation.Combat is not null ? "terminal" : decisionKind,
                legal_actions = legalActions.Select(action => new
                {
                    action_id = action.ActionId,
                    kind = action.Kind,
                    parameters = action.Parameters,
                }).ToArray(),
            },
            terminal = observation.IsTerminal,
            victory = observation.IsVictory,
        };
        return CanonicalObservationJson.EncodeRuntime(runtimeProjection);
    }

    private static (string DecisionKind, object? StageBlock, CanonicalChoice? Choice) ProjectStage(ObservationDto observation)
    {
        RoomObservationDto? room = observation.Room;
        if (observation.Combat is not null) return ("combat_action", null, null);
        if (observation.Phase == "victory") return ("act_transition", null, null);
        if (observation.IsTerminal || observation.Phase == "game_over") return ("run_terminal", null, null);
        return observation.Phase switch
        {
            "map" => ("map_choice", MapStage(observation, room), null),
            "card_reward" => ("reward_choice", RewardStage(room), null),
            "rewards" => ("room_reward_choice", RoomRewardsStage(room), null),
            "rest_site" => ("rest_choice", RestStage(room), null),
            "event" => ("event_choice", EventStage(room), null),
            "treasure" => ("treasure_open", new CanonicalTreasure { Opened = false, Resolved = false, RelicOptions = [] }, null),
            "shop" => ("shop_choice", ShopStage(room), null),
            "deck_upgrade" or "deck_card_select" or "simple_card_select" =>
                ("card_choice", null, ChoiceStage(observation.Phase, room)),
            _ => ("act_transition", null, null),
        };
    }

    private static CanonicalMap MapStage(ObservationDto observation, RoomObservationDto? room)
    {
        int nextRow = (observation.MapCoord?.Row ?? -1) + 1;
        CanonicalMapPoint[] points = (room?.Options ?? []).Select((option, index) =>
        {
            string[] parts = option.Split(':', 2);
            int column = int.TryParse(parts[0], out int parsed) ? parsed - 1 : index;
            return new CanonicalMapPoint
            {
                Coord = new CanonicalCoord { Col = column, Row = nextRow },
                PointType = parts.Length == 2 ? parts[1] : option,
                Children = [],
            };
        }).ToArray();
        CanonicalCoord? current = observation.MapCoord is null
            ? null
            : new CanonicalCoord { Col = observation.MapCoord.Col, Row = observation.MapCoord.Row };
        return new CanonicalMap
        {
            Points = points,
            Visited = current is null ? [] : [current],
            Current = current,
        };
    }

    private static CanonicalReward RewardStage(RoomObservationDto? room) => new()
    {
        Kind = "card",
        Options = (room?.Options ?? []).Select((modelId, index) => new CanonicalRewardOption
        {
            OptionId = $"reward-{index}-{modelId}",
            ModelId = modelId,
        }).ToArray(),
        CanSkip = true,
        Selected = false,
    };

    private static CanonicalRoomRewards RoomRewardsStage(RoomObservationDto? room) => new()
    {
        Rewards = (room?.Options ?? []).Select((option, index) => new CanonicalRoomReward
        {
            RewardIndex = index,
            Kind = option.Split(':').Last(),
            Options = [],
            Resolved = false,
        }).ToArray(),
    };

    private static CanonicalRestSite RestStage(RoomObservationDto? room) => new()
    {
        Options = (room?.Options ?? []).Select(option => new CanonicalRestOption
        {
            OptionId = option,
            Enabled = true,
            Implementation = option,
        }).ToArray(),
        Selected = false,
    };

    private static CanonicalEvent EventStage(RoomObservationDto? room) => new()
    {
        ModelId = room?.RoomType ?? "Event",
        Options = (room?.Options ?? []).Select((option, index) => new CanonicalEventOption
        {
            OptionIndex = index,
            TextKey = option,
            Locked = false,
            Chosen = false,
            IsProceed = false,
        }).ToArray(),
        Finished = false,
    };

    private static CanonicalShop ShopStage(RoomObservationDto? room) => new()
    {
        Entries = (room?.Options ?? []).Select((option, index) =>
        {
            string[] parts = option.Split(':');
            return new CanonicalShopEntry
            {
                EntryIndex = index,
                Kind = parts.ElementAtOrDefault(1) ?? "Unknown",
                ModelId = parts.ElementAtOrDefault(2),
                Cost = int.TryParse(parts.ElementAtOrDefault(3), out int cost) ? cost : 0,
                Stocked = true,
                EnoughGold = true,
            };
        }).ToArray(),
    };

    private static CanonicalChoice ChoiceStage(string phase, RoomObservationDto? room) => new()
    {
        ChoiceId = $"bridge-{phase}",
        Kind = "choose_cards",
        MinSelect = 1,
        MaxSelect = 1,
        Provenance = "FullAppBridge",
        Options = (room?.Options ?? []).Select((modelId, index) =>
            (CanonicalChoiceOption)new CanonicalModelChoiceOption
            {
                OptionId = $"bridge-{phase}-{index}-{modelId}",
                ModelId = modelId,
            }).ToArray(),
    };
}
