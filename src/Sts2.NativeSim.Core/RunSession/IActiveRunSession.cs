namespace Sts2.NativeSim.Core.RunSession;

/// <summary>The complete interface of an active run: inspect one decision, or apply one action.</summary>
internal interface IActiveRunSession
{
    DecisionFrame Current { get; }
    Task ApplyAsync(string actionId);
}

