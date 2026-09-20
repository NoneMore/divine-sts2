using System.Text.Json;
using System.Text.Json.Serialization;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// The one JSON shape the bridge writes. Dropping nulls is not cosmetic: the simulator's worker and
/// the trace exporter both omit a null member, so in every other projection a field that can be
/// null is <em>absent</em>. Writing <c>null</c> instead would make a field-by-field comparison
/// report a difference for a state the two encoders agree on.
/// </summary>
public static class BridgeJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = false,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new FullAppBridgeLegalActionConverter() },
    };
}
