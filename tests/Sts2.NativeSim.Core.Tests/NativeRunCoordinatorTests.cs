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
        EnvironmentResult choice = await coordinator.StepAsync("ancient-choice-1");
        Assert.Equal("nested-card-0", Assert.Single(choice.LegalActions).ActionId);

        EnvironmentResult restored = await coordinator.RestoreAsync(branch);
        Assert.Equal(ancient.StateHash, restored.StateHash);
        Assert.Equal("ancient-choice-1", Assert.Single(restored.LegalActions).ActionId);
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
        ScriptedNativeRunAdapter adapter = new ScriptedNativeRunAdapter("collision")
            .Frame("collision", "COLLISION", """
                {"schema_version":3,"decision":{"kind":"event"}}
                """,
                Action("same-id", "choose_event", ("option_index", 0)),
                Action("same-id", "choose_event", ("option_index", 1)));
        using NativeRunCoordinator coordinator = new(adapter);

        ProtocolException error = Assert.Throws<ProtocolException>(() => coordinator.RunReset(Request()));

        Assert.Equal("action_id_collision", error.Code);
        Assert.Equal(0, adapter.MutationCount);
        await Assert.ThrowsAsync<ProtocolException>(() => coordinator.StepAsync("same-id"));
        Assert.Equal(0, adapter.MutationCount);
    }

    [Fact]
    public async Task Recorded_generated_scenario_recipe_reaches_the_recorded_combat_initial_state()
    {
        ScriptedNativeRunAdapter adapter = ScenarioScript();
        using NativeRunCoordinator coordinator = new(adapter);
        EnvironmentResult state = coordinator.RunReset(Request());

        state = await coordinator.StepAsync(ActionWith(state, "enter_ancient").ActionId);
        state = await coordinator.StepAsync(ActionWith(state, "choose_event", "option_index", 1).ActionId);
        state = await coordinator.StepAsync(state.LegalActions[0].ActionId);
        state = await coordinator.StepAsync("leave_event");
        state = await coordinator.StepAsync(ActionWith(state, "choose_map", "row", 1).ActionId);

        const string expectedObservation = """
            {"schema_version":3,"run":{"seed":"CORE-SEAM","act_variant":"OVERGROWTH","act_floor":1,"total_floor":1},"combat":{"encounter":"CULTIST","turn":1},"decision":{"kind":"combat"}}
            """;
        JsonElement actual = Assert.IsType<JsonElement>(state.Observation);
        Assert.Equal("CULTIST", actual.GetProperty("combat").GetProperty("encounter").GetString());
        Assert.Equal(JsonDocument.Parse(expectedObservation).RootElement.GetRawText(), actual.GetRawText());
        Assert.Equal("RECORDED-COMBAT-HASH", state.StateHash);
    }

    [Fact]
    public void Reflection_adapter_and_scripted_adapter_share_the_native_port()
    {
        Assert.True(typeof(INativeRunAdapter).IsAssignableFrom(typeof(ReflectionNativeRunAdapter)));
        Assert.True(typeof(INativeRunAdapter).IsAssignableFrom(typeof(ScriptedNativeRunAdapter)));
    }

    private static ScriptedNativeRunAdapter ScenarioScript()
    {
        return new ScriptedNativeRunAdapter("map")
            .Frame("map", "MAP-HASH", """
                {"schema_version":3,"run":{"seed":"CORE-SEAM","act_variant":"OVERGROWTH"},"decision":{"kind":"map"}}
                """, Action("ancient-door", "enter_ancient"))
            .Frame("ancient", "ANCIENT-HASH", """
                {"schema_version":3,"decision":{"kind":"event"}}
                """, Action("ancient-choice-1", "choose_event", ("option_index", 1), ("relic_model_id", "NEOW_BONUS")))
            .Frame("nested", "NESTED-HASH", """
                {"schema_version":3,"decision":{"kind":"card_select"}}
                """, Action("nested-card-0", "choose_cards", ("option_ids", new[] { "card-0" })))
            .Frame("complete", "ANCIENT-COMPLETE-HASH", """
                {"schema_version":3,"decision":{"kind":"event_complete"}}
                """, Action("leave_event", "leave_event"))
            .Frame("route", "ROUTE-HASH", """
                {"schema_version":3,"decision":{"kind":"map"}}
                """, Action("map-0-1", "choose_map", ("col", 0), ("row", 1), ("point_type", "Monster")))
            .Frame("combat", "RECORDED-COMBAT-HASH", """
                {"schema_version":3,"run":{"seed":"CORE-SEAM","act_variant":"OVERGROWTH","act_floor":1,"total_floor":1},"combat":{"encounter":"CULTIST","turn":1},"decision":{"kind":"combat"}}
                """)
            .Transition("map", "ancient-door", "ancient")
            .Transition("ancient", "ancient-choice-1", "nested")
            .Transition("nested", "nested-card-0", "complete")
            .Transition("complete", "leave_event", "route")
            .Transition("route", "map-0-1", "combat");
    }

    private static LegalAction Action(string id, string kind, params (string Key, object? Value)[] parameters) =>
        new(id, kind, parameters.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));

    private static LegalAction ActionWith(EnvironmentResult state, string kind, string? key = null, object? value = null) =>
        state.LegalActions.Single(action => action.Kind == kind && (key is null || Equals(action.Parameters[key], value)));

    private static ResetRequest Request() => new(
        new(), "CORE-SEAM", new Dictionary<string, int>(), "IRONCLAD", 0, "first", 80, 80,
        Array.Empty<CardSpec>(), Array.Empty<string>(), Array.Empty<RelicSpec>(), Array.Empty<PotionSpec>(), 99,
        ResetMode: ResetModes.Run);
}
