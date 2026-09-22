namespace Sts2.NativeSim.Protocol;

public enum ProgressionReadinessState
{
    Initializing,
    Ready,
    Failed,
}

public sealed record ProgressionReadinessSnapshot(
    ProgressionReadinessState State,
    string Status,
    string? ProfileFingerprint,
    string? FailureMessage);

public sealed class ProgressionReadiness
{
    private readonly object _sync = new();
    private ProgressionReadinessState _state = ProgressionReadinessState.Initializing;
    private string? _profileFingerprint;
    private Exception? _failure;

    public string Status
    {
        get { lock (_sync) return WireStatus(_state); }
    }

    public string? ProfileFingerprint
    {
        get { lock (_sync) return _profileFingerprint; }
    }

    public string? FailureMessage
    {
        get { lock (_sync) return _failure?.Message; }
    }

    public void Complete(string profileFingerprint)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(profileFingerprint);
        lock (_sync)
        {
            if (_state != ProgressionReadinessState.Initializing)
                throw new InvalidOperationException($"Progress readiness is already {WireStatus(_state)}.");
            _profileFingerprint = profileFingerprint;
            _state = ProgressionReadinessState.Ready;
        }
    }

    public void Fail(Exception failure)
    {
        ArgumentNullException.ThrowIfNull(failure);
        lock (_sync)
        {
            if (_state != ProgressionReadinessState.Initializing) return;
            _failure = failure;
            _state = ProgressionReadinessState.Failed;
        }
    }

    public void EnsureReadyForStart()
    {
        lock (_sync)
        {
            if (_state == ProgressionReadinessState.Ready) return;
            if (_failure is not null)
                throw new InvalidOperationException($"Progression-complete baseline initialization failed: {_failure.Message}", _failure);
            throw new InvalidOperationException("Progression-complete baseline is still initializing; start_run is not available yet.");
        }
    }

    public ProgressionReadinessSnapshot Snapshot()
    {
        lock (_sync)
        {
            return new ProgressionReadinessSnapshot(
                _state, WireStatus(_state), _profileFingerprint, _failure?.Message);
        }
    }

    private static string WireStatus(ProgressionReadinessState state) => state switch
    {
        ProgressionReadinessState.Initializing => "initializing",
        ProgressionReadinessState.Ready => "ready",
        ProgressionReadinessState.Failed => "failed",
        _ => throw new ArgumentOutOfRangeException(nameof(state), state, null),
    };
}
