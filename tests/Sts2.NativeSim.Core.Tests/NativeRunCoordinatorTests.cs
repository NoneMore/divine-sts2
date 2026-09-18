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

        state = await coordinator.StepAsync(ActionWith(state, "enter_ancient").ActionId);
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
    }

    [Fact]
    public async Task Combat_can_transition_through_reward_to_the_map()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("combat")
            .Frame("combat", """{"schema_version":3,"decision":{"kind":"combat"}}""",
                Action("finish-combat", "end_turn"))
            .Frame("reward", """{"schema_version":3,"decision":{"kind":"card_reward"}}""",
                Action("reward-0", "choose_reward", ("option_index", 0)))
            .Frame("map", """{"schema_version":3,"decision":{"kind":"map"}}""",
                Action("map-0-2", "choose_map", ("col", 0), ("row", 2)))
            .Transition("combat", "finish-combat", "reward")
            .Transition("reward", "reward-0", "map");
        NativeRunCoordinator coordinator = new(adapter);

        coordinator.RunReset(Request());
        EnvironmentResult reward = await coordinator.StepAsync("finish-combat");
        EnvironmentResult map = await coordinator.StepAsync("reward-0");

        Assert.Equal("choose_reward", Assert.Single(reward.LegalActions).Kind);
        Assert.Equal("choose_map", Assert.Single(map.LegalActions).Kind);
    }

    [Fact]
    public async Task Card_select_prompt_suspends_its_parent_until_the_typed_selection_resumes_it()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("event")
            .Frame("event", """{"decision":{"kind":"event"}}""",
                Action("open-card-select", "choose_event"),
                Action("leave-event", "leave_event"))
            .CardPrompt(
                "card-select",
                """{"decision":{"kind":"card_choice"}}""",
                choiceId: "card-choice-0",
                optionIds: ["strike", "defend"],
                minSelect: 1,
                maxSelect: 1)
            .Frame("event-resumed", """{"decision":{"kind":"event_complete"}}""",
                Action("leave-event", "leave_event"))
            .Transition("event", "open-card-select", "card-select")
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
    }

    [Fact]
    public async Task Nested_reward_prompt_resumes_the_reward_parent_it_suspended()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("event")
            .Frame("event", """{"decision":{"kind":"event"}}""",
                Action("open-rewards", "choose_event"))
            .RewardPrompt("outer-reward", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [0])
            .RewardPrompt("inner-reward", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [1])
            .RewardPrompt("outer-resumed", """{"decision":{"kind":"custom_reward_choice"}}""", rewardIndices: [])
            .Frame("map", """{"decision":{"kind":"map"}}""", Action("map-0-1", "choose_map"))
            .Transition("event", "open-rewards", "outer-reward")
            .ResumeRewardPrompt("outer-reward", rewardIndex: 0, "inner-reward")
            .ResumeRewardPrompt("inner-reward", rewardIndex: 1, "outer-resumed")
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
    }

    [Fact]
    public async Task Resolving_card_prompts_can_reach_prompt_map_combat_and_terminal_states()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("first")
            .CardPrompt("first", """{"decision":{"kind":"card_choice"}}""", "choice-0", ["a"], 1, 1)
            .CardPrompt("second", """{"decision":{"kind":"card_choice"}}""", "choice-1", ["b"], 1, 1)
            .Frame("map", """{"decision":{"kind":"map"}}""", Action("open-third", "choose_map"))
            .CardPrompt("third", """{"decision":{"kind":"card_choice"}}""", "choice-2", ["c"], 1, 1)
            .Frame("combat", """{"decision":{"kind":"combat"}}""", Action("open-fourth", "end_turn"))
            .CardPrompt("fourth", """{"decision":{"kind":"card_choice"}}""", "choice-3", ["d"], 1, 1)
            .TerminalFrame("terminal", """{"decision":{"kind":"terminal"}}""", victory: true)
            .ResumeCardPrompt("first", ["a"], "second")
            .ResumeCardPrompt("second", ["b"], "map")
            .Transition("map", "open-third", "third")
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
            .Frame("event", """{"decision":{"kind":"event"}}""", Action("open", "choose_event"))
            .CardPrompt("prompt", """{"decision":{"kind":"card_choice"}}""", "choice-0", ["map", "combat"], 1, 1)
            .Frame("map", """{"decision":{"kind":"map"}}""", Action("route", "choose_map"))
            .Frame("combat", """{"decision":{"kind":"combat"}}""", Action("play", "play_card"))
            .Transition("event", "open", "prompt")
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
    }

    [Fact]
    public async Task Option_pick_keeps_its_action_identity_and_parameters()
    {
        LegalAction option = Action("choose_option:choice-0:bundle-1", "choose_option",
            ("choice_id", "choice-0"), ("option_ids", new[] { "bundle-1" }));
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("option")
            .Frame("option", """{"decision":{"kind":"option_choice"}}""", option)
            .Frame("map", """{"decision":{"kind":"map"}}""", Action("route", "choose_map"))
            .Transition("option", option.ActionId, "map");
        NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult before = coordinator.RunReset(Request());
        EnvironmentResult after = await coordinator.StepAsync(option.ActionId);

        Assert.Same(option, Assert.Single(before.LegalActions));
        Assert.Equal("route", Assert.Single(after.LegalActions).ActionId);
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
    public void Reflection_adapter_and_scripted_adapter_share_the_compatibility_port()
    {
        Assert.True(typeof(IRunSessionCompatibilityAdapter).IsAssignableFrom(typeof(LegacyRunSessionAdapter)));
        Assert.True(typeof(IRunSessionCompatibilityAdapter).IsAssignableFrom(typeof(ScriptedNativeRunAdapter)));
    }

    private static ScriptedNativeRunAdapter ScenarioScript() => ScenarioScript(LoadRecordedScenarioCapture());

    private static ScriptedNativeRunAdapter ScenarioScript(RecordedScenario recorded)
    {
        return new ScriptedNativeRunAdapter("map")
            .Frame("map", """
                {"schema_version":3,"run":{"seed":"ANC1ENT01","act_variant":"OVERGROWTH"},"decision":{"kind":"map"}}
                """, Action("ancient-door", "enter_ancient"))
            .Frame("ancient", """
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
            .Frame("complete", """
                {"schema_version":3,"decision":{"kind":"event_complete"}}
                """, Action("leave_event", "leave_event"))
            .Frame("route", """
                {"schema_version":3,"decision":{"kind":"map"}}
                """,
                Action("map-2-1", "choose_map", ("col", 2), ("row", 1), ("point_type", "Monster")),
                Action("map-0-1", "choose_map", ("col", 0), ("row", 1), ("point_type", "Monster")))
            .Frame("combat", recorded.Observation.GetRawText())
            .Transition("map", "ancient-door", "ancient")
            .Transition("ancient", "ancient-choice-2", "nested")
            .Transition("nested", "nested-card-0", "complete")
            .Transition("complete", "leave_event", "route")
            .Transition("route", "map-0-1", "combat");
    }

    private static LegalAction Action(string id, string kind, params (string Key, object? Value)[] parameters) =>
        new(id, kind, parameters.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));

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
