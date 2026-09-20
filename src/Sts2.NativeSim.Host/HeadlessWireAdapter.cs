using System.Text.Json;
using System.Text.Json.Serialization;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Host;

public static class HeadlessWireAdapter
{
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new HeadlessLegalActionConverter() },
    };

    public static RpcRequest DecodeRequest(string json)
    {
        HeadlessRequest request = JsonSerializer.Deserialize<HeadlessRequest>(json, Json)
            ?? throw new JsonException("Empty request.");
        return new RpcRequest(request.Id, request.Method, request.Parameters);
    }

    public static string EncodeResponse(RpcResponse response) =>
        JsonSerializer.Serialize(
            new HeadlessResponse(response.Id, response.Ok, response.Result, response.Error),
            Json);

    private sealed record HeadlessRequest(
        [property: JsonPropertyName("id")] string Id,
        [property: JsonPropertyName("method")] string Method,
        [property: JsonPropertyName("params")] JsonElement Parameters);
    private sealed record HeadlessResponse(
        string Id,
        bool Ok,
        object? Result,
        ProtocolError? Error);
}
