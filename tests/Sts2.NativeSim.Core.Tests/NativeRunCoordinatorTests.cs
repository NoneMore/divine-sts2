using System.IO.Compression;
using System.Text.Json;
using Sts2.NativeSim.Core;
using Sts2.NativeSim.Protocol;
using Xunit;

namespace Sts2.NativeSim.Core.Tests;

public sealed class NativeRunCoordinatorTests
{
    [Fact]
    public async Task Caller_can_reset_capture_step_fork_and_restore()
    {
        ScriptedNativeRunAdapter adapter = ScenarioScript();
        using NativeRunCoordinator coordinator = new(adapter);

        EnvironmentResult reset = coordinator.RunReset(Request());
        Assert.Equal("ancient-door", Assert.Single(coordinator.LegalActions()).ActionId);
        Assert.Equal(reset.StateHash, coordinator.Observe().StateHash);

        EnvironmentResult ancient = await coordinator.StepAsync("ancient-door");
        string branch = coordinator.Fork();
        EnvironmentResult choice = await coordinator.StepAsync("ancient-choice-2");
        Assert.Equal("nested-card-0", Assert.Single(choice.LegalActions).ActionId);

        EnvironmentResult restored = await coordinator.RestoreAsync(branch);
        Assert.Equal(ancient.StateHash, restored.StateHash);
        Assert.Equal("ancient-choice-2", Assert.Single(restored.LegalActions).ActionId);
    }

    [Fact]
    public async Task Invalid_action_does_not_reach_the_native_port_or_mutate_state()
    {
        ScriptedNativeRunAdapter adapter = ScenarioScript();
        using NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult before = coordinator.RunReset(Request());

        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(
            () => coordinator.StepAsync("not-advertised"));

        Assert.Equal("invalid_action", error.Code);
        Assert.Equal(0, adapter.MutationCount);
        Assert.Equal(before.StateHash, coordinator.Observe().StateHash);
    }

    [Fact]
    public async Task Action_id_collision_does_not_reach_the_native_port_or_mutate_state()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("safe")
            .Frame("safe", "SAFE", """
                {"schema_version":3,"decision":{"kind":"event"}}
                """, Action("enter-collision", "choose_event"))
            .Frame("collision", "COLLISION", """
                {"schema_version":3,"decision":{"kind":"event"}}
                """,
                Action("same-id", "choose_event", ("option_index", 0)),
                Action("same-id", "choose_event", ("option_index", 1)))
            .Transition("safe", "enter-collision", "collision");
        using NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult before = coordinator.RunReset(Request());

        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(
            () => coordinator.StepAsync("enter-collision"));

        Assert.Equal("action_id_collision", error.Code);
        Assert.Equal(0, adapter.MutationCount);
        Assert.Equal(before.StateHash, coordinator.Observe().StateHash);
    }

    [Fact]
    public async Task Recorded_generated_scenario_recipe_reaches_the_recorded_combat_initial_state()
    {
        RecordedScenario recorded = LoadRecordedScenario();
        ScriptedNativeRunAdapter adapter = ScenarioScript(recorded);
        using NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult state = coordinator.RunReset(Request());

        state = await coordinator.StepAsync(ActionWith(state, "enter_ancient").ActionId);
        int optionIndex = recorded.Recipe.GetProperty("ancient_choice").GetProperty("option_index").GetInt32();
        state = await coordinator.StepAsync(ActionWith(state, "choose_event", "option_index", optionIndex).ActionId);
        foreach (JsonElement nested in recorded.Recipe.GetProperty("nested_choices").EnumerateArray())
            state = await coordinator.StepAsync(state.LegalActions[nested.GetProperty("selected_index").GetInt32()].ActionId);
        state = await coordinator.StepAsync("leave_event");
        int row = recorded.Recipe.GetProperty("node").GetProperty("row").GetInt32();
        state = await coordinator.StepAsync(ActionWith(state, "choose_map", "row", row).ActionId);

        JsonElement actual = Assert.IsType<JsonElement>(state.Observation);
        Assert.Equal(recorded.Recipe.GetProperty("encounter").GetString(), actual.GetProperty("combat").GetProperty("encounter").GetString());
        Assert.Equal(recorded.Observation.GetRawText(), actual.GetRawText());
        Assert.Equal(recorded.StateHash, state.StateHash);
    }

    [Fact]
    public async Task Combat_can_transition_through_reward_to_the_map()
    {
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("combat")
            .Frame("combat", "COMBAT", """{"schema_version":3,"decision":{"kind":"combat"}}""",
                Action("finish-combat", "end_turn"))
            .Frame("reward", "REWARD", """{"schema_version":3,"decision":{"kind":"card_reward"}}""",
                Action("reward-0", "choose_reward", ("option_index", 0)))
            .Frame("map", "MAP", """{"schema_version":3,"decision":{"kind":"map"}}""",
                Action("map-0-2", "choose_map", ("col", 0), ("row", 2)))
            .Transition("combat", "finish-combat", "reward")
            .Transition("reward", "reward-0", "map");
        using NativeRunCoordinator coordinator = new(adapter);

        coordinator.RunReset(Request());
        EnvironmentResult reward = await coordinator.StepAsync("finish-combat");
        EnvironmentResult map = await coordinator.StepAsync("reward-0");

        Assert.Equal("choose_reward", Assert.Single(reward.LegalActions).Kind);
        Assert.Equal("choose_map", Assert.Single(map.LegalActions).Kind);
    }

    [Fact]
    public void Reflection_adapter_and_scripted_adapter_share_the_native_port()
    {
        Assert.True(typeof(INativeRunAdapter).IsAssignableFrom(typeof(ReflectionNativeRunAdapter)));
        Assert.True(typeof(INativeRunAdapter).IsAssignableFrom(typeof(ScriptedNativeRunAdapter)));
    }

    private static ScriptedNativeRunAdapter ScenarioScript() => ScenarioScript(LoadRecordedScenario());

    private static ScriptedNativeRunAdapter ScenarioScript(RecordedScenario recorded)
    {
        return new ScriptedNativeRunAdapter("map")
            .Frame("map", "MAP-HASH", """
                {"schema_version":3,"run":{"seed":"ANC1ENT01","act_variant":"OVERGROWTH"},"decision":{"kind":"map"}}
                """, Action("ancient-door", "enter_ancient"))
            .Frame("ancient", "ANCIENT-HASH", """
                {"schema_version":3,"decision":{"kind":"event"}}
                """, Action("ancient-choice-2", "choose_event", ("option_index", 2), ("relic_model_id", "PRECARIOUS_SHEARS")))
            .Frame("nested", "NESTED-HASH", """
                {"schema_version":3,"decision":{"kind":"card_select"}}
                """, Action("nested-card-0", "choose_cards", ("option_ids", new[] { "generated-card-choice-0-0-STRIKE_IRONCLAD", "generated-card-choice-0-1-STRIKE_IRONCLAD" })))
            .Frame("complete", "ANCIENT-COMPLETE-HASH", """
                {"schema_version":3,"decision":{"kind":"event_complete"}}
                """, Action("leave_event", "leave_event"))
            .Frame("route", "ROUTE-HASH", """
                {"schema_version":3,"decision":{"kind":"map"}}
                """, Action("map-0-1", "choose_map", ("col", 0), ("row", 1), ("point_type", "Monster")))
            .Frame("combat", recorded.StateHash, recorded.Observation.GetRawText())
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

    private static RecordedScenario LoadRecordedScenario()
    {
        string path = Path.Combine(AppContext.BaseDirectory, "Fixtures", "recorded-generated-scenarios.jsonl.gz");
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
        throw new InvalidOperationException("The recorded fixture contains no Generated scenario with a nested choice.");
    }

    private sealed record RecordedScenario(JsonElement Recipe, JsonElement Observation, string StateHash);
}
