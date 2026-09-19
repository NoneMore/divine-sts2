using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Sts2.NativeSim.Core.RunSession;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core;

/// <summary>
/// Caller-facing owner of branch history, state identity, RPC results and transition timing. Run
/// decisions themselves are reached only through <see cref="IActiveRunSession"/>.
/// </summary>
public sealed class NativeRunCoordinator
{
    private static readonly int BranchCapacity = int.TryParse(
        System.Environment.GetEnvironmentVariable("STS2_BRANCH_CAPACITY"),
        out int capacity) && capacity > 0 ? capacity : 8192;

    private readonly IRunSessionCompatibilityAdapter _adapter;
    private readonly Dictionary<string, CoordinatorBranch> _branches = new(StringComparer.Ordinal);
    private readonly LinkedList<string> _branchOrder = [];
    private readonly List<string> _history = [];
    private readonly SemaphoreSlim _serial = new(1, 1);
    private CompatibilityActiveRunSession? _session;
    private ResetRequest? _reset;
    private string? _currentBranchHandle;

    internal NativeRunCoordinator(IRunSessionCompatibilityAdapter adapter) => _adapter = adapter;

    public NativeRunCoordinator(PersistentNativeCombatEnvironment environment)
        : this(new LegacyRunSessionAdapter(environment)) { }

    public EnvironmentResult RunReset(ResetRequest request)
    {
        return Reset(request with { ResetMode = ResetModes.Run }, _adapter.Reset, "run_reset");
    }

    public EnvironmentResult MapReset(ResetRequest request)
    {
        return Reset(request with { ResetMode = ResetModes.Combat }, _adapter.ResetMap, "map_reset");
    }

    private EnvironmentResult Reset(
        ResetRequest request,
        Func<ResetRequest, CompatibilityCapture> reset,
        string transitionKind)
    {
        _serial.Wait();
        try
        {
            CompatibilityCapture initial = reset(request);
            _session = new(_adapter, initial);
            _reset = request;
            _branches.Clear();
            _branchOrder.Clear();
            _history.Clear();
            _currentBranchHandle = null;
            return Project(initial.Frame, new { kind = transitionKind, replayed_actions = 0 });
        }
        finally
        {
            _serial.Release();
        }
    }

    public EnvironmentResult Observe()
    {
        _serial.Wait();
        try
        {
            return Project(Session.Current, transition: null);
        }
        finally
        {
            _serial.Release();
        }
    }

    public IReadOnlyList<LegalAction> LegalActions()
    {
        _serial.Wait();
        try
        {
            return Session.Current.LegalActions;
        }
        finally
        {
            _serial.Release();
        }
    }

    public async Task<EnvironmentResult> StepAsync(string actionId)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            DecisionFrame before = Session.Current;
            LegalAction? action = before.LegalActions.SingleOrDefault(candidate =>
                StringComparer.Ordinal.Equals(candidate.ActionId, actionId));
            // The session repeats this check while holding its serial gate. This lookup only preserves
            // the action kind in the coordinator-owned transition envelope.
            if (action is null)
                throw new ProtocolException(
                    "invalid_action",
                    $"Action '{actionId}' is not legal in state {ComputeStateHash(before)}.");

            Stopwatch timer = Stopwatch.StartNew();
            await Session.ApplyAsync(actionId).ConfigureAwait(false);
            timer.Stop();
            _history.Add(actionId);
            return Project(
                Session.Current,
                new
                {
                    kind = action.Kind,
                    action_id = actionId,
                    elapsed_ms = timer.Elapsed.TotalMilliseconds,
                    history_length = _history.Count
                },
                actionId);
        }
        finally
        {
            _serial.Release();
        }
    }

    public string Fork()
    {
        _serial.Wait();
        try
        {
            _ = Project(Session.Current, transition: null);
            return _currentBranchHandle!;
        }
        finally
        {
            _serial.Release();
        }
    }

    public async Task<EnvironmentResult> RestoreAsync(string stateHandle)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            if (!_branches.TryGetValue(stateHandle, out CoordinatorBranch? branch))
                throw new ProtocolException("unknown_state_handle", stateHandle);

            Stopwatch timer = Stopwatch.StartNew();
            CompatibilityCapture restored = await Session.RestoreAsync(branch.Checkpoint).ConfigureAwait(false);
            string actualHash = ComputeStateHash(restored.Frame);
            if (!StringComparer.Ordinal.Equals(branch.ExpectedHash, actualHash))
                throw new ProtocolException(
                    "replay_divergence",
                    $"Expected {branch.ExpectedHash}, obtained {actualHash}.",
                    new { history_length = branch.History.Count });

            _history.Clear();
            _history.AddRange(branch.History);
            _currentBranchHandle = stateHandle;
            timer.Stop();
            CompatibilityRestore metadata = restored.Restore
                ?? new("restore", branch.History.Count);
            Dictionary<string, object?> transition = new(StringComparer.Ordinal)
            {
                ["kind"] = metadata.Kind,
                ["replayed_actions"] = metadata.ReplayedActions,
                ["elapsed_ms"] = metadata.ResidentPrefixHit is true
                    ? 0.0
                    : timer.Elapsed.TotalMilliseconds
            };
            if (metadata.ResidentPrefixHit is { } resident)
                transition["resident_prefix_hit"] = resident;
            return Project(restored.Frame, transition);
        }
        finally
        {
            _serial.Release();
        }
    }

    private CompatibilityActiveRunSession Session =>
        _session ?? throw new ProtocolException("invalid_state", "The run session has not been reset.");

    private EnvironmentResult Project(DecisionFrame frame, object? transition, string? actionId = null)
    {
        string stateHash = ComputeStateHash(frame);
        string stateHandle = GetOrAddCurrentBranch(frame, stateHash, actionId);
        return new(
            frame.Observation,
            stateHash,
            frame.LegalActions,
            frame.Terminated,
            frame.Victory,
            stateHandle,
            transition,
            frame.ScoringFeatures);
    }

    private string GetOrAddCurrentBranch(DecisionFrame frame, string stateHash, string? actionId)
    {
        if (actionId is null
            && _currentBranchHandle is not null
            && _branches.TryGetValue(_currentBranchHandle, out CoordinatorBranch? resident)
            && StringComparer.Ordinal.Equals(resident.ExpectedHash, stateHash))
        {
            _branches[_currentBranchHandle] = resident with
            {
                Checkpoint = _adapter.CaptureCheckpoint()
            };
            Touch(_currentBranchHandle);
            return _currentBranchHandle;
        }

        ResetRequest reset = _reset
            ?? throw new ProtocolException("invalid_state", "The run session has no reset recipe.");
        byte[] payload = JsonSerializer.SerializeToUtf8Bytes(new
        {
            parent = _currentBranchHandle,
            action_id = actionId,
            expected_hash = stateHash,
            reset,
            kernel = frame.KernelProjection
        });
        string handle = "s:" + Convert.ToHexString(SHA256.HashData(payload));
        object checkpoint = _adapter.CaptureCheckpoint();
        if (!_branches.ContainsKey(handle))
        {
            _branches.Add(handle, new(stateHash, _history.ToArray(), checkpoint));
            _branchOrder.AddLast(handle);
            while (_branches.Count > BranchCapacity && _branchOrder.First is { } oldest)
            {
                _branchOrder.RemoveFirst();
                _branches.Remove(oldest.Value);
            }
        }
        else
        {
            _branches[handle] = _branches[handle] with { Checkpoint = checkpoint };
            Touch(handle);
        }
        _currentBranchHandle = handle;
        return handle;
    }

    private void Touch(string handle)
    {
        _branchOrder.Remove(handle);
        _branchOrder.AddLast(handle);
    }

    internal static string ComputeStateHash(DecisionFrame frame)
    {
        byte[] payload = JsonSerializer.SerializeToUtf8Bytes(new
        {
            hash_schema_version = 4,
            observation = frame.Observation,
            kernel = frame.KernelProjection
        });
        return Convert.ToHexString(SHA256.HashData(payload));
    }

    private sealed record CoordinatorBranch(
        string ExpectedHash,
        IReadOnlyList<string> History,
        object Checkpoint);
}
