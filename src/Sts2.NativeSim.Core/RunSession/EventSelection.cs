using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.RunSession;

internal sealed record EventSelection(int OptionIndex);

internal sealed record EventDecisionMetadata(string? EventId)
{
    public static EventDecisionMetadata? ForActions(
        EventDecisionMetadata? activeEvent,
        IReadOnlyList<LegalAction> actions) =>
        activeEvent is not null
        && (actions.Count == 0 || actions.All(action => action.Kind is "choose_event" or "leave_event"))
            ? activeEvent
            : null;
}
