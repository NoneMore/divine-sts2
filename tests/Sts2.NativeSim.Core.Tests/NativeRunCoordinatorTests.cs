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
