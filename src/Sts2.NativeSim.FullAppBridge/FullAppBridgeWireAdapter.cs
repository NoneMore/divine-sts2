using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.FullAppBridge;

public static class FullAppBridgeWireAdapter
{
    private static readonly JsonElement EmptyParameters = JsonSerializer.Deserialize<JsonElement>("{}");

    public static RpcRequest DecodeRequest(string json)
    {
        BridgeRequest request = JsonSerializer.Deserialize<BridgeRequest>(json)
            ?? throw new JsonException("Empty request.");
        return new RpcRequest(
            request.Id.ToString(CultureInfo.InvariantCulture),
            request.Method,
            request.Parameters ?? EmptyParameters);
    }

    public static string EncodeResponse(RpcResponse response)
    {
        if (!int.TryParse(response.Id, NumberStyles.None, CultureInfo.InvariantCulture, out int id))
            throw new JsonException($"FullAppBridge request id '{response.Id}' is not an integer.");

        return JsonSerializer.Serialize(
            new BridgeResponse(id, response.Ok ? response.Result : null, response.Error?.Message),
            BridgeJson.Options);
    }

    public static bool TryReadInt32Parameter(
        JsonElement parameters,
        string name,
        out int value)
    {
        value = default;
        return parameters.ValueKind == JsonValueKind.Object
            && parameters.TryGetProperty(name, out JsonElement parameter)
            && int.TryParse(parameter.ToString(), out value);
    }

    private sealed record BridgeRequest(
        [property: JsonPropertyName("id")] int Id,
        [property: JsonPropertyName("method")] string Method,
        [property: JsonPropertyName("params")] JsonElement? Parameters);

    private sealed record BridgeResponse(
        [property: JsonPropertyName("id")] int Id,
        [property: JsonPropertyName("result")] object? Result,
        [property: JsonPropertyName("error")] string? Error);
}
