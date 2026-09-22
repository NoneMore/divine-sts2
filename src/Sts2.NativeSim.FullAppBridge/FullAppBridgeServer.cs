using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.FullAppBridge;

public static class FullAppBridgeServer
{
    public const string UnlockPolicy = "all";
    private static readonly ProgressionReadiness ProgressReadiness = new();
    private static TcpListener? _listener;
    private static TcpClient? _client;
    private static NetworkStream? _stream;
    private static StreamWriter? _writer;
    private static StreamReader? _reader;
    private static TaskCompletionSource<string>? _pendingActionTcs;
    private static TaskCompletionSource<bool>? _initialBoundaryTcs;

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

    public static void MarkProgressReady(string fingerprint) => ProgressReadiness.Complete(fingerprint);

    public static void MarkProgressFailed(Exception failure) => ProgressReadiness.Fail(failure);

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
        string forceChar = Environment.GetEnvironmentVariable("STS2_FORCE_CHARACTER") ?? "";
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
                    _client?.Dispose();
                    _client = client;
                    _stream = client.GetStream();
                    _writer = new StreamWriter(_stream, new UTF8Encoding(false)) { AutoFlush = true };
                    _reader = new StreamReader(_stream, new UTF8Encoding(false));
                }

                _ = HandleClientAsync(_reader, _writer);
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

                RpcRequest? request = null;
                try
                {
                    request = FullAppBridgeWireAdapter.DecodeRequest(line);

                    object? result = await DispatchRequestAsync(request.Method, request.Parameters);
                    RpcResponse response = new(request.Id, true, result);
                    string responseJson = FullAppBridgeWireAdapter.EncodeResponse(response);
                    await writer.WriteLineAsync(responseJson);
                }
                catch (Exception ex)
                {
                    RpcResponse errorResponse = new(
                        request?.Id ?? "0",
                        false,
                        Error: new ProtocolError("bridge_error", ex.Message));
                    await writer.WriteLineAsync(FullAppBridgeWireAdapter.EncodeResponse(errorResponse));
                }
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
                    _client?.Dispose();
                    _client = null;
                    _stream = null;
                    _writer = null;
                    _reader = null;
                }
            }
        }
    }

    private static async Task<object?> DispatchRequestAsync(string method, JsonElement parameters)
    {
        switch (method.ToLowerInvariant())
        {
            case "hello":
                ProgressionReadinessSnapshot readiness = ProgressReadiness.Snapshot();
                return FullAppBridgeHandshake.CreateHello(
                    readiness,
                    // Hash the shipped build only after profile readiness, so an initializing hello
                    // remains prompt even though the PCK is large.
                    () => GameBuild.Current,
                    Environment.ProcessId,
                    BoundPort,
                    "fresh");

            case "start_run":
                FullAppBridgeHandshake.EnsureCanStart(ProgressReadiness);
                if (parameters.TryGetProperty("seed", out JsonElement seed))
                    RequestedSeed = seed.ToString();
                if (parameters.TryGetProperty("character", out JsonElement character))
                    RequestedCharacter = character.ToString();
                if (FullAppBridgeWireAdapter.TryReadInt32Parameter(parameters, "ascension", out int asc))
                    RequestedAscension = asc;

                if (RequestedAscension is < 0 or > 10)
                    throw new ArgumentOutOfRangeException("ascension", RequestedAscension, "Ascension must be between 0 and 10.");

                _initialBoundaryTcs = new TaskCompletionSource<bool>();
                IsRunStarted = true;

                // Wait until the game reaches the first decision boundary
                await _initialBoundaryTcs.Task;

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
                return CurrentObservation;

            case "legal_actions":
                return CurrentLegalActions;

            case "step":
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
                return new Dictionary<string, object?>
                {
                    ["seed"] = RequestedSeed,
                    ["character"] = RequestedCharacter,
                    ["ascension"] = RequestedAscension,
                    ["unlock_policy"] = UnlockPolicy,
                    ["actions"] = ActionHistory,
                    ["state_hashes"] = StateHashHistory,
                };

            case "close":
                _ = Task.Run(async () =>
                {
                    await Task.Delay(50);
                    Environment.Exit(0);
                });
                return new Dictionary<string, object?> { ["closed"] = true };

            default:
                throw new NotSupportedException($"Unknown RPC method: {method}");
        }
    }

    public static async Task<string> WaitForCoordinatorActionAsync(
        string phase,
        bool isTerminal,
        bool isVictory,
        object? contextObject = null)
    {
        // The game can be waiting on two boundaries at once: the room's own loop re-reports the room
        // while the prompt an effect inside it opened is still open. Only one of them can be the
        // decision a caller answers, and a second boundary that published over the first would take
        // the caller's action away from the prompt the game is actually blocked on — so a boundary
        // waits its turn to publish, in the order the game asked for one.
        await BoundaryGate.WaitAsync();
        try
        {
            AutoSlayer.CurrentWatchdog?.Reset($"Bridge:{phase}");
            var (obs, actions) = FullAppStateTracker.CreateStateSnapshot(phase, isTerminal, isVictory, contextObject);
            CurrentObservation = obs;
            CurrentLegalActions = actions;

            if (StateHashHistory.Count == 0 && obs is not null)
            {
                StateHashHistory.Add(obs.StateHash);
            }

            // Notify that a decision boundary has been reached
            _initialBoundaryTcs?.TrySetResult(true);

            if (isTerminal)
            {
                // Run has finished; keep server alive for final observation/history inspections
                return "terminal_halt";
            }

            _pendingActionTcs = new TaskCompletionSource<string>();
            string chosenAction = await _pendingActionTcs.Task;
            AutoSlayer.CurrentWatchdog?.Reset($"Bridge:{phase}:{chosenAction}");
            return chosenAction;
        }
        finally
        {
            BoundaryGate.Release();
        }
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
