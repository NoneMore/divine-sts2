namespace Sts2.NativeSim.Core.RunSession;

/// <summary>
/// An in-memory identity for the exact native parent suspended by a prompt. Its marker is never
/// projected, hashed, checkpointed, or serialized; replay creates a fresh token.
/// </summary>
internal sealed class PromptResumeToken(object marker)
{
    internal object Marker { get; } = marker;
}

/// <summary>The semantic result of resolving one Card-select prompt.</summary>
internal sealed record CardSelection(string ActionId, IReadOnlyList<string> OptionIds);

/// <summary>The semantic result of resolving a bundle or relic option pick.</summary>
internal sealed record OptionSelection(string ActionId, IReadOnlyList<string> OptionIds);

/// <summary>The semantic result of taking or skipping one entry in a reward prompt.</summary>
internal sealed record RewardSelection(
    string ActionId,
    int? RewardIndex,
    int? ChildIndex,
    int? OptionIndex);
