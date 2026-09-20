using System.Text.Json;
using System.Text.Json.Serialization;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Host;

internal sealed class HeadlessLegalActionConverter : JsonConverter<LegalAction>
{
    public override LegalAction Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) =>
        throw new NotSupportedException("The headless host only writes legal actions.");

    public override void Write(Utf8JsonWriter writer, LegalAction value, JsonSerializerOptions options)
    {
        writer.WriteStartObject();
        writer.WriteString("action_id", value.ActionId);
        writer.WriteString("kind", value.Kind);
        writer.WritePropertyName("parameters");
        JsonSerializer.Serialize(writer, value.Parameters, options);
        writer.WriteEndObject();
    }
}
