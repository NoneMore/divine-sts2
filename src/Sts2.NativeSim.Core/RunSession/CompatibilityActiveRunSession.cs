using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.RunSession;

/// <summary>
/// Temporary port implemented by the legacy room/combat state machine. It is deliberately private
/// to the RunSession module so no new caller can depend on capture or execution by room kind.
/// </summary>
internal interface IRunSessionCompatibilityAdapter
{
    CompatibilityCapture Reset(ResetRequest request);
    Task<CompatibilityCapture> ApplyAsync(string actionId);
    string Fork();
    Task<CompatibilityCapture> RestoreAsync(string stateHandle);
    void Retain(string stateHandle);
}

internal sealed record CompatibilityCapture(DecisionFrame Frame, object? Transition = null);

/// <summary>
/// Serial compatibility implementation of the active-run interface. Its action table is built
/// from the same frame it exposes, so validation always precedes native mutation.
/// </summary>
internal sealed class CompatibilityActiveRunSession : IActiveRunSession
{
    private const string PoisonedMessage =
        "Worker state is corrupted and must be reconstructed. Discard and replace this worker.";

    private readonly IRunSessionCompatibilityAdapter _adapter;
    private readonly SemaphoreSlim _serial = new(1, 1);
    private DecisionFrame _current;
    private IReadOnlyDictionary<string, LegalAction> _executors;
    private bool _poisoned;

    public CompatibilityActiveRunSession(
        IRunSessionCompatibilityAdapter adapter,
        CompatibilityCapture initial)
    {
        _adapter = adapter;
        _current = initial.Frame;
        _executors = BuildExecutorTable(_current);
    }

    public DecisionFrame Current
    {
        get
        {
            _serial.Wait();
            try
            {
                ThrowIfPoisoned();
                return _current;
            }
            finally
            {
                _serial.Release();
            }
        }
    }

    public async Task ApplyAsync(string actionId)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            ThrowIfPoisoned();
            if (!_executors.ContainsKey(actionId))
                throw new ProtocolException(
                    "invalid_action",
                    $"Action '{actionId}' is not legal in the current decision frame.");

            string checkpoint = _adapter.Fork();
            try
            {
                CompatibilityCapture next = await _adapter.ApplyAsync(actionId).ConfigureAwait(false);
                IReadOnlyDictionary<string, LegalAction> nextExecutors = BuildExecutorTable(next.Frame);
                _current = next.Frame;
                _executors = nextExecutors;
            }
            catch
            {
                try
                {
                    CompatibilityCapture restored = await _adapter.RestoreAsync(checkpoint).ConfigureAwait(false);
                    _current = restored.Frame;
                    _executors = BuildExecutorTable(restored.Frame);
                }
                catch
                {
                    _poisoned = true;
                    throw Poisoned();
                }
                throw;
            }
        }
        finally
        {
            _serial.Release();
        }
    }

    internal async Task<CompatibilityCapture> RestoreAsync(string stateHandle)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            ThrowIfPoisoned();
            try
            {
                CompatibilityCapture restored = await _adapter.RestoreAsync(stateHandle).ConfigureAwait(false);
                _executors = BuildExecutorTable(restored.Frame);
                _current = restored.Frame;
                return restored;
            }
            catch
            {
                _poisoned = true;
                throw;
            }
        }
        finally
        {
            _serial.Release();
        }
    }

    private static IReadOnlyDictionary<string, LegalAction> BuildExecutorTable(DecisionFrame frame)
    {
        Dictionary<string, LegalAction> executors = new(StringComparer.Ordinal);
        foreach (LegalAction action in frame.LegalActions)
        {
            if (!executors.TryAdd(action.ActionId, action))
                throw new ProtocolException(
                    "action_id_collision",
                    $"Action id '{action.ActionId}' is advertised more than once in the current decision frame.");
        }
        return executors;
    }

    private void ThrowIfPoisoned()
    {
        if (_poisoned) throw Poisoned();
    }

    private static ProtocolException Poisoned() => new("worker_poisoned", PoisonedMessage);
}
