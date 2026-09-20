using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.TraceExporter;

/// <summary>The trace runtime's adapter into the shared canonical observation records.</summary>
public static class TraceCanonicalObservationEncoder
{
    public static CanonicalObservation Encode(object runtimeObservation) =>
        CanonicalObservationJson.EncodeRuntime(runtimeObservation);
}
