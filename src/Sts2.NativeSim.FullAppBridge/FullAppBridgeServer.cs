using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Diagnostics;
using Godot;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Runs;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.FullAppBridge;

public static class FullAppBridgeServer
{
    private enum WorkerState { Launching, Idle, Running, Ending, Poisoned, Closed }
    private sealed class ProcessModeMismatchException(string message) : Exception(message);

    public const string UnlockPolicy = "all";
    private static readonly ProgressionReadiness ProgressReadiness = new();
    private static TcpListener? _listener;
    private static TcpClient? _client;
    private static NetworkStream? _stream;
    private static StreamWriter? _writer;
    private static StreamReader? _reader;
    private static TaskCompletionSource<string>? _pendingActionTcs;
    private static TaskCompletionSource<bool>? _initialBoundaryTcs;
    private static Task? _driverTask;
    private static Task<RunState>? _shippedStartTask;
    private static WorkerState _workerState = WorkerState.Launching;
    private static long _generation;
    private static long _boundaryGeneration;
    private static string? _boundaryPhase;
    private static int _staleRefusals;
    private static int _lifecycleRequestBusy;
    private static int _runsStarted;

    /// <summary>
    /// Serialises the decision boundaries, so one decision is live at a time and the caller's action
    /// always belongs to the decision it was shown.
    ///
    /// A room's loop and a prompt an effect inside it opened reach a boundary concurrently: the loop
    /// re-reports the room about 50 ms after the choice that opened the prompt. Only one boundary can
    /// hold the pending action at a time, and a second one that published over the first would take
    /// the caller's answer away from the decision it saw — which for a prompt means the game stays
    /// blocked on it. Waiting here gives the first arrival the caller, and the second publishes its
    /// own observation once that answer has been consumed. Which of the two arrives first is a matter
    /// of timing; what this preserves is that whoever published is who gets answered, so a caller
    /// never sends a card action to a room. See <see cref="WaitForCoordinatorActionAsync"/>.
    /// </summary>
    private static readonly SemaphoreSlim BoundaryGate = new(1, 1);

    private static readonly object SyncLock = new();

    public static int BoundPort { get; private set; }
    public static ObservationDto? CurrentObservation { get; set; }
    public static List<LegalAction> CurrentLegalActions { get; set; } = new();
    public static List<string> ActionHistory { get; } = new();
    public static List<string> StateHashHistory { get; } = new();

    public static string RequestedSeed { get; private set; } = "A1B2C3D4E5";
    public static string RequestedCharacter { get; private set; } = "IRONCLAD";
    public static int RequestedAscension { get; private set; } = 0;
    public static bool IsRunStarted { get; private set; }
    internal static bool IsWarmRun => FullAppBridgeMod.ReuseMode && Volatile.Read(ref _runsStarted) > 1;

    internal static void FailDriverStart(Exception error)
    {
        Poison();
        _initialBoundaryTcs?.TrySetException(error);
    }

    public static void MarkProgressReady(string fingerprint)
    {
        ProgressReadiness.Complete(fingerprint);
        lock (SyncLock)
        {
            if (_workerState == WorkerState.Launching) _workerState = WorkerState.Idle;
        }
    }

    public static void MarkProgressFailed(Exception failure)
    {
        ProgressReadiness.Fail(failure);
        lock (SyncLock) _workerState = WorkerState.Poisoned;
    }

    public static void TrackDriver(Task task)
    {
        lock (SyncLock) _driverTask = task;
        _ = task.ContinueWith(completed =>
        {
            lock (SyncLock)
            {
                if (_workerState != WorkerState.Running) return;
                _workerState = WorkerState.Poisoned;
                string reason = completed.Exception?.GetBaseException().Message
                    ?? (completed.IsCanceled ? "Shipped driver was cancelled unexpectedly."
                        : "Shipped driver exited before end_run.");
                _initialBoundaryTcs?.TrySetException(new InvalidOperationException(reason));
            }
        }, TaskScheduler.Default);
    }

    public static void TrackShippedStart(Task<RunState> task)
    {
        lock (SyncLock) _shippedStartTask = task;
        _ = task.ContinueWith(completed =>
        {
            if (!completed.IsFaulted && !completed.IsCanceled) return;
            lock (SyncLock)
            {
                if (_workerState != WorkerState.Running) return;
                _initialBoundaryTcs?.TrySetException(completed.Exception?.GetBaseException()
                    ?? new OperationCanceledException("Shipped run start was cancelled."));
            }
        }, TaskScheduler.Default);
    }

    /// <summary>
    /// Whether a client is driving this worker. A prompt the game opens with nobody to answer it
    /// belongs to the shipped autoplay rather than to this seam, so the bridge defers it. The flag is
    /// the connection this server is holding rather than a socket's own stale `Connected` bit: the
    /// read loop clears it when the client goes away, so a client that dropped mid-run is not
    /// mistaken for one that is still there.
    /// </summary>
    public static bool HasClient
    {
        get
        {
            lock (SyncLock)
            {
                return _client is not null;
            }
        }
    }

    public static void Start(int preferredPort, string portFilePath)
    {
        string forceChar = System.Environment.GetEnvironmentVariable("STS2_FORCE_CHARACTER") ?? "";
        if (!string.IsNullOrWhiteSpace(forceChar))
        {
            RequestedCharacter = forceChar;
        }

        _listener = new TcpListener(IPAddress.Loopback, preferredPort);
        _listener.Start();
        BoundPort = ((IPEndPoint)_listener.LocalEndpoint).Port;

        if (!string.IsNullOrWhiteSpace(portFilePath))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(portFilePath)!);
            File.WriteAllText(portFilePath, BoundPort.ToString());
        }

        Task.Run(ListenLoopAsync);
    }

    private static async Task ListenLoopAsync()
    {
        while (_listener is not null)
        {
            try
            {
                TcpClient client = await _listener.AcceptTcpClientAsync();
                lock (SyncLock)
                {
                    if (_client is not null)
                    {
                        _workerState = WorkerState.Poisoned;
                        client.Dispose();
                        continue;
                    }
                    _client = client;
                    _stream = client.GetStream();
                    _writer = new StreamWriter(_stream, new UTF8Encoding(false)) { AutoFlush = true };
                    _reader = new StreamReader(_stream, new UTF8Encoding(false));
                }

                _ = HandleClientAsync(_reader!, _writer!);
            }
            catch
            {
                // listener closed or error
                break;
            }
        }
    }

    private static async Task HandleClientAsync(StreamReader reader, StreamWriter writer)
    {
        try
        {
            while (true)
            {
                string? line = await reader.ReadLineAsync();
                if (line is null) break;
                if (string.IsNullOrWhiteSpace(line)) continue;

                // Keep reading while start/step waits for the game. An overlapping lifecycle request
                // must be detected now, not silently queued until the first one has completed.
                _ = ProcessRequestAsync(line, writer);
            }
        }
        finally
        {
            // A client that has gone away is not a client: the run is no longer being driven, so the
            // flag the selector's fallback reads has to say so rather than keep a closed socket.
            lock (SyncLock)
            {
                if (ReferenceEquals(_reader, reader))
                {
                    if (_workerState is WorkerState.Running or WorkerState.Ending) _workerState = WorkerState.Poisoned;
                    _client?.Dispose();
                    _client = null;
                    _stream = null;
                    _writer = null;
                    _reader = null;
                }
            }
        }
    }

    private static readonly SemaphoreSlim WriteGate = new(1, 1);

    private static async Task ProcessRequestAsync(string line, StreamWriter writer)
    {
        RpcRequest? request = null;
        RpcResponse response;
        bool lifecycleRequest = false;
        bool acquiredLifecycle = false;
        try
        {
            request = FullAppBridgeWireAdapter.DecodeRequest(line);
            lifecycleRequest = request.Method.ToLowerInvariant() is "start_run" or "end_run" or "step";
            if (lifecycleRequest && Interlocked.CompareExchange(ref _lifecycleRequestBusy, 1, 0) != 0)
            {
                Poison();
                throw new InvalidOperationException("Overlapping lifecycle requests poisoned the worker.");
            }
            acquiredLifecycle = lifecycleRequest;
            object? result = await DispatchRequestAsync(request.Method, request.Parameters);
            response = new RpcResponse(request.Id, true, result);
        }
        catch (Exception ex)
        {
            if (lifecycleRequest && ex is not ProcessModeMismatchException) Poison();
            response = new RpcResponse(request?.Id ?? "0", false,
                Error: new ProtocolError("bridge_error", ex.Message));
        }
        finally
        {
            if (acquiredLifecycle) Interlocked.Exchange(ref _lifecycleRequestBusy, 0);
        }
        await WriteGate.WaitAsync();
        try { await writer.WriteLineAsync(FullAppBridgeWireAdapter.EncodeResponse(response)); }
        catch (IOException) { Poison(); }
        catch (ObjectDisposedException) { Poison(); }
        finally { WriteGate.Release(); }
    }

    private static void Poison()
    {
        lock (SyncLock)
        {
            if (_workerState != WorkerState.Closed) _workerState = WorkerState.Poisoned;
        }
    }

    private static string StateName(WorkerState state) => state.ToString().ToLowerInvariant();

    private static void RequireState(WorkerState required, string method)
    {
        lock (SyncLock)
        {
            if (_workerState == required) return;
            WorkerState old = _workerState;
            if (old != WorkerState.Closed) _workerState = WorkerState.Poisoned;
            throw new InvalidOperationException($"{method} requires {StateName(required)}; worker was {StateName(old)} and is now poisoned.");
        }
    }

    private static async Task<object> EndRunAsync()
    {
        Stopwatch timer = Stopwatch.StartNew();
        long endedGeneration;
        string endingPhase;
        Task driver;
        TaskCompletionSource<string>? parked;
        lock (SyncLock)
        {
            endedGeneration = _generation;
            if (_boundaryPhase is null)
            {
                _workerState = WorkerState.Poisoned;
                throw new InvalidOperationException("No stable decision boundary is parked.");
            }
            endingPhase = _boundaryPhase;
            if (_boundaryGeneration != endedGeneration || _pendingActionTcs is null || _pendingActionTcs.Task.IsCompleted)
            {
                _workerState = WorkerState.Poisoned;
                throw new InvalidOperationException("No stable decision boundary is parked.");
            }
            if (_driverTask is null)
            {
                _workerState = WorkerState.Poisoned;
                throw new InvalidOperationException("Shipped driver task was not captured.");
            }
            driver = _driverTask;
            parked = _pendingActionTcs;
            _generation++;
            _workerState = WorkerState.Ending;
            _staleRefusals = 0;
        }

        bool released = false;
        string driverResult = "unknown";
        try
        {
            FullAppBridgeMod.StopDriver();
            await CleanUpOnGameThreadAsync();
            released = parked.TrySetResult("abandon_run");
            Task completed = await Task.WhenAny(driver, Task.Delay(TimeSpan.FromSeconds(45)));
            if (!ReferenceEquals(completed, driver))
                throw new TimeoutException("Shipped driver did not exit within 45 seconds.");
            try
            {
                await driver;
                driverResult = "abandoned";
            }
            catch (OperationCanceledException)
            {
                driverResult = "cancelled";
            }
            if (RunManager.Instance?.DebugOnlyGetState() is not null)
                throw new InvalidOperationException("Shipped run state survived cleanup.");
            if (!ReferenceEquals(_driverTask, driver)
                || _shippedStartTask is null
                || !_shippedStartTask.IsCompletedSuccessfully
                || !ReferenceEquals(_pendingActionTcs, parked)
                || !parked.Task.IsCompletedSuccessfully
                || parked.Task.Result != "abandon_run"
                || _initialBoundaryTcs is null
                || !_initialBoundaryTcs.Task.IsCompletedSuccessfully
                || _boundaryGeneration != endedGeneration)
                throw new InvalidOperationException("Unsafe pending bridge state survived driver shutdown.");

            var historyCounts = new Dictionary<string, int>
            {
                ["actions"] = ActionHistory.Count,
                ["state_hashes"] = StateHashHistory.Count,
            };
            CurrentObservation = null;
            CurrentLegalActions = new();
            ActionHistory.Clear();
            StateHashHistory.Clear();
            FullAppStateTracker.ResetRunState();
            FullAppBridgeMod.ReleaseDriver();
            _pendingActionTcs = null;
            _initialBoundaryTcs = null;
            _driverTask = null;
            _shippedStartTask = null;
            _boundaryPhase = null;
            _boundaryGeneration = 0;
            RequestedSeed = "A1B2C3D4E5";
            RequestedCharacter = System.Environment.GetEnvironmentVariable("STS2_FORCE_CHARACTER") ?? "IRONCLAD";
            RequestedAscension = 0;
            IsRunStarted = false;
            lock (SyncLock)
            {
                if (_workerState != WorkerState.Ending)
                    throw new InvalidOperationException($"Worker became {StateName(_workerState)} during teardown.");
                _workerState = WorkerState.Idle;
            }
            return new Dictionary<string, object?>
            {
                ["ended_generation"] = endedGeneration,
                ["ending_phase"] = endingPhase,
                ["parked_wait_released"] = released,
                ["stale_continuation_refusals"] = _staleRefusals,
                ["driver_result"] = driverResult,
                ["reset_history_counts"] = historyCounts,
                ["final_state"] = "idle",
                ["duration_ms"] = timer.ElapsedMilliseconds,
            };
        }
        catch
        {
            parked.TrySetResult("abandon_run");
            Poison();
            throw;
        }
    }

    private static Task CleanUpOnGameThreadAsync()
    {
        var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        Callable.From(() =>
        {
            try
            {
                RunManager.Instance?.CleanUp();
                completion.TrySetResult(true);
            }
            catch (Exception ex) { completion.TrySetException(ex); }
        }).CallDeferred();
        return completion.Task;
    }

    private static async Task<object?> DispatchRequestAsync(string method, JsonElement parameters)
    {
        switch (method.ToLowerInvariant())
        {
            case "hello":
                ProgressionReadinessSnapshot readiness = ProgressReadiness.Snapshot();
                lock (SyncLock)
                {
                    if (_workerState is WorkerState.Poisoned or WorkerState.Closed)
                        throw new InvalidOperationException(
                            $"Worker is {StateName(_workerState)}; only close is accepted."
                            + (readiness.State == ProgressionReadinessState.Failed
                                ? $" Progression-complete baseline failed: {readiness.FailureMessage}"
                                : ""));
                }
                var hello = new Dictionary<string, object?>(FullAppBridgeHandshake.CreateHello(
                    readiness,
                    // Hash the shipped build only after profile readiness, so an initializing hello
                    // remains prompt even though the PCK is large.
                    () => GameBuild.Current,
                    System.Environment.ProcessId,
                    BoundPort,
                    FullAppBridgeMod.ReuseMode ? "reuse" : "fresh"));
                lock (SyncLock) hello["worker_state"] = StateName(_workerState);
                return hello;

            case "start_run":
                string declaredMode = parameters.TryGetProperty("process_mode", out JsonElement processMode)
                    ? processMode.ToString() : "";
                string actualMode = FullAppBridgeMod.ReuseMode ? "reuse" : "fresh";
                if (declaredMode != actualMode)
                    throw new ProcessModeMismatchException(
                        $"Client process mode {declaredMode} does not match worker mode {actualMode}.");
                FullAppBridgeHandshake.EnsureCanStart(ProgressReadiness);
                RequireState(WorkerState.Idle, "start_run");
                if (parameters.TryGetProperty("seed", out JsonElement seed))
                    RequestedSeed = seed.ToString();
                if (parameters.TryGetProperty("character", out JsonElement character))
                    RequestedCharacter = character.ToString();
                if (FullAppBridgeWireAdapter.TryReadInt32Parameter(parameters, "ascension", out int asc))
                    RequestedAscension = asc;

                if (RequestedAscension is < 0 or > 10)
                    throw new ArgumentOutOfRangeException("ascension", RequestedAscension, "Ascension must be between 0 and 10.");

                _initialBoundaryTcs = new TaskCompletionSource<bool>();
                lock (SyncLock)
                {
                    _generation++;
                    _runsStarted++;
                    _workerState = WorkerState.Running;
                }
                IsRunStarted = true;

                if (IsWarmRun) FullAppBridgeMod.StartWarmDriver();

                // Wait until the game reaches the first decision boundary
                await _initialBoundaryTcs.Task;
                if (FullAppBridgeMod.ReuseMode)
                {
                    Task<RunState> startedTask = _shippedStartTask
                        ?? throw new InvalidOperationException("Shipped run start task was not captured.");
                    await startedTask;
                }

                return new Dictionary<string, object?>
                {
                    ["started"] = true,
                    ["seed"] = RequestedSeed,
                    ["character"] = RequestedCharacter,
                    ["ascension"] = RequestedAscension,
                    ["unlock_policy"] = UnlockPolicy,
                    ["progression_policy"] = ProgressionCompletePolicy.Revision,
                    ["profile_fingerprint"] = ProgressReadiness.ProfileFingerprint,
                    ["observation"] = CurrentObservation,
                    ["legal_actions"] = CurrentLegalActions,
                };

            case "observe":
                RequireState(WorkerState.Running, "observe");
                return CurrentObservation;

            case "legal_actions":
                RequireState(WorkerState.Running, "legal_actions");
                return CurrentLegalActions;

            case "step":
                RequireState(WorkerState.Running, "step");
                string actionId = parameters.TryGetProperty("action_id", out JsonElement action)
                    ? action.ToString()
                    : "";
                if (string.IsNullOrWhiteSpace(actionId))
                    throw new ArgumentException("step requires action_id");

                // A card-select action is answered by the game's own flow rather than by a loop here,
                // so an action the prompt it is looking at does not offer would leave the game
                // blocked while the caller waits for a boundary that never comes. Rejecting it now,
                // against the actions this bridge is actually reporting, tells the caller instead.
                if (IsCardSelectAction(actionId) && !CurrentLegalActions.Any(action => action.ActionId == actionId))
                {
                    throw new ArgumentException(
                        $"'{actionId}' is not one of the legal actions the bridge reports for {CurrentObservation?.Phase}.");
                }

                ActionHistory.Add(actionId);

                _initialBoundaryTcs = new TaskCompletionSource<bool>();
                if (_pendingActionTcs != null && !_pendingActionTcs.Task.IsCompleted)
                {
                    _pendingActionTcs.SetResult(actionId);
                }

                await _initialBoundaryTcs.Task;

                if (CurrentObservation is not null)
                {
                    StateHashHistory.Add(CurrentObservation.StateHash);
                }

                return new Dictionary<string, object?>
                {
                    ["observation"] = CurrentObservation,
                    ["legal_actions"] = CurrentLegalActions,
                };

            case "history":
                RequireState(WorkerState.Running, "history");
                return new Dictionary<string, object?>
                {
                    ["seed"] = RequestedSeed,
                    ["character"] = RequestedCharacter,
                    ["ascension"] = RequestedAscension,
                    ["unlock_policy"] = UnlockPolicy,
                    ["actions"] = ActionHistory,
                    ["state_hashes"] = StateHashHistory,
                };

            case "end_run":
                if (!FullAppBridgeMod.ReuseMode)
                {
                    Poison();
                    throw new InvalidOperationException("end_run requires reuse process mode.");
                }
                RequireState(WorkerState.Running, "end_run");
                return await EndRunAsync();

            case "close":
                lock (SyncLock) _workerState = WorkerState.Closed;
                _ = Task.Run(async () =>
                {
                    await Task.Delay(50);
                    System.Environment.Exit(0);
                });
                return new Dictionary<string, object?> { ["closed"] = true };

            default:
                Poison();
                throw new NotSupportedException($"Unknown RPC method: {method}");
        }
    }

    public static async Task<string> WaitForCoordinatorActionAsync(
        string phase,
        bool isTerminal,
        bool isVictory,
        object? contextObject = null)
    {
        long generation = Volatile.Read(ref _generation);
        // The game can be waiting on two boundaries at once: the room's own loop re-reports the room
        // while the prompt an effect inside it opened is still open. Only one of them can be the
        // decision a caller answers, and a second boundary that published over the first would take
        // the caller's action away from the prompt the game is actually blocked on — so a boundary
        // waits its turn to publish, in the order the game asked for one.
        await BoundaryGate.WaitAsync();
        try
        {
            RefuseStale(generation);
            AutoSlayer.CurrentWatchdog?.Reset($"Bridge:{phase}");
            var (obs, actions) = FullAppStateTracker.CreateStateSnapshot(phase, isTerminal, isVictory, contextObject);
            CurrentObservation = obs;
            CurrentLegalActions = actions;

            if (StateHashHistory.Count == 0 && obs is not null)
            {
                StateHashHistory.Add(obs.StateHash);
            }

            if (isTerminal)
            {
                _initialBoundaryTcs?.TrySetResult(true);
                // Run has finished; keep server alive for final observation/history inspections
                return "terminal_halt";
            }

            _boundaryGeneration = generation;
            _boundaryPhase = phase;
            _pendingActionTcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            // Publish only after the parked wait exists. A caller may immediately request end_run.
            _initialBoundaryTcs?.TrySetResult(true);
            string chosenAction = await _pendingActionTcs.Task;
            RefuseStale(generation);
            _boundaryPhase = null;
            AutoSlayer.CurrentWatchdog?.Reset($"Bridge:{phase}:{chosenAction}");
            return chosenAction;
        }
        finally
        {
            BoundaryGate.Release();
        }
    }

    private static void RefuseStale(long generation)
    {
        if (generation == Volatile.Read(ref _generation)) return;
        Interlocked.Increment(ref _staleRefusals);
        throw new OperationCanceledException($"A continuation from abandoned generation {generation} was refused; current generation is {Volatile.Read(ref _generation)}.");
    }

    /// <summary>
    /// Whether an action answers a flat card-set prompt, which no loop here can answer for the caller.
    /// </summary>
    private static bool IsCardSelectAction(string actionId)
    {
        return actionId.StartsWith("choose_card_select:", StringComparison.Ordinal)
            || actionId == CardSelectPrompt.FinishActionId;
    }

    /// <summary>
    /// One flat card-set prompt the game opened, reported as a decision and answered by the caller.
    ///
    /// The offered cards are reported in the order the game offered them, each action naming the card
    /// it selects, so a caller selects by identity. The prompt is reported once per card it can still
    /// take: a caller that has chosen the game's minimum may finish there — which is how a prompt the
    /// game allows to be skipped is skipped — and one that has not chosen it is asked again until it
    /// has, so the set the game is handed is always a legal one.
    /// </summary>
    public static async Task<IEnumerable<CardModel>> CoordinateCardChoiceAsync(
        IEnumerable<CardModel> options,
        int minSelect,
        int maxSelect)
    {
        List<CardModel> offered = options.ToList();
        List<CardModel> selected = [];

        while (true)
        {
            List<CardModel> remaining = offered.Where(card => !selected.Contains(card)).ToList();
            if (remaining.Count == 0)
            {
                // The offer ran out: what was chosen is legal exactly when it meets the minimum, and
                // a short set is a caller error rather than something to hand the game quietly.
                if (selected.Count < minSelect)
                {
                    throw new InvalidOperationException(
                        $"A card prompt offered {offered.Count} card(s) and needs {minSelect} of them, "
                        + $"so the {selected.Count} chosen cannot satisfy it.");
                }

                return selected;
            }

            string actionId = await WaitForCoordinatorActionAsync(
                "simple_card_select",
                isTerminal: false,
                isVictory: false,
                new CardSelectPrompt(remaining, minSelect, maxSelect, selected.Select(card => card.Id.Entry).ToList()));

            if (actionId == CardSelectPrompt.FinishActionId)
            {
                if (selected.Count < minSelect)
                {
                    throw new InvalidOperationException(
                        $"A card prompt needs {minSelect} card(s) before it can be left, and {selected.Count} were chosen.");
                }

                return selected;
            }

            selected.Add(ResolveOfferedCard(actionId, remaining));
            if (selected.Count >= maxSelect)
            {
                return selected;
            }
        }
    }

    /// <summary>
    /// The card one offered action selects, resolved by the identity the action names.
    ///
    /// The action carries the position and the model id, and the model id is what decides: a deck
    /// holds copies of one card, so a position alone is ambiguous between them while a model id names
    /// the card a caller asked for. An action naming a card the prompt does not offer is a caller
    /// error rather than a reason to select something else, so it fails loudly — and `step` rejects
    /// such an action against the prompt's own legal actions before it can reach here, so the caller
    /// that made the mistake is told rather than left waiting for a boundary that never comes.
    /// </summary>
    private static CardModel ResolveOfferedCard(string actionId, IReadOnlyList<CardModel> remaining)
    {
        string[] parts = actionId.Split(':');
        if (parts.Length < 3 || parts[0] != "choose_card_select")
        {
            throw new InvalidOperationException(
                $"A card prompt offers {string.Join(", ", remaining.Select(card => card.Id.Entry))}, "
                + $"so it cannot be answered with {actionId}.");
        }

        string modelId = string.Join(':', parts[2..]);
        CardModel? named = remaining.FirstOrDefault(card => card.Id.Entry == modelId);
        if (named is null)
        {
            throw new InvalidOperationException(
                $"A card prompt offers {string.Join(", ", remaining.Select(card => card.Id.Entry))}, "
                + $"which does not include {modelId}.");
        }

        if (int.TryParse(parts[1], out int index) && index >= 0 && index < remaining.Count
            && remaining[index].Id.Entry == modelId)
        {
            return remaining[index];
        }

        return named;
    }
}
