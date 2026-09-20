using System.Text.Json;
using System.Text.Json.Nodes;
using Sts2.NativeSim.FullAppBridge;
using Sts2.NativeSim.Host;
using Sts2.NativeSim.Protocol;
using Sts2.NativeSim.TraceExporter;
using Xunit;

namespace Sts2.NativeSim.Protocol.Tests;

public sealed class CanonicalObservationContractTests
{
    [Fact]
    public void EveryPublishedCaptureIsReadByTheTypedContract()
    {
        using JsonDocument fixture = JsonDocument.Parse(File.ReadAllText("fixtures/canonical-observations.json"));

        foreach (JsonProperty capture in fixture.RootElement.EnumerateObject())
        {
            CanonicalObservation observation = CanonicalObservationJson.Deserialize(capture.Value.GetRawText());

            Assert.Equal(ProtocolConstants.ObservationSchemaVersion, observation.SchemaVersion);
            Assert.False(string.IsNullOrWhiteSpace(observation.Decision.Kind), capture.Name);
            Assert.NotNull(observation.Stage);
        }
    }

    [Fact]
    public void PublishedSchemaIsGeneratedFromTheTypedContract()
    {
        using JsonDocument generated = JsonDocument.Parse(CanonicalObservationSchema.Generate());
        using JsonDocument published = JsonDocument.Parse(File.ReadAllText("schemas/canonical-state.schema.json"));

        Assert.True(JsonElement.DeepEquals(generated.RootElement, published.RootElement));
    }

    [Fact]
    public void HeadlessWireEncodesRuntimeObservationsThroughTheTypedContract()
    {
        using JsonDocument fixture = JsonDocument.Parse(File.ReadAllText("fixtures/canonical-observations.json"));
        JsonElement runtimeObservation = fixture.RootElement.GetProperty("run_map_choice").Clone();
        EnvironmentResult result = new(runtimeObservation, "HEADLESS-HASH", [], false, false, "handle-1");

        string json = HeadlessWireAdapter.EncodeResponse(new RpcResponse("request-1", true, result));

        using JsonDocument encoded = JsonDocument.Parse(json);
        JsonElement observation = encoded.RootElement.GetProperty("result").GetProperty("observation");
        Assert.True(JsonElement.DeepEquals(runtimeObservation, observation));
        Assert.Equal("HEADLESS-HASH", encoded.RootElement.GetProperty("result").GetProperty("state_hash").GetString());
    }

    [Fact]
    public void HeadlessWireRejectsAnObservationOutsideTheTypedContract()
    {
        JsonObject runtimeObservation = JsonNode.Parse(
            JsonDocument.Parse(File.ReadAllText("fixtures/canonical-observations.json"))
                .RootElement.GetProperty("run_map_choice").GetRawText())!.AsObject();
        runtimeObservation["unexpected_runtime_block"] = new JsonObject();
        EnvironmentResult result = new(runtimeObservation, "HEADLESS-HASH", [], false, false, "handle-1");

        Assert.Throws<JsonException>(() =>
            HeadlessWireAdapter.EncodeResponse(new RpcResponse("request-1", true, result)));
    }

    [Fact]
    public void FullAppBridgeEncodesItsCombatSnapshotIntoTheTypedContract()
    {
        using JsonDocument fixture = JsonDocument.Parse(File.ReadAllText("fixtures/canonical-observations.json"));
        JsonElement expected = fixture.RootElement.GetProperty("run_combat_action");
        ObservationDto runtime = new()
        {
            Phase = "combat",
            GameBuild = JsonSerializer.Deserialize<GameBuildDto>(expected.GetProperty("game_build"))!,
            Run = JsonSerializer.Deserialize<RunObservationDto>(expected.GetProperty("run"))!,
            Combat = JsonSerializer.Deserialize<CombatObservationDto>(expected.GetProperty("combat"))!,
            Inventory = JsonSerializer.Deserialize<InventoryObservationDto>(expected.GetProperty("inventory"))!,
        };
        List<LegalAction> actions = JsonSerializer.Deserialize<List<LegalAction>>(
            expected.GetProperty("decision").GetProperty("legal_actions"))!;

        CanonicalObservation actual = FullAppCanonicalObservationEncoder.Encode(runtime, actions);

        Assert.Equal("combat_action", actual.Decision.Kind);
        Assert.Equal(expected.GetProperty("combat").GetProperty("encounter").GetString(), actual.Combat!.Encounter);
        Assert.Equal(expected.GetProperty("run").GetProperty("seed").GetString(), actual.Run.Seed);
    }

    [Fact]
    public void FullAppBridgeMapsANonCombatRoomToItsCanonicalStage()
    {
        ObservationDto runtime = new()
        {
            Phase = "map",
            GameBuild = new GameBuildDto { Version = "v", AssemblySha256 = "a", PckSha256 = "p" },
            Run = new RunObservationDto
            {
                Seed = "SEED",
                Ascension = 0,
                Gold = 99,
                ActVariant = "OVERGROWTH",
                ActIndex = 0,
                ActFloor = 0,
                TotalFloor = 1,
            },
            MapCoord = new CoordObservationDto { Col = 3, Row = 0 },
            Room = new RoomObservationDto { RoomType = "Map", Options = ["1:Monster", "2:Unknown"] },
        };

        CanonicalObservation actual = FullAppCanonicalObservationEncoder.Encode(runtime, []);

        Assert.IsType<CanonicalMapObservationStage>(actual.Stage);
        Assert.Equal("map_choice", actual.Decision.Kind);
        Assert.Equal(2, actual.Map!.Points.Count);
    }

    [Fact]
    public void TraceExporterEncodesCheckpointsIntoTheTypedContract()
    {
        using JsonDocument fixture = JsonDocument.Parse(File.ReadAllText("fixtures/canonical-observations.json"));
        JsonElement runtime = fixture.RootElement.GetProperty("standalone_combat").Clone();

        CanonicalObservation actual = TraceCanonicalObservationEncoder.Encode(runtime);

        Assert.Equal(ProtocolConstants.ObservationSchemaVersion, actual.SchemaVersion);
        Assert.Equal("combat_action", actual.Decision.Kind);
    }
}
