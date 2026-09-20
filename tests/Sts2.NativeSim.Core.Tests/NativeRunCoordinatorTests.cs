using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Sts2.NativeSim.Core;
using Sts2.NativeSim.Core.RunSession;
using Sts2.NativeSim.Protocol;
using Xunit;

namespace Sts2.NativeSim.Core.Tests;

public sealed class NativeRunCoordinatorTests
{
    [Fact]
    public async Task Caller_can_reset_capture_step_fork_and_restore()
    {
        ScriptedNativeRunAdapter adapter = ScenarioScript();
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult reset = coordinator.RunReset(Request());
        Assert.Equal("ancient-door", Assert.Single(coordinator.LegalActions()).ActionId);
        Assert.Equal(reset.StateHash, coordinator.Observe().StateHash);

        EnvironmentResult ancient = await coordinator.StepAsync("ancient-door");
        string branch = coordinator.Fork();
        EnvironmentResult choice = await coordinator.StepAsync("ancient-choice-2");
        Assert.Contains(choice.LegalActions, action => action.ActionId == "nested-card-0");

        EnvironmentResult restored = await coordinator.RestoreAsync(branch);
        Assert.Equal(ancient.StateHash, restored.StateHash);
        Assert.Contains(restored.LegalActions, action => action.ActionId == "ancient-choice-2");
    }

    [Fact]
    public async Task Invalid_action_does_not_reach_the_native_port_or_mutate_state()
    {
        ScriptedNativeRunAdapter adapter = ScenarioScript();
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult before = coordinator.RunReset(Request());

        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(
            () => coordinator.StepAsync("not-advertised"));

        Assert.Equal("invalid_action", error.Code);
        Assert.Equal(0, adapter.MutationCount);
        Assert.Equal(before.StateHash, coordinator.Observe().StateHash);
    }

    [Fact]
    public async Task Action_id_collision_restores_the_state_that_preceded_the_action()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("safe")
            .Frame("safe", """
                {"schema_version":3,"decision":{"kind":"event"}}
                """, Action("enter-collision", "choose_event"))
            .Frame("collision", """
                {"schema_version":3,"decision":{"kind":"event"}}
                """,
                Action("same-id", "choose_event", ("option_index", 0)),
                Action("same-id", "choose_event", ("option_index", 1)))
            .Transition("safe", "enter-collision", "collision");
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult before = coordinator.RunReset(Request());

        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(
            () => coordinator.StepAsync("enter-collision"));

        Assert.Equal("action_id_collision", error.Code);
        Assert.Equal(1, adapter.MutationCount);
        Assert.Equal(before.StateHash, coordinator.Observe().StateHash);
    }

    [Fact]
    public async Task Native_error_after_mutation_restores_the_state_that_preceded_the_action()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("before")
            .Frame("before", """{"schema_version":3,"decision":{"kind":"event"}}""",
                Action("fail", "choose_event"))
            .Frame("mutated", """{"schema_version":3,"decision":{"kind":"map"}}""")
            .Transition("before", "fail", "mutated")
            .ErrorAfterMutation("before", "fail");
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult before = coordinator.RunReset(Request());

        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(() => coordinator.StepAsync("fail"));

        Assert.Equal("scripted_native_error", error.Code);
        Assert.Equal(1, adapter.MutationCount);
        Assert.Equal(before.StateHash, coordinator.Observe().StateHash);
    }

    [Fact]
    public async Task Recorded_generated_scenario_recipe_reaches_the_recorded_combat_initial_state()
    {
        RecordedRecipe recipe = new(
            AncientOptionIndex: 2,
            NestedOptionIndices: [0],
            NodeCol: 0,
            NodeRow: 1,
            Encounter: "SLIMES_WEAK",
            ObservationSha256: "85E0A1ECB8D151839B5E243827857F99836CFB28B24F76464153F84E32ED188E");
        RecordedScenario recorded = LoadRecordedScenarioCapture();
        AssertRecordedRecipe(recorded.Recipe, recipe);
        ScriptedNativeRunAdapter adapter = ScenarioScript(recorded);
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult state = coordinator.RunReset(Request());

        state = await coordinator.StepAsync(ActionWith(state, "choose_map").ActionId);
        int optionIndex = recorded.Recipe.GetProperty("ancient_choice").GetProperty("option_index").GetInt32();
        state = await coordinator.StepAsync(ActionWith(state, "choose_event", "option_index", optionIndex).ActionId);
        foreach (JsonElement nested in recorded.Recipe.GetProperty("nested_choices").EnumerateArray())
            state = await coordinator.StepAsync(state.LegalActions[nested.GetProperty("selected_index").GetInt32()].ActionId);
        state = await coordinator.StepAsync("leave_event");
        JsonElement recordedNode = recorded.Recipe.GetProperty("node");
        LegalAction mapAction = state.LegalActions.Single(action =>
            action.Kind == "choose_map"
            && Equals(action.Parameters["col"], recordedNode.GetProperty("col").GetInt32())
            && Equals(action.Parameters["row"], recordedNode.GetProperty("row").GetInt32()));
        state = await coordinator.StepAsync(mapAction.ActionId);

        JsonElement actual = Assert.IsType<JsonElement>(state.Observation);
        string observationHash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(actual.GetRawText())));
        Assert.Equal(recipe.Encounter, actual.GetProperty("combat").GetProperty("encounter").GetString());
        Assert.Equal(recipe.ObservationSha256, observationHash);
        Assert.Matches("^[0-9A-F]{64}$", state.StateHash);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Map_actions_are_executed_by_the_semantic_native_port()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("map")
            .MapFrame("map", """{"decision":{"kind":"map_choice"}}""",
                MapAction("ancient", 1, 0, "Ancient"),
                MapAction("monster", 0, 1, "Monster"))
            .Frame("ancient", """{"decision":{"kind":"event"}}""",
                Action("choose", "choose_event"))
            .Frame("combat", """{"decision":{"kind":"combat"}}""",
                Action("play", "play_card"))
            .EnterMapPoint("map", col: 1, row: 0, pointType: "Ancient", to: "ancient")
            .EnterMapPoint("map", col: 0, row: 1, pointType: "Monster", to: "combat");
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult map = coordinator.RunReset(Request());

        EnvironmentResult ancient = await coordinator.StepAsync("ancient");

        Assert.Equal("choose", Assert.Single(ancient.LegalActions).ActionId);
        Assert.Equal([(1, 0)], adapter.EnteredMapPoints);
        Assert.Equal(0, adapter.GenericApplyCount);
        Assert.Equal(2, map.LegalActions.Count);
    }

    [Fact]
    public async Task Event_choices_are_executed_by_the_semantic_native_port()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("event")
            .EventFrame("event", """{"decision":{"kind":"event_choice"}}""",
                Action("first", "choose_event", ("option_index", 0)),
                Action("second", "choose_event", ("option_index", 1)))
            .EventFrame("complete", """{"decision":{"kind":"event_complete"}}""",
                Action("leave_event", "leave_event"))
            .EventTransition("event", new(1), "complete");
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult before = coordinator.RunReset(Request());

        EnvironmentResult after = await coordinator.StepAsync("second");

        Assert.Equal(["first", "second"], before.LegalActions.Select(action => action.ActionId));
        Assert.Equal("leave_event", Assert.Single(after.LegalActions).ActionId);
        Assert.Equal(1, Assert.Single(adapter.EventSelections).OptionIndex);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Standalone_event_reset_initializes_the_active_session()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("event")
            .EventFrame("event", """{"event":{"model_id":"THE_ARCHITECT"},"decision":{"kind":"event_choice"}}""",
                Action("choose", "choose_event", ("option_index", 0)))
            .EventFrame("complete", """{"event":{"model_id":"THE_ARCHITECT"},"decision":{"kind":"event_complete"}}""",
                Action("leave_event", "leave_event"))
            .EventTransition("event", new(0), "complete");
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult reset = await coordinator.EventResetAsync(
            new(Request() with { ResetMode = null }, "THE_ARCHITECT"));
        EnvironmentResult observed = coordinator.Observe();
        EnvironmentResult complete = await coordinator.StepAsync("choose");

        Assert.Equal(reset.StateHash, observed.StateHash);
        Assert.Equal("leave_event", Assert.Single(complete.LegalActions).ActionId);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Standalone_map_reset_initializes_the_active_session()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("map")
            .MapFrame("map", """{"decision":{"kind":"map_choice"}}""",
                MapAction("enter", 0, 1, "Monster"))
            .Frame("combat", """{"decision":{"kind":"combat"}}""",
                Action("play", "play_card"))
            .EnterMapPoint("map", col: 0, row: 1, pointType: "Monster", to: "combat");
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult map = coordinator.MapReset(Request() with { ResetMode = null });
        EnvironmentResult combat = await coordinator.StepAsync(Assert.Single(map.LegalActions).ActionId);

        Assert.Equal("play", Assert.Single(combat.LegalActions).ActionId);
        Assert.Equal([(0, 1)], adapter.EnteredMapPoints);
    }

    [Fact]
    public void Standalone_map_reset_rejects_an_explicit_run_mode()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("map")
            .MapFrame("map", """{"decision":{"kind":"map_choice"}}""");
        NativeRunCoordinator coordinator = new(adapter);

        ProtocolException error = Assert.Throws<ProtocolException>(() => coordinator.MapReset(Request()));

        Assert.Equal("invalid_reset", error.Code);
    }

    [Fact]
    public async Task Standalone_rest_reset_initializes_the_active_session()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("rest")
            .RestFrame("rest", """{"decision":{"kind":"rest_choice"}}""",
                Action("choose_rest:REST", "choose_rest", ("option_id", "REST")))
            .RestFrame("complete", """{"decision":{"kind":"rest_complete"}}""")
            .RestTransition("rest", new RestSelection("REST"), "complete");
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult reset = coordinator.RestReset(Request() with { ResetMode = ResetModes.Combat });
        EnvironmentResult complete = await coordinator.StepAsync("choose_rest:REST");

        Assert.Equal("choose_rest:REST", Assert.Single(reset.LegalActions).ActionId);
        Assert.Empty(complete.LegalActions);
        Assert.Equal([new RestSelection("REST")], adapter.RestSelections);
    }

    [Theory]
    [InlineData("Ancient", "event")]
    [InlineData("Monster", "combat")]
    [InlineData("Elite", "combat")]
    [InlineData("Boss", "combat")]
    [InlineData("RestSite", "rest")]
    [InlineData("Unknown", "event")]
    [InlineData("Treasure", "treasure")]
    [InlineData("Shop", "shop")]
    public async Task Each_supported_map_point_selects_one_next_active_state(
        string pointType,
        string nextDecision)
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("map")
            .MapFrame("map", """{"decision":{"kind":"map_choice"}}""",
                MapAction("enter", 2, 3, pointType))
            .Frame("next", JsonSerializer.Serialize(new { decision = new { kind = nextDecision } }))
            .EnterMapPoint("map", col: 2, row: 3, pointType, to: "next");
        NativeRunCoordinator coordinator = new(adapter);
        coordinator.RunReset(Request());

        EnvironmentResult next = await coordinator.StepAsync("enter");

        Assert.Equal(nextDecision, Assert.IsType<JsonElement>(next.Observation)
            .GetProperty("decision").GetProperty("kind").GetString());
        Assert.Equal([(2, 3)], adapter.EnteredMapPoints);
    }

    [Fact]
    public async Task Rest_actions_keep_their_projection_order_and_use_the_semantic_native_port()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("rest")
            .RestFrame("rest", """{"decision":{"kind":"rest_choice"}}""",
                Action("choose_rest:SMITH", "choose_rest", ("option_id", "SMITH")),
                Action("choose_rest:REST", "choose_rest", ("option_id", "REST")))
            .RestFrame("complete", """{"decision":{"kind":"rest_complete"}}""",
                Action("leave_rest", "leave_rest"))
            .MapFrame("map", """{"decision":{"kind":"map"}}""",
                MapAction("route", 0, 1, "Monster"))
            .RestTransition("rest", new RestSelection("SMITH"), "complete")
            .LeaveSimpleRoom("complete", SimpleRoomKind.Rest, "map");
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult rest = coordinator.RunReset(Request());
        EnvironmentResult complete = await coordinator.StepAsync("choose_rest:SMITH");
        EnvironmentResult map = await coordinator.StepAsync("leave_rest");

        Assert.Equal(["choose_rest:SMITH", "choose_rest:REST"], rest.LegalActions.Select(action => action.ActionId));
        Assert.Equal("leave_rest", Assert.Single(complete.LegalActions).ActionId);
        Assert.Equal("route", Assert.Single(map.LegalActions).ActionId);
        Assert.Equal([new RestSelection("SMITH")], adapter.RestSelections);
        Assert.Equal([SimpleRoomKind.Rest], adapter.LeftSimpleRooms);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Treasure_actions_keep_their_projection_order_and_use_the_semantic_native_port()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("closed")
            .TreasureFrame("closed", """{"decision":{"kind":"treasure_open"}}""",
                Action("open_treasure", "open_treasure"))
            .TreasureFrame("open", """{"decision":{"kind":"treasure_relic_choice"}}""",
                Action("choose_treasure:0:ANCHOR", "choose_treasure", ("option_index", 0), ("model_id", "ANCHOR")),
                Action("choose_treasure:1:BAG_OF_PREPARATION", "choose_treasure", ("option_index", 1), ("model_id", "BAG_OF_PREPARATION")),
                Action("skip_treasure", "skip_treasure"))
            .TreasureFrame("complete", """{"decision":{"kind":"treasure_complete"}}""",
                Action("leave_treasure", "leave_treasure"))
            .MapFrame("map", """{"decision":{"kind":"map"}}""",
                MapAction("route", 0, 1, "Monster"))
            .OpenTreasure("closed", "open")
            .TreasureTransition("open", new TreasureSelection(1), "complete")
            .LeaveSimpleRoom("complete", SimpleRoomKind.Treasure, "map");
        NativeRunCoordinator coordinator = new(adapter);

        coordinator.RunReset(Request());
        EnvironmentResult open = await coordinator.StepAsync("open_treasure");
        EnvironmentResult complete = await coordinator.StepAsync("choose_treasure:1:BAG_OF_PREPARATION");
        EnvironmentResult map = await coordinator.StepAsync("leave_treasure");

        Assert.Equal(
            ["choose_treasure:0:ANCHOR", "choose_treasure:1:BAG_OF_PREPARATION", "skip_treasure"],
            open.LegalActions.Select(action => action.ActionId));
        Assert.Equal("leave_treasure", Assert.Single(complete.LegalActions).ActionId);
        Assert.Equal("route", Assert.Single(map.LegalActions).ActionId);
        Assert.Equal(1, adapter.OpenTreasureCount);
        Assert.Equal([new TreasureSelection(1)], adapter.TreasureSelections);
        Assert.Equal([SimpleRoomKind.Treasure], adapter.LeftSimpleRooms);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Shop_actions_keep_their_projection_order_and_use_the_semantic_native_port()
    {
        LegalAction card = Action(
            "buy_shop:0:card:BASH",
            "buy_shop",
            ("entry_index", 0),
            ("entry_kind", "card"),
            ("model_id", "BASH"),
            ("cost", 50));
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("shop")
            .ShopFrame("shop", """{"decision":{"kind":"shop_choice"}}""",
                card,
                Action("leave_shop", "leave_shop"))
            .ShopFrame("after-buy", """{"decision":{"kind":"shop_choice"}}""",
                Action("leave_shop", "leave_shop"))
            .MapFrame("map", """{"decision":{"kind":"map"}}""",
                MapAction("route", 0, 1, "Monster"))
            .ShopTransition("shop", new ShopSelection(0), "after-buy")
            .LeaveSimpleRoom("after-buy", SimpleRoomKind.Shop, "map");
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult shop = coordinator.RunReset(Request());
        EnvironmentResult afterBuy = await coordinator.StepAsync(card.ActionId);
        EnvironmentResult map = await coordinator.StepAsync("leave_shop");

        Assert.Same(card, shop.LegalActions[0]);
        Assert.Equal([card.ActionId, "leave_shop"], shop.LegalActions.Select(action => action.ActionId));
        Assert.Equal("leave_shop", Assert.Single(afterBuy.LegalActions).ActionId);
        Assert.Equal("route", Assert.Single(map.LegalActions).ActionId);
        Assert.Equal([new ShopSelection(0)], adapter.ShopSelections);
        Assert.Equal([SimpleRoomKind.Shop], adapter.LeftSimpleRooms);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Combat_can_transition_through_reward_to_the_map()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("combat")
            .Frame("combat", """{"schema_version":3,"decision":{"kind":"combat"}}""",
                Action("finish-combat", "end_turn"))
            .StandaloneRewardFrame("reward", """{"schema_version":3,"decision":{"kind":"card_reward"}}""",
                Action("reward-0", "choose_reward", ("option_index", 0)))
            .MapFrame("map", """{"schema_version":3,"decision":{"kind":"map"}}""",
                MapAction("map-0-2", 0, 2, "Monster"))
            .Transition("combat", "finish-combat", "reward")
            .ChooseStandaloneReward("reward", new(0), "map");
        NativeRunCoordinator coordinator = new(adapter);

        coordinator.RunReset(Request());
        string branch = coordinator.Fork();
        EnvironmentResult reward = await coordinator.StepAsync("finish-combat");
        EnvironmentResult map = await coordinator.StepAsync("reward-0");
        await coordinator.RestoreAsync(branch);
        EnvironmentResult replayedReward = await coordinator.StepAsync("finish-combat");
        EnvironmentResult replayedMap = await coordinator.StepAsync("reward-0");

        Assert.Equal("choose_reward", Assert.Single(reward.LegalActions).Kind);
        Assert.Equal("choose_reward", Assert.Single(replayedReward.LegalActions).Kind);
        Assert.Equal("choose_map", Assert.Single(map.LegalActions).Kind);
        Assert.Equal(map.StateHash, replayedMap.StateHash);
        Assert.Equal([new StandaloneRewardSelection(0), new StandaloneRewardSelection(0)],
            adapter.StandaloneRewardSelections);
        Assert.Equal(2, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Standalone_reward_selection_preserves_order_and_uses_the_reward_port()
    {
        LegalAction take = Action("choose_reward:0:RELIC", "choose_reward",
            ("option_index", 0), ("model_id", "RELIC"), ("skip", false));
        LegalAction skip = Action("choose_reward:skip", "choose_reward",
            ("option_index", -1), ("model_id", null), ("skip", true));
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("reward")
            .StandaloneRewardFrame("reward", """{"decision":{"kind":"reward_choice"}}""", take, skip)
            .StandaloneRewardFrame("complete", """{"decision":{"kind":"reward_complete"}}""")
            .ChooseStandaloneReward("reward", new(0), "complete");
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult before = coordinator.RunReset(Request());
        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(
            () => coordinator.StepAsync("not-a-reward"));
        Assert.Equal("invalid_action", error.Code);
        Assert.Empty(adapter.StandaloneRewardSelections);
        string branch = coordinator.Fork();
        EnvironmentResult after = await coordinator.StepAsync(take.ActionId);
        await coordinator.RestoreAsync(branch);
        EnvironmentResult replayed = await coordinator.StepAsync(take.ActionId);

        Assert.Equal([take, skip], before.LegalActions);
        Assert.Empty(after.LegalActions);
        Assert.Equal(after.StateHash, replayed.StateHash);
        Assert.Equal([new StandaloneRewardSelection(0), new StandaloneRewardSelection(0)],
            adapter.StandaloneRewardSelections);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Standalone_reward_option_pick_temporarily_replaces_the_reward_state_with_a_typed_prompt()
    {
        LegalAction take = Action("choose_reward:0:SCROLL_BOXES", "choose_reward", ("option_index", 0));
        LegalAction option = Action("choose_option:bundle-0", "choose_option",
            ("choice_id", "scroll-boxes"), ("option_ids", new[] { "bundle-0" }));
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("reward")
            .StandaloneRewardFrame("reward", """{"decision":{"kind":"reward_choice"}}""", take)
            .StandaloneRewardFrame("option", """{"decision":{"kind":"option_choice"}}""", option)
            .StandaloneRewardFrame("complete", """{"decision":{"kind":"reward_complete"}}""")
            .ChooseStandaloneReward("reward", new(0), "option")
            .Transition("option", option.ActionId, "complete");
        NativeRunCoordinator coordinator = new(adapter);
        coordinator.RunReset(Request());

        EnvironmentResult prompt = await coordinator.StepAsync(take.ActionId);
        EnvironmentResult complete = await coordinator.StepAsync(option.ActionId);

        Assert.Same(option, Assert.Single(prompt.LegalActions));
        Assert.Empty(complete.LegalActions);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Reward_nested_choice_limit_failure_keeps_its_code_and_restores_the_reward()
    {
        LegalAction take = Action("choose_reward:0:RELIC", "choose_reward", ("option_index", 0));
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("reward")
            .StandaloneRewardFrame("reward", """{"decision":{"kind":"reward_choice"}}""", take)
            .StandaloneRewardFrame("mutated", """{"decision":{"kind":"reward_complete"}}""")
            .ChooseStandaloneReward("reward", new(0), "mutated")
            .ErrorAfterMutation("reward", take.ActionId, "choice_too_large");
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult before = coordinator.RunReset(Request());

        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(
            () => coordinator.StepAsync(take.ActionId));

        Assert.Equal("choice_too_large", error.Code);
        Assert.Equal(before.StateHash, coordinator.Observe().StateHash);
        Assert.Equal(take.ActionId, Assert.Single(coordinator.LegalActions()).ActionId);
    }

    [Fact]
    public void Reward_reset_initializes_the_active_reward_session()
    {
        LegalAction skip = Action("choose_reward:skip", "choose_reward",
            ("option_index", -1), ("model_id", null), ("skip", true));
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("reward")
            .StandaloneRewardFrame("reward", """{"decision":{"kind":"reward_choice"}}""", skip);
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult reset = coordinator.RewardReset(Request() with { ResetMode = ResetModes.Combat });

        Assert.Equal(skip, Assert.Single(reset.LegalActions));
        Assert.Equal("reward_reset", JsonSerializer.SerializeToElement(reset.Transition)
            .GetProperty("kind").GetString());
        Assert.Equal(1, adapter.RewardResetCount);
    }

    [Fact]
    public async Task Item_and_custom_reward_resets_preserve_their_transition_metadata()
    {
        ScriptedNativeRunAdapter itemAdapter = new ScriptedNativeRunAdapter("item")
            .StandaloneRewardFrame("item", """{"decision":{"kind":"reward_choice"}}""",
                Action("choose_reward:skip", "choose_reward", ("option_index", -1)));
        NativeRunCoordinator itemCoordinator = new(itemAdapter);
        EnvironmentResult item = itemCoordinator.ItemRewardReset(
            new(Request() with { ResetMode = ResetModes.Combat }, "relic", "ANCHOR"));

        ScriptedNativeRunAdapter customAdapter = new ScriptedNativeRunAdapter("custom")
            .RewardPrompt("custom", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [0]);
        NativeRunCoordinator customCoordinator = new(customAdapter);
        EnvironmentResult custom = await customCoordinator.CustomRewardResetAsync(
            new(Request() with { ResetMode = ResetModes.Combat }, ["gold"], Linked: true));

        JsonElement itemTransition = JsonSerializer.SerializeToElement(item.Transition);
        Assert.Equal("item_reward_reset", itemTransition.GetProperty("kind").GetString());
        Assert.Equal("relic", itemTransition.GetProperty("reward_kind").GetString());
        Assert.Equal("ANCHOR", itemTransition.GetProperty("model_id").GetString());
        JsonElement customTransition = JsonSerializer.SerializeToElement(custom.Transition);
        Assert.Equal("custom_reward_reset", customTransition.GetProperty("kind").GetString());
        Assert.True(customTransition.GetProperty("linked").GetBoolean());
        Assert.Equal(1, itemAdapter.ItemRewardResetCount);
        Assert.Equal(1, customAdapter.CustomRewardResetCount);
    }

    [Fact]
    public async Task Room_rewards_generate_choose_and_leave_through_the_reward_port()
    {
        LegalAction generate = Action("generate_room_rewards", "generate_room_rewards");
        LegalAction card = Action("choose_room_reward:0:card:1:BASH", "choose_room_reward",
            ("reward_index", 0), ("option_index", 1), ("reward_kind", "card"), ("model_id", "BASH"));
        LegalAction relic = Action("choose_room_reward:1:take", "choose_room_reward",
            ("reward_index", 1), ("option_index", 0), ("reward_kind", "relic"), ("model_id", "ANCHOR"));
        LegalAction leave = Action("leave_room_rewards", "leave_room_rewards");
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("pending")
            .RoomRewardFrame("pending", """{"decision":{"kind":"room_reward_choice"}}""", generate)
            .RoomRewardFrame("rewards", """{"decision":{"kind":"room_reward_choice"}}""", card, relic, leave)
            .RoomRewardFrame("resolved", """{"decision":{"kind":"room_reward_choice"}}""", leave)
            .MapFrame("map", """{"decision":{"kind":"map"}}""", MapAction("route", 0, 1, "Monster"))
            .GenerateRoomRewards("pending", "rewards")
            .ChooseRoomReward("rewards", new(0, 1), "resolved")
            .LeaveRoomRewards("resolved", "map");
        NativeRunCoordinator coordinator = new(adapter);

        coordinator.RunReset(Request());
        string branch = coordinator.Fork();
        EnvironmentResult rewards = await coordinator.StepAsync(generate.ActionId);
        EnvironmentResult resolved = await coordinator.StepAsync(card.ActionId);
        EnvironmentResult map = await coordinator.StepAsync(leave.ActionId);
        await coordinator.RestoreAsync(branch);
        await coordinator.StepAsync(generate.ActionId);
        await coordinator.StepAsync(card.ActionId);
        EnvironmentResult replayedMap = await coordinator.StepAsync(leave.ActionId);

        Assert.Equal([card, relic, leave], rewards.LegalActions);
        Assert.Equal([leave], resolved.LegalActions);
        Assert.Equal(map.StateHash, replayedMap.StateHash);
        Assert.Equal([new RoomRewardSelection(0, 1), new RoomRewardSelection(0, 1)],
            adapter.RoomRewardSelections);
        Assert.Equal(2, adapter.GenerateRoomRewardsCount);
        Assert.Equal(2, adapter.LeaveRoomRewardsCount);
        Assert.Equal("route", Assert.Single(map.LegalActions).ActionId);
        Assert.Equal(0, adapter.GenericApplyCount);
    }

    [Fact]
    public async Task Act_transition_replays_to_the_same_terminal_hash_through_its_typed_state()
    {
        LegalAction advance = Action("advance_act", "advance_act");
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("act-transition")
            .ActTransitionFrame("act-transition", """{"decision":{"kind":"act_transition"}}""", advance)
            .TerminalFrame("terminal", """{"decision":{"kind":"run_terminal"},"terminal":true,"victory":true}""", victory: true)
            .AdvanceAct("act-transition", "terminal");
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult transition = coordinator.RunReset(Request());
        string branch = coordinator.Fork();

        EnvironmentResult first = await coordinator.StepAsync(advance.ActionId);
        EnvironmentResult restored = await coordinator.RestoreAsync(branch);
        EnvironmentResult replayed = await coordinator.StepAsync(advance.ActionId);

        Assert.Equal("advance_act", Assert.Single(transition.LegalActions).ActionId);
        Assert.Empty(first.LegalActions);
        Assert.True(first.Terminated);
        Assert.True(first.Victory);
        Assert.Equal(first.StateHash, replayed.StateHash);
        Assert.Equal(2, adapter.AdvanceActCount);
        Assert.Equal(0, adapter.GenericApplyCount);
        Assert.Equal(0, JsonSerializer.SerializeToElement(restored.Transition)
            .GetProperty("replayed_actions").GetInt32());
    }

    [Fact]
    public async Task Card_select_prompt_suspends_its_parent_until_the_typed_selection_resumes_it()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("event")
            .EventFrame("event", """{"decision":{"kind":"event"}}""",
                Action("open-card-select", "choose_event", ("option_index", 0)),
                Action("leave-event", "leave_event"))
            .CardPrompt(
                "card-select",
                """{"decision":{"kind":"card_choice"}}""",
                choiceId: "card-choice-0",
                optionIds: ["strike", "defend"],
                minSelect: 1,
                maxSelect: 1)
            .EventFrame("event-resumed", """{"decision":{"kind":"event_complete"}}""",
                Action("leave-event", "leave_event"))
            .EventTransition("event", new(0), "card-select")
            .ResumeCardPrompt("card-select", ["strike"], "event-resumed");
        NativeRunCoordinator coordinator = new(adapter);
        coordinator.RunReset(Request());

        EnvironmentResult prompt = await coordinator.StepAsync("open-card-select");

        Assert.All(prompt.LegalActions, action => Assert.Equal("choose_cards", action.Kind));
        LegalAction selection = prompt.LegalActions.Single(action =>
            Assert.IsType<string[]>(action.Parameters["option_ids"]).SequenceEqual(["strike"]));
        Assert.DoesNotContain(prompt.LegalActions, action => action.ActionId == "leave-event");

        EnvironmentResult resumed = await coordinator.StepAsync(selection.ActionId);

        Assert.Equal("leave-event", Assert.Single(resumed.LegalActions).ActionId);
        CardSelection applied = Assert.Single(adapter.CardSelections);
        Assert.Equal(selection.ActionId, applied.ActionId);
        Assert.Equal(["strike"], applied.OptionIds);
    }

    [Fact]
    public async Task Nested_reward_prompt_resumes_the_reward_parent_it_suspended()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("event")
            .EventFrame("event", """{"decision":{"kind":"event"}}""",
                Action("open-rewards", "choose_event", ("option_index", 0)))
            .RewardPrompt("outer-reward", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [0])
            .RewardPrompt("inner-reward", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [1])
            .RewardPrompt("outer-resumed", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [])
            .MapFrame("map", """{"decision":{"kind":"map"}}""",
                MapAction("map-0-1", 0, 1, "Monster"))
            .EventTransition("event", new(0), "outer-reward")
            .ResumeRewardPrompt("outer-reward", rewardIndex: 0, "inner-reward")
            .ResumeRewardParent("inner-reward", rewardIndex: 1, "outer-resumed")
            .SkipRewardPrompt("outer-resumed", "map");
        NativeRunCoordinator coordinator = new(adapter);
        coordinator.RunReset(Request());

        EnvironmentResult outer = await coordinator.StepAsync("open-rewards");
        EnvironmentResult inner = await coordinator.StepAsync(
            outer.LegalActions.Single(action => action.Kind == "choose_custom_reward").ActionId);

        Assert.DoesNotContain(inner.LegalActions, action => action.ActionId == "open-rewards");
        Assert.Contains(inner.LegalActions, action =>
            action.Kind == "choose_custom_reward" && Equals(action.Parameters["reward_index"], 1));

        EnvironmentResult resumed = await coordinator.StepAsync(
            inner.LegalActions.Single(action => action.Kind == "choose_custom_reward").ActionId);
        EnvironmentResult map = await coordinator.StepAsync(
            resumed.LegalActions.Single(action => action.Kind == "skip_custom_rewards").ActionId);

        Assert.Equal("map-0-1", Assert.Single(map.LegalActions).ActionId);
        Assert.Collection(
            adapter.RewardSelections,
            selection => Assert.Equal(0, selection.RewardIndex),
            selection => Assert.Equal(1, selection.RewardIndex),
            selection => Assert.Null(selection.RewardIndex));
        Assert.Equal(3, adapter.RewardResumeTokens.Count);
        Assert.NotSame(adapter.RewardResumeTokens[0].Marker, adapter.RewardResumeTokens[1].Marker);
        Assert.Same(adapter.RewardResumeTokens[0].Marker, adapter.RewardResumeTokens[2].Marker);
    }

    [Fact]
    public async Task Restoring_a_nested_reward_rebuilds_its_typed_stack_and_expected_hash()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("outer")
            .RewardPrompt("outer", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [0])
            .RewardPrompt("inner", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [1])
            .RewardPrompt("outer-resumed", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [])
            .MapFrame("map", """{"decision":{"kind":"map"}}""", MapAction("route", 0, 1, "Monster"))
            .ResumeRewardPrompt("outer", rewardIndex: 0, "inner")
            .ResumeRewardParent("inner", rewardIndex: 1, "outer-resumed")
            .SkipRewardPrompt("outer-resumed", "map");
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult outer = coordinator.RunReset(Request());
        EnvironmentResult inner = await coordinator.StepAsync(
            outer.LegalActions.Single(action => action.Kind == "choose_custom_reward").ActionId);
        string branch = coordinator.Fork();

        EnvironmentResult resumed = await coordinator.StepAsync(
            inner.LegalActions.Single(action => action.Kind == "choose_custom_reward").ActionId);
        EnvironmentResult first = await coordinator.StepAsync("skip_custom_rewards");
        EnvironmentResult restored = await coordinator.RestoreAsync(branch);
        resumed = await coordinator.StepAsync(
            restored.LegalActions.Single(action => action.Kind == "choose_custom_reward").ActionId);
        EnvironmentResult replayed = await coordinator.StepAsync("skip_custom_rewards");

        Assert.Equal(first.StateHash, replayed.StateHash);
        Assert.Equal("skip_custom_rewards", Assert.Single(resumed.LegalActions).ActionId);
        Assert.Equal("route", Assert.Single(replayed.LegalActions).ActionId);
    }

    [Fact]
    public async Task Resolving_card_prompts_can_reach_prompt_map_combat_and_terminal_states()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("first")
            .CardPrompt("first", """{"decision":{"kind":"card_choice"}}""", "choice-0", ["a"], 1, 1)
            .CardPrompt("second", """{"decision":{"kind":"card_choice"}}""", "choice-1", ["b"], 1, 1)
            .MapFrame("map", """{"decision":{"kind":"map"}}""",
                MapAction("open-third", 0, 1, "Unknown"))
            .CardPrompt("third", """{"decision":{"kind":"card_choice"}}""", "choice-2", ["c"], 1, 1)
            .Frame("combat", """{"decision":{"kind":"combat"}}""", Action("open-fourth", "end_turn"))
            .CardPrompt("fourth", """{"decision":{"kind":"card_choice"}}""", "choice-3", ["d"], 1, 1)
            .TerminalFrame("terminal", """{"decision":{"kind":"terminal"}}""", victory: true)
            .ResumeCardPrompt("first", ["a"], "second")
            .ResumeCardPrompt("second", ["b"], "map")
            .EnterMapPoint("map", col: 0, row: 1, pointType: "Unknown", to: "third")
            .ResumeCardPrompt("third", ["c"], "combat")
            .Transition("combat", "open-fourth", "fourth")
            .ResumeCardPrompt("fourth", ["d"], "terminal");
        NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult state = coordinator.RunReset(Request());

        state = await coordinator.StepAsync(Assert.Single(state.LegalActions).ActionId);
        Assert.Equal("choose_cards", Assert.Single(state.LegalActions).Kind);
        state = await coordinator.StepAsync(Assert.Single(state.LegalActions).ActionId);
        Assert.Equal("choose_map", Assert.Single(state.LegalActions).Kind);
        state = await coordinator.StepAsync("open-third");
        state = await coordinator.StepAsync(Assert.Single(state.LegalActions).ActionId);
        Assert.Equal("end_turn", Assert.Single(state.LegalActions).Kind);
        state = await coordinator.StepAsync("open-fourth");
        state = await coordinator.StepAsync(Assert.Single(state.LegalActions).ActionId);

        Assert.Empty(state.LegalActions);
        Assert.True(state.Terminated);
        Assert.True(state.Victory);
    }

    [Fact]
    public async Task Restoring_a_prompt_rebuilds_its_continuation_from_the_checkpoint_replay()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("event")
            .EventFrame("event", """{"decision":{"kind":"event"}}""",
                Action("open", "choose_event", ("option_index", 0)))
            .CardPrompt("prompt", """{"decision":{"kind":"card_choice"}}""", "choice-0", ["map", "combat"], 1, 1)
            .MapFrame("map", """{"decision":{"kind":"map"}}""",
                MapAction("route", 0, 1, "Monster"))
            .Frame("combat", """{"decision":{"kind":"combat"}}""", Action("play", "play_card"))
            .EventTransition("event", new(0), "prompt")
            .ResumeCardPrompt("prompt", ["map"], "map")
            .ResumeCardPrompt("prompt", ["combat"], "combat");
        NativeRunCoordinator coordinator = new(adapter);
        coordinator.RunReset(Request());
        EnvironmentResult prompt = await coordinator.StepAsync("open");
        string branch = coordinator.Fork();

        await coordinator.StepAsync(ActionSelecting(prompt, "map").ActionId);
        EnvironmentResult restored = await coordinator.RestoreAsync(branch);
        EnvironmentResult combat = await coordinator.StepAsync(ActionSelecting(restored, "combat").ActionId);

        Assert.Equal("play", Assert.Single(combat.LegalActions).ActionId);
        Assert.Equal(1, JsonSerializer.SerializeToElement(restored.Transition).GetProperty("replayed_actions").GetInt32());
        Assert.Equal(2, adapter.CardResumeTokens.Count);
        Assert.NotSame(adapter.CardResumeTokens[0], adapter.CardResumeTokens[1]);
    }

    [Fact]
    public async Task Option_pick_keeps_its_action_identity_and_parameters()
    {
        LegalAction option = Action("choose_option:choice-0:bundle-1", "choose_option",
            ("choice_id", "choice-0"), ("option_ids", new[] { "bundle-1" }));
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("option")
            .Frame("option", """{"decision":{"kind":"option_choice"}}""", option)
            .MapFrame("map", """{"decision":{"kind":"map"}}""",
                MapAction("route", 0, 1, "Monster"))
            .Transition("option", option.ActionId, "map");
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult before = coordinator.RunReset(Request());
        EnvironmentResult after = await coordinator.StepAsync(option.ActionId);

        Assert.Same(option, Assert.Single(before.LegalActions));
        Assert.Equal("route", Assert.Single(after.LegalActions).ActionId);
    }

    [Fact]
    public async Task Ancient_option_pick_replaces_the_event_until_the_nested_choice_resumes()
    {
        LegalAction option = Action("choose_option:choice-0:bundle-1", "choose_option",
            ("choice_id", "choice-0"), ("option_ids", new[] { "bundle-1" }));
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("event")
            .EventFrame("event", """{"decision":{"kind":"event_choice"}}""",
                Action("open-option", "choose_event", ("option_index", 0)))
            .EventFrame("option", """{"decision":{"kind":"option_choice"}}""", option)
            .EventFrame("complete", """{"decision":{"kind":"event_complete"}}""",
                Action("leave_event", "leave_event"))
            .EventTransition("event", new(0), "option")
            .Transition("option", option.ActionId, "complete");
        NativeRunCoordinator coordinator = new(adapter);
        coordinator.RunReset(Request());

        EnvironmentResult prompt = await coordinator.StepAsync("open-option");
        EnvironmentResult complete = await coordinator.StepAsync(option.ActionId);

        Assert.Same(option, Assert.Single(prompt.LegalActions));
        Assert.Equal("leave_event", Assert.Single(complete.LegalActions).ActionId);
        Assert.Equal([new EventSelection(0)], adapter.EventSelections);
    }

    [Fact]
    public async Task Concurrent_steps_return_the_frame_and_history_for_their_own_action()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("zero")
        {
            ApplyDelay = TimeSpan.FromMilliseconds(30)
        }
            .Frame("zero", """{"step":0}""", Action("advance", "choose_event"))
            .Frame("one", """{"step":1}""", Action("advance", "choose_event"))
            .Frame("two", """{"step":2}""")
            .Transition("zero", "advance", "one")
            .Transition("one", "advance", "two");
        NativeRunCoordinator coordinator = new(adapter);
        coordinator.RunReset(Request());

        Task<EnvironmentResult> first = coordinator.StepAsync("advance");
        Task<EnvironmentResult> second = coordinator.StepAsync("advance");
        EnvironmentResult[] results = await Task.WhenAll(first, second);

        Assert.Equal(1, Assert.IsType<JsonElement>(results[0].Observation).GetProperty("step").GetInt32());
        Assert.Equal(2, Assert.IsType<JsonElement>(results[1].Observation).GetProperty("step").GetInt32());
        Assert.Equal(1, JsonSerializer.SerializeToElement(results[0].Transition).GetProperty("history_length").GetInt32());
        Assert.Equal(2, JsonSerializer.SerializeToElement(results[1].Transition).GetProperty("history_length").GetInt32());
    }

    [Fact]
    public async Task Reset_forgets_old_branches_without_poisoning_the_new_session()
    {
        ScriptedNativeRunAdapter adapter = ScenarioScript();
        NativeRunCoordinator coordinator = new(adapter);
        coordinator.RunReset(Request());
        string oldHandle = coordinator.Fork();

        EnvironmentResult reset = coordinator.RunReset(Request() with { Seed = "ANOTHER-SEED" });
        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(
            () => coordinator.RestoreAsync(oldHandle));

        Assert.Equal("unknown_state_handle", error.Code);
        Assert.Equal(reset.StateHash, coordinator.Observe().StateHash);
    }

    [Fact]
    public void Production_and_scripted_adapters_share_the_native_run_port()
    {
        Assert.True(typeof(INativeRunAdapter).IsAssignableFrom(typeof(NativeRunAdapter)));
        Assert.True(typeof(INativeRunAdapter).IsAssignableFrom(typeof(ScriptedNativeRunAdapter)));
    }

    private static ScriptedNativeRunAdapter ScenarioScript() => ScenarioScript(LoadRecordedScenarioCapture());

    private static ScriptedNativeRunAdapter ScenarioScript(RecordedScenario recorded)
    {
        return new ScriptedNativeRunAdapter("map")
            .MapFrame("map", """
                {"schema_version":3,"run":{"seed":"ANC1ENT01","act_variant":"OVERGROWTH"},"decision":{"kind":"map"}}
                """, MapAction("ancient-door", 0, 0, "Ancient"))
            .EventFrame("ancient", """
                {"schema_version":3,"decision":{"kind":"event"}}
                """,
                Action("ancient-choice-0", "choose_event", ("option_index", 0), ("relic_model_id", "BOOMING_CONCH")),
                Action("ancient-choice-1", "choose_event", ("option_index", 1), ("relic_model_id", "GOLDEN_PEARL")),
                Action("ancient-choice-2", "choose_event", ("option_index", 2), ("relic_model_id", "PRECARIOUS_SHEARS")))
            .Frame("nested", """
                {"schema_version":3,"decision":{"kind":"card_select"}}
                """,
                Action("nested-card-0", "choose_cards", ("option_ids", new[] { "generated-card-choice-0-0-STRIKE_IRONCLAD", "generated-card-choice-0-1-STRIKE_IRONCLAD" })),
                Action("nested-card-1", "choose_cards", ("option_ids", new[] { "generated-card-choice-0-2-DEFEND_IRONCLAD" })))
            .EventFrame("complete", """
                {"schema_version":3,"decision":{"kind":"event_complete"}}
                """, Action("leave_event", "leave_event"))
            .MapFrame("route", """
                {"schema_version":3,"decision":{"kind":"map"}}
                """,
                Action("map-2-1", "choose_map", ("col", 2), ("row", 1), ("point_type", "Monster")),
                Action("map-0-1", "choose_map", ("col", 0), ("row", 1), ("point_type", "Monster")))
            .Frame("combat", recorded.Observation.GetRawText())
            .EnterMapPoint("map", col: 0, row: 0, pointType: "Ancient", to: "ancient")
            .EventTransition("ancient", new(2), "nested")
            .ResumeCardPrompt(
                "nested",
                ["generated-card-choice-0-0-STRIKE_IRONCLAD", "generated-card-choice-0-1-STRIKE_IRONCLAD"],
                "complete")
            .LeaveEvent("complete", "route")
            .EnterMapPoint("route", col: 0, row: 1, pointType: "Monster", to: "combat");
    }

    private static LegalAction Action(string id, string kind, params (string Key, object? Value)[] parameters) =>
        new(id, kind, parameters.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));

    private static LegalAction MapAction(string id, int col, int row, string pointType) =>
        Action(id, "choose_map", ("col", col), ("row", row), ("point_type", pointType));

    private static LegalAction ActionWith(EnvironmentResult state, string kind, string? key = null, object? value = null) =>
        state.LegalActions.Single(action => action.Kind == kind && (key is null || Equals(action.Parameters[key], value)));

    private static LegalAction ActionSelecting(EnvironmentResult state, string optionId) =>
        state.LegalActions.Single(action =>
            Assert.IsType<string[]>(action.Parameters["option_ids"]).SequenceEqual([optionId]));

    private static ResetRequest Request() => new(
        new(), "ANC1ENT01", new Dictionary<string, int>(), "IRONCLAD", 0, "first", 80, 80,
        Array.Empty<CardSpec>(), Array.Empty<string>(), Array.Empty<RelicSpec>(), Array.Empty<PotionSpec>(), 99,
        ResetMode: ResetModes.Run);

    private static RecordedScenario LoadRecordedScenarioCapture()
    {
        string path = Path.Combine(AppContext.BaseDirectory, "GeneratedScenarios", "recorded-scenarios.jsonl.gz");
        using FileStream file = File.OpenRead(path);
        using GZipStream gzip = new(file, CompressionMode.Decompress);
        using StreamReader reader = new(gzip);
        while (reader.ReadLine() is { } line)
        {
            using JsonDocument document = JsonDocument.Parse(line);
            JsonElement recipe = document.RootElement.GetProperty("recipe");
            if (recipe.GetProperty("nested_choices").GetArrayLength() == 0) continue;
            return new(
                recipe.Clone(),
                document.RootElement.GetProperty("combat_initial_state").Clone(),
                document.RootElement.GetProperty("state_hash").GetString()!);
        }
        throw new InvalidOperationException("The recorded Generated scenario corpus contains no recipe with a nested choice.");
    }

    private static void AssertRecordedRecipe(JsonElement actual, RecordedRecipe expected)
    {
        Assert.Equal("IRONCLAD", actual.GetProperty("character").GetString());
        Assert.Equal(0, actual.GetProperty("ascension").GetInt32());
        Assert.Equal("ANC1ENT01", actual.GetProperty("seed").GetString());
        Assert.Equal(expected.AncientOptionIndex, actual.GetProperty("ancient_choice").GetProperty("option_index").GetInt32());
        Assert.Equal("PRECARIOUS_SHEARS", actual.GetProperty("ancient_choice").GetProperty("relic_model_id").GetString());
        Assert.Equal(expected.NestedOptionIndices, actual.GetProperty("nested_choices").EnumerateArray().Select(choice => choice.GetProperty("selected_index").GetInt32()).ToArray());
        Assert.Equal(expected.NodeCol, actual.GetProperty("node").GetProperty("col").GetInt32());
        Assert.Equal(expected.NodeRow, actual.GetProperty("node").GetProperty("row").GetInt32());
        Assert.Equal(expected.Encounter, actual.GetProperty("encounter").GetString());
    }

    private sealed record RecordedScenario(JsonElement Recipe, JsonElement Observation, string StateHash);
    private sealed record RecordedRecipe(
        int AncientOptionIndex,
        IReadOnlyList<int> NestedOptionIndices,
        int NodeCol,
        int NodeRow,
        string Encounter,
        string ObservationSha256);
}
