namespace Sts2.NativeSim.Core.RunSession;

/// <summary>The semantic result of resolving one Card-select prompt.</summary>
internal sealed record CardSelection(string ActionId, IReadOnlyList<string> OptionIds);

/// <summary>The semantic result of taking or skipping one entry in a reward prompt.</summary>
internal sealed record RewardSelection(
    string ActionId,
    int? RewardIndex,
    int? ChildIndex,
    int? OptionIndex);
