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
    private CompatibilityActiveRunSession? _session;
    private ResetRequest? _reset;
    private string? _currentBranchHandle;

    internal NativeRunCoordinator(IRunSessionCompatibilityAdapter adapter) => _adapter = adapter;

    public NativeRunCoordinator(PersistentNativeCombatEnvironment environment)
        : this(new LegacyRunSessionAdapter(environment)) { }

    public EnvironmentResult RunReset(ResetRequest request)
    {
        CompatibilityCapture initial = _adapter.Reset(request);
        _session = new(_adapter, initial);
        _reset = request with { ResetMode = ResetModes.Run };
        _history.Clear();
        _currentBranchHandle = null;
        return Project(initial.Frame, initial.Transition);
    }

    public EnvironmentResult Observe() => Project(Session.Current, transition: null);

    public IReadOnlyList<LegalAction> LegalActions() => Session.Current.LegalActions;

    public async Task<EnvironmentResult> StepAsync(string actionId)
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

    public string Fork()
    {
        _ = Project(Session.Current, transition: null);
        return _currentBranchHandle!;
    }

    public async Task<EnvironmentResult> RestoreAsync(string stateHandle)
    {
        if (!_branches.TryGetValue(stateHandle, out CoordinatorBranch? branch))
            throw new ProtocolException("unknown_state_handle", stateHandle);

        Stopwatch timer = Stopwatch.StartNew();
        CompatibilityCapture restored = await Session.RestoreAsync(stateHandle).ConfigureAwait(false);
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
        object transition = restored.Transition ?? new
        {
            kind = "restore",
            replayed_actions = branch.History.Count,
            elapsed_ms = timer.Elapsed.TotalMilliseconds
        };
        return Project(restored.Frame, transition);
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
        if (!_branches.ContainsKey(handle))
        {
            _branches.Add(handle, new(stateHash, _history.ToArray()));
            _branchOrder.AddLast(handle);
            _adapter.Retain(handle);
            while (_branches.Count > BranchCapacity && _branchOrder.First is { } oldest)
            {
                _branchOrder.RemoveFirst();
                _branches.Remove(oldest.Value);
            }
        }
        else
        {
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

    private sealed record CoordinatorBranch(string ExpectedHash, IReadOnlyList<string> History);
}
