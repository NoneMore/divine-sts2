using System.Text.Json;
using Sts2.NativeSim.FullAppBridge;
using Sts2.NativeSim.Host;
using Sts2.NativeSim.Protocol;
using Xunit;

namespace Sts2.NativeSim.Protocol.Tests;

public sealed class HostWireAdapterTests
{
    [Fact]
    public void HeadlessAdapterPreservesItsRequestAndResponseEnvelope()
    {
        RpcRequest request = HeadlessWireAdapter.DecodeRequest(
            """{"id":"request-7","method":"step","params":{"action_id":"end_turn"}}""");

        Assert.Equal("request-7", request.Id);
        Assert.Equal("step", request.Method);
        Assert.Equal("end_turn", request.Parameters.GetProperty("action_id").GetString());

        string encoded = HeadlessWireAdapter.EncodeResponse(
            new RpcResponse(request.Id, false, Error: new ProtocolError("invalid_action", "No such action.")));
        using JsonDocument document = JsonDocument.Parse(encoded);
        JsonElement root = document.RootElement;
        Assert.Equal("request-7", root.GetProperty("id").GetString());
        Assert.False(root.GetProperty("ok").GetBoolean());
        Assert.Equal("invalid_action", root.GetProperty("error").GetProperty("code").GetString());
        Assert.Equal("No such action.", root.GetProperty("error").GetProperty("message").GetString());
        Assert.False(root.TryGetProperty("result", out _));
    }

    [Fact]
    public void FullAppBridgeAdapterPreservesItsRequestAndErrorEnvelope()
    {
        RpcRequest request = FullAppBridgeWireAdapter.DecodeRequest(
            """{"id":42,"method":"step","params":{"action_id":"end_turn"}}""");

        Assert.Equal("42", request.Id);
        Assert.Equal("step", request.Method);
        Assert.Equal("end_turn", request.Parameters.GetProperty("action_id").GetString());

        string encoded = FullAppBridgeWireAdapter.EncodeResponse(
            new RpcResponse(request.Id, false, Error: new ProtocolError("invalid_action", "No such action.")));
        using JsonDocument document = JsonDocument.Parse(encoded);
        JsonElement root = document.RootElement;
        Assert.Equal(42, root.GetProperty("id").GetInt32());
        Assert.Equal("No such action.", root.GetProperty("error").GetString());
        Assert.False(root.TryGetProperty("ok", out _));
        Assert.False(root.TryGetProperty("result", out _));
    }

    [Theory]
    [InlineData("5", 5)]
    [InlineData("\"5\"", 5)]
    public void FullAppBridgeAdapterAcceptsLegacyIntegerParameterForms(string value, int expected)
    {
        string json = "{\"id\":42,\"method\":\"start_run\",\"params\":{\"ascension\":" + value + "}}";
        RpcRequest request = FullAppBridgeWireAdapter.DecodeRequest(json);

        Assert.True(FullAppBridgeWireAdapter.TryReadInt32Parameter(
            request.Parameters,
            "ascension",
            out int actual));
        Assert.Equal(expected, actual);
    }

    [Fact]
    public void HostAdaptersEncodeOneSemanticLegalActionInTheirOwnDialects()
    {
        LegalAction action = new(
            "play:strike-1:none",
            "play_card",
            new Dictionary<string, object?> { ["card_id"] = "STRIKE_IRONCLAD" },
            "Play Strike");

        using JsonDocument headless = JsonDocument.Parse(HeadlessWireAdapter.EncodeResponse(
            new RpcResponse("headless-1", true, new[] { action })));
        JsonElement headlessAction = headless.RootElement.GetProperty("result")[0];
        Assert.Equal("play_card", headlessAction.GetProperty("kind").GetString());
        Assert.Equal("STRIKE_IRONCLAD", headlessAction.GetProperty("parameters").GetProperty("card_id").GetString());
        Assert.False(headlessAction.TryGetProperty("action_type", out _));
        Assert.False(headlessAction.TryGetProperty("description", out _));

        using JsonDocument bridge = JsonDocument.Parse(FullAppBridgeWireAdapter.EncodeResponse(
            new RpcResponse("9", true, new[] { action })));
        JsonElement bridgeAction = bridge.RootElement.GetProperty("result")[0];
        Assert.Equal("play_card", bridgeAction.GetProperty("action_type").GetString());
        Assert.Equal("STRIKE_IRONCLAD", bridgeAction.GetProperty("metadata").GetProperty("card_id").GetString());
        Assert.Equal("Play Strike", bridgeAction.GetProperty("description").GetString());
        Assert.False(bridgeAction.TryGetProperty("kind", out _));
    }
}
