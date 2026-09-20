using System.Text.Json;
using System.Text.Json.Serialization;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.FullAppBridge;

internal sealed class FullAppBridgeLegalActionConverter : JsonConverter<LegalAction>
{
    public override LegalAction Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) =>
        throw new NotSupportedException("FullAppBridge only writes legal actions.");

    public override void Write(Utf8JsonWriter writer, LegalAction value, JsonSerializerOptions options)
    {
        writer.WriteStartObject();
        writer.WriteString("action_id", value.ActionId);
        writer.WriteString("action_type", value.Kind);
        writer.WriteString("description", value.Description ?? "");
        if (value.Parameters.Count > 0)
        {
            writer.WritePropertyName("metadata");
            JsonSerializer.Serialize(writer, value.Parameters, options);
        }
        writer.WriteEndObject();
    }
}
