using System.Text.Json;
using System.Text.Json.Serialization;

namespace Sts2.NativeSim.Protocol;

public static class CanonicalObservationJson
{
    public static JsonSerializerOptions Options { get; } = new()
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = null,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public static CanonicalObservation Deserialize(string json)
    {
        CanonicalObservation observation = JsonSerializer.Deserialize<CanonicalObservation>(json, Options)
            ?? throw new JsonException("The canonical observation was null.");
        _ = observation.Stage;
        return observation;
    }

    public static CanonicalObservation EncodeRuntime(object runtimeObservation) =>
        Deserialize(JsonSerializer.Serialize(runtimeObservation));

    public static string Serialize(CanonicalObservation observation) => JsonSerializer.Serialize(observation, Options);
}

internal sealed class CanonicalRunCardJsonConverter : JsonConverter<CanonicalRunCard>
{
    public override CanonicalRunCard Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.String) return new(reader.GetString(), null);
        CanonicalCardReference reference = JsonSerializer.Deserialize<CanonicalCardReference>(ref reader, options)
            ?? throw new JsonException("A run card reference was null.");
        return new(null, reference);
    }

    public override void Write(Utf8JsonWriter writer, CanonicalRunCard value, JsonSerializerOptions options)
    {
        if (value.ModelId is not null) writer.WriteStringValue(value.ModelId);
        else JsonSerializer.Serialize(writer, value.Reference, options);
    }
}

internal sealed class CanonicalChoiceOptionJsonConverter : JsonConverter<CanonicalChoiceOption>
{
    public override CanonicalChoiceOption Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        using JsonDocument document = JsonDocument.ParseValue(ref reader);
        Type target = document.RootElement.TryGetProperty("cards", out _)
            ? typeof(CanonicalBundleChoiceOption)
            : typeof(CanonicalModelChoiceOption);
        return (CanonicalChoiceOption)(JsonSerializer.Deserialize(document.RootElement.GetRawText(), target, options)
            ?? throw new JsonException("A choice option was null."));
    }

    public override void Write(Utf8JsonWriter writer, CanonicalChoiceOption value, JsonSerializerOptions options) =>
        JsonSerializer.Serialize(writer, value, value.GetType(), options);
}

internal sealed class CanonicalNativeValueJsonConverter : JsonConverter<CanonicalNativeValue>
{
    public override CanonicalNativeValue Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        using JsonDocument document = JsonDocument.ParseValue(ref reader);
        JsonElement value = document.RootElement;
        bool valid = value.ValueKind is JsonValueKind.String or JsonValueKind.True or JsonValueKind.False
            || value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out _)
            || value.ValueKind == JsonValueKind.Array && value.EnumerateArray().All(item =>
                item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out _));
        if (!valid)
        {
            throw new JsonException("A native-state value must be an integer, boolean, string, or integer array.");
        }
        return new CanonicalNativeValue(value.Clone());
    }

    public override void Write(Utf8JsonWriter writer, CanonicalNativeValue value, JsonSerializerOptions options) =>
        value.Value.WriteTo(writer);
}
