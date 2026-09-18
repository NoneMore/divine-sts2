using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core;

/// <summary>
/// The semantic native seam used by the run coordinator. Implementations own native objects and
/// continuations; callers see only complete captures and action identifiers.
/// </summary>
internal interface INativeRunAdapter : IDisposable
{
    EnvironmentResult RunReset(ResetRequest request);
    EnvironmentResult Capture();
    Task<EnvironmentResult> ApplyAsync(string actionId);
    string Fork();
    Task<EnvironmentResult> RestoreAsync(string stateHandle);
}

/// <summary>
/// The caller-facing run seam. It rejects an ambiguous or unadvertised action before the native
/// adapter can mutate state. Room-state dispatch remains in the existing reflection implementation
/// until the active-session work replaces it.
/// </summary>
internal sealed class NativeRunCoordinator(INativeRunAdapter adapter) : IDisposable
{
    private EnvironmentResult? _current;

    public EnvironmentResult RunReset(ResetRequest request) =>
        Remember(adapter.RunReset(request));

    public EnvironmentResult Observe() => Remember(adapter.Capture());

    public IReadOnlyList<LegalAction> LegalActions() => Current().LegalActions;

    public async Task<EnvironmentResult> StepAsync(string actionId)
    {
        EnvironmentResult before = Current();
        LegalAction? action = before.LegalActions.SingleOrDefault(candidate =>
            StringComparer.Ordinal.Equals(candidate.ActionId, actionId));
        if (action is null)
            throw new ProtocolException(
                "invalid_action",
                $"Action '{actionId}' is not legal in state {before.StateHash}.");

        return Remember(await adapter.ApplyAsync(actionId));
    }

    public string Fork()
    {
        _ = Current();
        return adapter.Fork();
    }

    public async Task<EnvironmentResult> RestoreAsync(string stateHandle) =>
        Remember(await adapter.RestoreAsync(stateHandle));

    public void Dispose() => adapter.Dispose();

    private EnvironmentResult Current() => _current ?? Observe();

    private EnvironmentResult Remember(EnvironmentResult result)
    {
        string? collision = result.LegalActions
            .GroupBy(action => action.ActionId, StringComparer.Ordinal)
            .FirstOrDefault(group => group.Count() > 1)
            ?.Key;
        if (collision is not null)
            throw new ProtocolException(
                "action_id_collision",
                $"Action id '{collision}' is advertised more than once in state {result.StateHash}.");

        _current = result;
        return result;
    }
}

/// <summary>
/// Production adapter for the shipped-game reflection implementation.
/// </summary>
internal sealed class ReflectionNativeRunAdapter : INativeRunAdapter
{
    private readonly PersistentNativeCombatEnvironment _environment;

    public ReflectionNativeRunAdapter(string assemblyPath, string pckPath)
    {
        _environment = new(assemblyPath, pckPath);
    }

    public EnvironmentResult RunReset(ResetRequest request) => _environment.RunReset(request);
    public EnvironmentResult Capture() => _environment.Observe();
    public Task<EnvironmentResult> ApplyAsync(string actionId) => _environment.StepAsync(actionId);
    public string Fork() => _environment.Fork();
    public Task<EnvironmentResult> RestoreAsync(string stateHandle) => _environment.RestoreAsync(stateHandle);
    public void Dispose() => _environment.Dispose();
}
