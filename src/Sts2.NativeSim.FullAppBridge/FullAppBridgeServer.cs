using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;

namespace Sts2.NativeSim.FullAppBridge;

public static class FullAppBridgeServer
{
    private static TcpListener? _listener;
    private static TcpClient? _client;
    private static NetworkStream? _stream;
    private static StreamWriter? _writer;
    private static StreamReader? _reader;
    private static TaskCompletionSource<string>? _pendingActionTcs;
    private static TaskCompletionSource<bool>? _initialBoundaryTcs;
    private static readonly object SyncLock = new();

    public static int BoundPort { get; private set; }
    public static ObservationDto? CurrentObservation { get; set; }
    public static List<LegalActionDto> CurrentLegalActions { get; set; } = new();
    public static List<string> ActionHistory { get; } = new();
    public static List<string> StateHashHistory { get; } = new();

    public static string RequestedSeed { get; private set; } = "A1B2C3D4E5";
    public static string RequestedCharacter { get; private set; } = "IRONCLAD";
    public static int RequestedAscension { get; private set; } = 0;

    /// <summary>Act-1 pin; the reconstructed environment always uses the default Act 1 (Overgrowth).</summary>
    public static string RequestedAct1 { get; private set; } = "overgrowth";

    /// <summary>
    /// When set, the bridge pins the sandbox profile (every epoch revealed, every encounter seen,
    /// non-zero run count, ascension unlocked) before the run starts, mirroring the reconstructed
    /// environment's `UnlockState.all` run-start profile. Without it a fresh sandbox has no Neow
    /// and clamps every requested ascension to 0.
    /// </summary>
    public static bool PinProfile { get; private set; } = true;

    /// <summary>
    /// When set, nested card/bundle choices the game would resolve through the AutoSlay selector are
    /// exposed to the protocol as `card_choice` / `option_choice` decisions instead of being
    /// auto-picked, so a caller can reproduce a specific Neow branch.
    /// </summary>
    public static bool ProtocolNestedChoices { get; private set; } = true;

    /// <summary>
    /// When set, the combat loop reports one final `combat_complete` boundary after the action that
    /// leaves the encounter with no living enemy and the player alive, before the run generates room
    /// rewards. That is the comparator's unified terminal state.
    /// </summary>
    public static bool EmitCombatCompleteBoundary { get; private set; }

    public static bool IsRunStarted { get; private set; }

    /// <summary>The room phase the last non-choice decision boundary reported.</summary>
    public static string CurrentPhase { get; private set; } = "map";

    /// <summary>The nested choice the shipped game is currently waiting on, if any.</summary>
    public static BridgePendingChoice? PendingChoice { get; private set; }

    private static int _choiceOrdinal;

    /// <summary>Run-start provenance recorded for the differential report.</summary>
    public static Dictionary<string, object?> RunStartProvenance { get; } = new();

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
        while (true)
        {
            string? line = await reader.ReadLineAsync();
            if (line is null) break;
            if (string.IsNullOrWhiteSpace(line)) continue;

            try
            {
                RpcRequest? request = JsonSerializer.Deserialize<RpcRequest>(line);
                if (request is null) continue;

                object? result = await DispatchRequestAsync(request.Method, request.Params);
                var response = new RpcResponse
                {
                    Id = request.Id,
                    Result = result,
                };
                string responseJson = JsonSerializer.Serialize(response);
                await writer.WriteLineAsync(responseJson);
            }
            catch (Exception ex)
            {
                var errorResponse = new RpcResponse
                {
                    Id = 0,
                    Error = ex.Message,
                };
                await writer.WriteLineAsync(JsonSerializer.Serialize(errorResponse));
            }
        }
    }

    private static async Task<object?> DispatchRequestAsync(string method, Dictionary<string, object?>? parameters)
    {
        switch (method.ToLowerInvariant())
        {
            case "hello":
                return new Dictionary<string, object?>
                {
                    ["status"] = "ready",
                    ["version"] = "0.1.0+59260271157f76a2896f0eab5bc6ea1245d8b314",
                    ["pid"] = Environment.ProcessId,
                    ["bound_port"] = BoundPort,
                    ["observation_schema_version"] = 3,
                    ["game_build"] = FullAppBuildIdentity.Value,
                    ["run_start"] = new Dictionary<string, object?>
                    {
                        ["method"] = "start_run",
                        ["pin_profile"] = PinProfile,
                        ["act1"] = RequestedAct1,
                        ["protocol_nested_choices"] = ProtocolNestedChoices,
                        ["unlock_profile"] = "pinned_all_epochs_revealed",
                        ["provenance"] = RunStartProvenance,
                    },
                };

            case "start_run":
                if (parameters is not null)
                {
                    if (parameters.TryGetValue("seed", out var s) && s is not null)
                        RequestedSeed = s.ToString()!;
                    if (parameters.TryGetValue("character", out var c) && c is not null)
                        RequestedCharacter = c.ToString()!;
                    if (parameters.TryGetValue("ascension", out var a) && a is not null && int.TryParse(a.ToString(), out int asc))
                        RequestedAscension = asc;
                    if (parameters.TryGetValue("act1", out var act1) && act1 is not null && act1.ToString() is { Length: > 0 } act1Value)
                        RequestedAct1 = act1Value;
                    if (parameters.TryGetValue("pin_profile", out var pin) && pin is not null && bool.TryParse(pin.ToString(), out bool pinValue))
                        PinProfile = pinValue;
                    if (parameters.TryGetValue("nested_choices", out var nested) && nested is not null && bool.TryParse(nested.ToString(), out bool nestedValue))
                        ProtocolNestedChoices = nestedValue;
                    if (parameters.TryGetValue("combat_complete", out var complete) && complete is not null && bool.TryParse(complete.ToString(), out bool completeValue))
                        EmitCombatCompleteBoundary = completeValue;
                }

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
                    ["observation"] = CurrentObservation,
                    ["legal_actions"] = CurrentLegalActions,
                };

            case "observe":
                return CurrentObservation;

            case "legal_actions":
                return CurrentLegalActions;

            case "step":
                string actionId = parameters?["action_id"]?.ToString() ?? "";
                if (string.IsNullOrWhiteSpace(actionId))
                    throw new ArgumentException("step requires action_id");

                BridgePendingChoice? pending = PendingChoice;
                if (pending is not null && !actionId.StartsWith(pending.ActionKind + ":", StringComparison.Ordinal))
                {
                    throw new ArgumentException(
                        $"action '{actionId}' does not answer the pending {pending.DecisionKind} '{pending.ChoiceId}'");
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
        AutoSlayer.CurrentWatchdog?.Reset($"Bridge:{phase}");
        if (!IsChoicePhase(phase)) CurrentPhase = phase;
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

    private static bool IsChoicePhase(string phase) => phase is "card_choice" or "option_choice";

    /// <summary>
    /// Expose one native card selection as a protocol decision and return the cards the caller chose.
    ///
    /// Used by <see cref="BridgeCardSelector"/>; the shipped game awaits this inside the effect that
    /// opened the selection (a Neow blessing, a relic's `AfterObtained`, a combat-start hook), so the
    /// ambient room phase is preserved in the observation while the choice is pending.
    /// </summary>
    public static async Task<IReadOnlyList<CardModel>> CoordinateCardChoiceAsync(
        IReadOnlyList<CardModel> options,
        int minSelect,
        int maxSelect)
    {
        if (PendingChoice is not null)
            throw new InvalidOperationException("A second native choice began before the first was resolved.");
        if (options.Count == 0)
            throw new InvalidOperationException("The native card choice exposed zero options.");

        string choiceId = $"card-choice-{Interlocked.Increment(ref _choiceOrdinal) - 1}";
        string[] optionIds = options.Select((_, index) => $"{choiceId}-option-{index}").ToArray();
        var pending = new BridgePendingChoice
        {
            ChoiceId = choiceId,
            DecisionKind = "card_choice",
            ActionKind = "choose_cards",
            OptionIds = optionIds,
            MinSelect = minSelect,
            MaxSelect = Math.Min(maxSelect, options.Count),
            Options = options.Select((card, index) => new ChoiceOptionDto
            {
                OptionId = optionIds[index],
                ModelId = card.Id.Entry,
            }).ToList(),
        };

        PendingChoice = pending;
        try
        {
            string actionId = await WaitForCoordinatorActionAsync("card_choice", isTerminal: false, isVictory: false, pending);
            string[] selected = ParseSelection(actionId, pending);
            return selected.Select(id => options[Array.IndexOf(optionIds, id)]).ToList();
        }
        finally
        {
            PendingChoice = null;
        }
    }

    /// <summary>
    /// Expose one native bundle/relic option choice as a protocol decision and return the chosen
    /// option indices. The caller supplies the semantic option payloads; option ids are assigned
    /// here so a caller cannot mismatch them.
    /// </summary>
    public static async Task<int[]> CoordinateOptionChoiceAsync(
        IReadOnlyList<ChoiceOptionDto> options,
        int minSelect,
        int maxSelect)
    {
        if (PendingChoice is not null)
            throw new InvalidOperationException("A second native choice began before the first was resolved.");
        if (options.Count == 0)
            throw new InvalidOperationException("The native option choice exposed zero options.");

        string choiceId = $"option-choice-{Interlocked.Increment(ref _choiceOrdinal) - 1}";
        string[] optionIds = options.Select((_, index) => $"{choiceId}-option-{index}").ToArray();
        var resolved = options.Select((option, index) => new ChoiceOptionDto
        {
            OptionId = optionIds[index],
            ModelId = option.ModelId,
            Cards = option.Cards,
        }).ToList();
        var pending = new BridgePendingChoice
        {
            ChoiceId = choiceId,
            DecisionKind = "option_choice",
            ActionKind = "choose_option",
            OptionIds = optionIds,
            MinSelect = minSelect,
            MaxSelect = Math.Min(maxSelect, options.Count),
            Options = resolved,
        };

        PendingChoice = pending;
        try
        {
            string actionId = await WaitForCoordinatorActionAsync("option_choice", isTerminal: false, isVictory: false, pending);
            string[] selected = ParseSelection(actionId, pending);
            return selected.Select(id => Array.IndexOf(optionIds, id)).ToArray();
        }
        finally
        {
            PendingChoice = null;
        }
    }

    /// <summary>
    /// A card-reward claim that names its card up front.
    ///
    /// The reconstructed environment exposes the cards of a `CardReward` as direct claims, while the
    /// shipped game needs two native steps (open the reward, then pick a card on the sub-screen). The
    /// bridge keeps that split as a coordinator detail: the rewards room records the claim here, and the
    /// card reward screen handler consumes it instead of asking the caller a second time.
    /// </summary>
    private static FusedCardRewardClaim? _fusedCardRewardClaim;

    public static void SetFusedCardRewardClaim(FusedCardRewardClaim claim)
    {
        lock (SyncLock)
        {
            _fusedCardRewardClaim = claim;
        }
    }

    public static FusedCardRewardClaim? TakeFusedCardRewardClaim()
    {
        lock (SyncLock)
        {
            FusedCardRewardClaim? claim = _fusedCardRewardClaim;
            _fusedCardRewardClaim = null;
            return claim;
        }
    }

    /// <summary>Parses `{action_kind}:{choice_id}:{suffix}` into the selected option ids.</summary>
    internal static string[] ParseSelection(string actionId, BridgePendingChoice pending)
    {
        string[] parts = actionId.Split(':');
        if (parts.Length != 3 || parts[0] != pending.ActionKind || parts[1] != pending.ChoiceId)
        {
            throw new ArgumentException($"action '{actionId}' is not a valid answer to choice '{pending.ChoiceId}'");
        }
        if (parts[2] == "skip")
        {
            if (pending.MinSelect > 0)
                throw new ArgumentException($"choice '{pending.ChoiceId}' requires at least {pending.MinSelect} selection(s)");
            return Array.Empty<string>();
        }
        string[] selected = parts[2].Split('+', StringSplitOptions.RemoveEmptyEntries)
            .Select(Uri.UnescapeDataString)
            .ToArray();
        if (selected.Distinct(StringComparer.Ordinal).Count() != selected.Length
            || selected.Length < pending.MinSelect
            || selected.Length > pending.MaxSelect
            || selected.Any(id => !pending.OptionIds.Contains(id, StringComparer.Ordinal)))
        {
            throw new ArgumentException($"selection '{parts[2]}' does not satisfy choice '{pending.ChoiceId}'");
        }
        return selected;
    }
}

/// <summary>
/// A card-reward claim that names its card up front: the option index inside the reward's offered
/// cards, and the card model it must resolve to.
/// </summary>
public sealed record FusedCardRewardClaim(int OptionIndex, string CardId);
