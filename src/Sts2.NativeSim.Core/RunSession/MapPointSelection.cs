using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.RunSession;

/// <summary>
/// The semantic identity needed to enter a map point. Reflected map objects remain behind the
/// native adapter and never cross into an active run state.
/// </summary>
internal sealed record MapPointSelection(int Col, int Row, string PointType)
{
    public static MapPointSelection FromAction(LegalAction action)
    {
        if (action.Kind != "choose_map")
            throw new ProtocolException(
                "protocol_desync",
                $"A map projection advertised non-map action '{action.Kind}'.");
        return new(
            Convert.ToInt32(action.Parameters["col"]),
            Convert.ToInt32(action.Parameters["row"]),
            Convert.ToString(action.Parameters["point_type"])!);
    }
}
