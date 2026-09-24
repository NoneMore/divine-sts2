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

    private readonly INativeRunAdapter _adapter;
    private readonly Dictionary<string, CoordinatorBranch> _branches = new(StringComparer.Ordinal);
    private readonly LinkedList<string> _branchOrder = [];
    private readonly List<string> _history = [];
    private readonly SemaphoreSlim _serial = new(1, 1);
    private ActiveRunSession? _session;
    private ResetRequest? _reset;
    private string? _currentBranchHandle;

    internal NativeRunCoordinator(INativeRunAdapter adapter) => _adapter = adapter;

    public NativeRunCoordinator(PersistentNativeCombatEnvironment environment)
        : this(new NativeRunAdapter(environment)) { }

    public EnvironmentResult CombatReset(ResetRequest request)
    {
        return ResetDecision(request, _adapter.ResetCombat, ResetModes.Combat, "reset");
    }

    public EnvironmentResult RunReset(ResetRequest request)
    {
        return ResetDecision(request, _adapter.ResetRun, ResetModes.Run, "run_reset");
    }

    public EnvironmentResult MapReset(ResetRequest request)
    {
        return ResetDecision(request, _adapter.ResetMap, ResetModes.Combat, "map_reset");
    }

    public EnvironmentResult RewardReset(ResetRequest request)
    {
        return ResetDecision(request, _adapter.ResetReward, ResetModes.Combat, "reward_reset");
    }

    public EnvironmentResult ItemRewardReset(ItemRewardResetRequest request)
    {
        _serial.Wait();
        try
        {
            NativeDecisionCapture initial = _adapter.ResetItemReward(request);
            InitializeSession(request.State, initial);
            return Project(initial.Frame, new
            {
                kind = "item_reward_reset",
                reward_kind = request.RewardKind,
                model_id = request.ModelId,
                replayed_actions = 0
            });
        }
        finally
        {
            _serial.Release();
        }
    }

    public async Task<EnvironmentResult> CustomRewardResetAsync(CustomRewardResetRequest request)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            NativeDecisionCapture initial = await _adapter.ResetCustomRewardAsync(request).ConfigureAwait(false);
            InitializeSession(request.State, initial);
            return Project(initial.Frame, new
            {
                kind = "custom_reward_reset",
                linked = request.Linked,
                replayed_actions = 0
            });
        }
        finally
        {
            _serial.Release();
        }
    }

    public EnvironmentResult RestReset(ResetRequest request)
    {
        return ResetDecision(request, _adapter.ResetRest, ResetModes.Combat, "rest_reset");
    }

    public async Task<EnvironmentResult> EventResetAsync(EventResetRequest request)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            NativeDecisionCapture initial = await _adapter.ResetEventAsync(request).ConfigureAwait(false);
            InitializeSession(request.State, initial);
            return Project(initial.Frame, new
            {
                kind = "event_reset",
                event_id = request.EventId,
                replayed_actions = 0
            });
        }
        finally
        {
            _serial.Release();
        }
    }

    private EnvironmentResult ResetDecision(
        ResetRequest request,
        Func<ResetRequest, NativeDecisionCapture> reset,
        string resetMode,
        string transitionKind)
    {
        _serial.Wait();
        try
        {
            NativeDecisionCapture initial = reset(request);
            InitializeSession(request with { ResetMode = resetMode }, initial);
            return Project(initial.Frame, new { kind = transitionKind, replayed_actions = 0 });
        }
        finally
        {
            _serial.Release();
        }
    }

    private void InitializeSession(ResetRequest request, NativeDecisionCapture initial)
    {
        _session = new(_adapter, initial);
        _reset = request with { ResetMode = request.ResetMode ?? ResetModes.Combat };
        _branches.Clear();
        _branchOrder.Clear();
        _history.Clear();
        _currentBranchHandle = null;
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

    #if DEBUG
    // RESEARCH PROTOTYPE: keep the native decision loop but omit coordinator projections for
    // intermediate actions. The adapter still captures the full legacy observation and hash.
    private async Task<DecisionFrame> StepFrameForScenarioProbeAsync(string actionId)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            await Session.ApplyAsync(actionId).ConfigureAwait(false);
            return Session.Current;
        }
        finally
        {
            _serial.Release();
        }
    }

    // RESEARCH PROTOTYPE: one request per seed. This deliberately returns only the final
    // combat projection, allowing an exact observation/hash comparison with generate_rows.
    public async Task<object> GenerateFirstCombatScenariosProbeAsync(ResetRequest request, bool light)
    {
        Stopwatch timer = Stopwatch.StartNew();
        Dictionary<string, double> phaseMs = new(StringComparer.Ordinal);
        void Add(string phase, long started)
        {
            double elapsed = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
            phaseMs[phase] = phaseMs.GetValueOrDefault(phase) + elapsed;
        }
        long tick = Stopwatch.GetTimestamp();
        EnvironmentResult reset = RunReset(request);
        Add("reset", tick);
        LegalAction ancient = reset.LegalActions.First(action =>
            action.Kind == "choose_map" && Convert.ToString(action.Parameters["point_type"]) == "Ancient");
        tick = Stopwatch.GetTimestamp();
        EnvironmentResult offered = await StepAsync(ancient.ActionId).ConfigureAwait(false);
        Add("enter_ancient", tick);
        string checkpoint = offered.StateHandle;
        LegalAction[] choices = offered.LegalActions.Where(action => action.Kind == "choose_event").ToArray();
        List<object> rows = [];
        for (int i = 0; i < choices.Length; i++)
        {
            if (i > 0)
            {
                tick = Stopwatch.GetTimestamp();
                await RestoreAsync(checkpoint).ConfigureAwait(false);
                Add("restore", tick);
            }
            tick = Stopwatch.GetTimestamp();
            DecisionFrame frame = await ProbeStepAsync(choices[i].ActionId, light).ConfigureAwait(false);
            Add("choose_ancient", tick);
            List<object> nested = [];
            for (int step = 0; step < 64 && !frame.LegalActions.Any(action => action.Kind == "leave_event"); step++)
            {
                LegalAction pick = frame.LegalActions.First();
                nested.Add(new { observation = frame.Observation, action = pick });
                tick = Stopwatch.GetTimestamp();
                frame = await ProbeStepAsync(pick.ActionId, light).ConfigureAwait(false);
                Add("nested", tick);
            }
            if (!frame.LegalActions.Any(action => action.Kind == "leave_event"))
                throw new ProtocolException("invalid_state", "Ancient choice did not finish within 64 nested steps.");
            tick = Stopwatch.GetTimestamp();
            frame = await ProbeStepAsync("leave_event", light).ConfigureAwait(false);
            Add("leave_ancient", tick);
            LegalAction node = frame.LegalActions.First(action => action.Kind == "choose_map");
            tick = Stopwatch.GetTimestamp();
            frame = await ProbeStepAsync(node.ActionId, light).ConfigureAwait(false);
            Add("enter_combat", tick);
            rows.Add(new
            {
                choice = choices[i],
                nested,
                node,
                observation = frame.Observation,
                state_hash = ComputeStateHash(frame)
            });
        }
        timer.Stop();
        return new { elapsed_ms = timer.Elapsed.TotalMilliseconds, phase_ms = phaseMs,
            reset_observation = reset.Observation,
            offered_observation = offered.Observation, rows };
    }

    private async Task<DecisionFrame> ProbeStepAsync(string actionId, bool light)
    {
        if (light) return await StepFrameForScenarioProbeAsync(actionId).ConfigureAwait(false);
        await StepAsync(actionId).ConfigureAwait(false);
        return Session.Current;
    }
    #endif

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
            NativeDecisionCapture restored = await Session.RestoreAsync(branch.Checkpoint).ConfigureAwait(false);
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
            NativeRestore metadata = restored.Restore
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
            // Where the restore spent its time, timed by the environment that did it. Only a
            // profiling worker reports one, and it is reported to this caller rather than written
            // anywhere a corpus owns (ADR-0008).
            if (metadata.Profile is { } profile)
                transition["profile"] = profile;
            return Project(restored.Frame, transition);
        }
        finally
        {
            _serial.Release();
        }
    }

    private ActiveRunSession Session =>
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
