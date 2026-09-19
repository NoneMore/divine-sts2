using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.RunSession.States;

/// <summary>
/// The closed set of decisions that can be active behind <see cref="IActiveRunSession"/>. Native
/// asynchronous work stays in the adapter; a prompt holds only a typed route back to that suspended
/// work.
/// </summary>
internal abstract class ActiveRunState
{
    protected ActiveRunState(DecisionFrame frame)
    {
        Frame = frame;
        Actions = Index(frame.LegalActions);
    }

    public DecisionFrame Frame { get; }
    protected IReadOnlyDictionary<string, LegalAction> Actions { get; }
    public abstract Task<ActiveRunState> ApplyAsync(string actionId);

    protected LegalAction RequireAction(string actionId)
    {
        if (Actions.TryGetValue(actionId, out LegalAction? action)) return action;
        throw new ProtocolException(
            "invalid_action",
            $"Action '{actionId}' is not legal in the current decision frame.");
    }

    private static IReadOnlyDictionary<string, LegalAction> Index(IReadOnlyList<LegalAction> actions)
    {
        Dictionary<string, LegalAction> indexed = new(StringComparer.Ordinal);
        foreach (LegalAction action in actions)
        {
            if (!indexed.TryAdd(action.ActionId, action))
                throw new ProtocolException(
                    "action_id_collision",
                    $"Action id '{action.ActionId}' is advertised more than once in the current decision frame.");
        }
        return indexed;
    }
}

/// <summary>A typed, in-memory route from a prompt to the native decision it suspended.</summary>
internal sealed class RunContinuation<T>(
    SuspendedNativeDecision parent,
    Func<SuspendedNativeDecision, T, Task<ActiveRunState>> resume)
{
    public Task<ActiveRunState> ResumeAsync(T value) => resume(parent, value);
}

/// <summary>A non-prompt decision, including compatibility states and terminal states.</summary>
internal sealed class NativeDecisionState(
    DecisionFrame frame,
    Func<string, Task<ActiveRunState>> apply) : ActiveRunState(frame)
{
    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return apply(actionId);
    }
}

/// <summary>
/// A map projection and the executors for exactly the actions advertised by that projection.
/// Each executor carries only a semantic coordinate; the native adapter owns map lookup and room
/// entry.
/// </summary>
internal sealed class MapDecisionState : ActiveRunState
{
    private readonly IReadOnlyDictionary<string, Func<Task<ActiveRunState>>> _executors;

    public MapDecisionState(
        DecisionFrame frame,
        IReadOnlyDictionary<string, MapPointSelection> actions,
        Func<MapPointSelection, Task<ActiveRunState>> enter) : base(frame)
    {
        Dictionary<string, Func<Task<ActiveRunState>>> executors = new(StringComparer.Ordinal);
        foreach ((string actionId, MapPointSelection selection) in actions)
        {
            if (!Actions.ContainsKey(actionId))
                throw new ProtocolException(
                    "protocol_desync",
                    $"Map executor '{actionId}' has no advertised legal action.");
            executors.Add(actionId, () => enter(selection));
        }
        if (executors.Count != Actions.Count)
            throw new ProtocolException(
                "protocol_desync",
                "The map projection and its hidden action executors do not describe the same actions.");
        _executors = executors;
    }

    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return _executors[actionId]();
    }
}

/// <summary>
/// The complete rest-site decision. The state keeps projection and execution paired while the
/// adapter receives only the selected native option identity.
/// </summary>
internal sealed class RestDecisionState : ActiveRunState
{
    private readonly IReadOnlyDictionary<string, Func<Task<ActiveRunState>>> _executors;

    public RestDecisionState(
        DecisionFrame frame,
        Func<RestSelection, Task<ActiveRunState>> choose,
        Func<Task<ActiveRunState>> leave) : base(frame)
    {
        Dictionary<string, Func<Task<ActiveRunState>>> executors = new(StringComparer.Ordinal);
        foreach (LegalAction action in frame.LegalActions)
        {
            executors.Add(action.ActionId, action.Kind switch
            {
                "choose_rest" => () => choose(new(Convert.ToString(action.Parameters["option_id"])!)),
                "leave_rest" => leave,
                _ => throw new ProtocolException(
                    "protocol_desync",
                    $"Rest projection advertised non-rest action '{action.Kind}'.")
            });
        }
        _executors = executors;
    }

    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return _executors[actionId]();
    }
}

/// <summary>A treasure-room projection paired with semantic open, relic-pick and skip executors.</summary>
internal sealed class TreasureDecisionState : ActiveRunState
{
    private readonly IReadOnlyDictionary<string, Func<Task<ActiveRunState>>> _executors;

    public TreasureDecisionState(
        DecisionFrame frame,
        Func<Task<ActiveRunState>> open,
        Func<TreasureSelection, Task<ActiveRunState>> choose,
        Func<Task<ActiveRunState>> leave) : base(frame)
    {
        Dictionary<string, Func<Task<ActiveRunState>>> executors = new(StringComparer.Ordinal);
        foreach (LegalAction action in frame.LegalActions)
        {
            executors.Add(action.ActionId, action.Kind switch
            {
                "open_treasure" => open,
                "choose_treasure" => () => choose(new(Convert.ToInt32(action.Parameters["option_index"]))),
                "skip_treasure" => () => choose(new(null)),
                "leave_treasure" => leave,
                _ => throw new ProtocolException(
                    "protocol_desync",
                    $"Treasure projection advertised non-treasure action '{action.Kind}'.")
            });
        }
        _executors = executors;
    }

    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return _executors[actionId]();
    }
}

/// <summary>A shop projection paired with semantic inventory-index and leave executors.</summary>
internal sealed class ShopDecisionState : ActiveRunState
{
    private readonly IReadOnlyDictionary<string, Func<Task<ActiveRunState>>> _executors;

    public ShopDecisionState(
        DecisionFrame frame,
        Func<ShopSelection, Task<ActiveRunState>> buy,
        Func<Task<ActiveRunState>> leave) : base(frame)
    {
        Dictionary<string, Func<Task<ActiveRunState>>> executors = new(StringComparer.Ordinal);
        foreach (LegalAction action in frame.LegalActions)
        {
            executors.Add(action.ActionId, action.Kind switch
            {
                "buy_shop" => () => buy(new(Convert.ToInt32(action.Parameters["entry_index"]))),
                "leave_shop" => leave,
                _ => throw new ProtocolException(
                    "protocol_desync",
                    $"Shop projection advertised non-shop action '{action.Kind}'.")
            });
        }
        _executors = executors;
    }

    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return _executors[actionId]();
    }
}

/// <summary>The sole active state while the shipped game is waiting for cards.</summary>
internal sealed class CardSelectPromptState(
    DecisionFrame frame,
    RunContinuation<CardSelection> continuation) : ActiveRunState(frame)
{
    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        LegalAction action = RequireAction(actionId);
        if (!PromptActionKind.IsCard(action.Kind))
            throw new ProtocolException("invalid_choice", $"Card-select prompt cannot apply '{action.Kind}'.");
        return continuation.ResumeAsync(new(action.ActionId, StringValues(action, "option_ids")));
    }

    private static IReadOnlyList<string> StringValues(LegalAction action, string key)
    {
        if (!action.Parameters.TryGetValue(key, out object? value) || value is not IEnumerable<string> values)
            throw new ProtocolException("invalid_choice", $"Card-select action '{action.ActionId}' has no {key}.");
        return values.ToArray();
    }
}

/// <summary>
/// A reward prompt uses the same typed-continuation shape as a Card-select prompt. This also models
/// nested reward sets without a second active parent flag.
/// </summary>
internal sealed class RewardPromptState(
    DecisionFrame frame,
    RunContinuation<RewardSelection> continuation) : ActiveRunState(frame)
{
    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        LegalAction action = RequireAction(actionId);
        if (!PromptActionKind.IsReward(action.Kind))
            throw new ProtocolException("invalid_choice", $"Reward prompt cannot apply '{action.Kind}'.");
        return continuation.ResumeAsync(new(
            action.ActionId,
            Integer(action, "reward_index"),
            Integer(action, "child_index"),
            Integer(action, "option_index")));
    }

    private static int? Integer(LegalAction action, string key) =>
        action.Parameters.TryGetValue(key, out object? value) && value is not null
            ? Convert.ToInt32(value)
            : null;
}

/// <summary>Turns semantic adapter captures into exactly one active state.</summary>
internal sealed class ActiveRunStateFactory(IRunSessionCompatibilityAdapter adapter)
{
    public ActiveRunState Create(CompatibilityCapture capture)
    {
        DecisionFrame frame = capture.Frame;
        if (capture.MapActions is { } mapActions)
            return new MapDecisionState(frame, mapActions, EnterMapPointAsync);
        if (capture.SimpleRoom is SimpleRoomKind.Rest)
            return new RestDecisionState(frame, ChooseRestAsync, () => LeaveSimpleRoomAsync(SimpleRoomKind.Rest));
        if (capture.SimpleRoom is SimpleRoomKind.Treasure)
            return new TreasureDecisionState(
                frame,
                OpenTreasureAsync,
                ChooseTreasureAsync,
                () => LeaveSimpleRoomAsync(SimpleRoomKind.Treasure));
        if (capture.SimpleRoom is SimpleRoomKind.Shop)
            return new ShopDecisionState(
                frame,
                BuyShopEntryAsync,
                () => LeaveSimpleRoomAsync(SimpleRoomKind.Shop));
        if (IsCardPrompt(frame))
        {
            SuspendedNativeDecision parent = Parent(capture);
            return new CardSelectPromptState(
                frame,
                new(parent, static (suspended, selection) => suspended.ResumeAsync(selection)));
        }
        if (IsRewardPrompt(frame))
        {
            SuspendedNativeDecision parent = Parent(capture);
            return new RewardPromptState(
                frame,
                new(parent, static (suspended, selection) => suspended.ResumeAsync(selection)));
        }
        return new NativeDecisionState(frame, ContinueAsync);
    }

    private async Task<ActiveRunState> ContinueAsync(string actionId) =>
        Create(await adapter.ApplyAsync(actionId).ConfigureAwait(false));

    private async Task<ActiveRunState> EnterMapPointAsync(MapPointSelection selection) =>
        Create(await adapter.EnterMapPointAsync(selection).ConfigureAwait(false));

    private async Task<ActiveRunState> ChooseRestAsync(RestSelection selection) =>
        Create(await adapter.ChooseRestAsync(selection).ConfigureAwait(false));

    private async Task<ActiveRunState> OpenTreasureAsync() =>
        Create(await adapter.OpenTreasureAsync().ConfigureAwait(false));

    private async Task<ActiveRunState> ChooseTreasureAsync(TreasureSelection selection) =>
        Create(await adapter.ChooseTreasureAsync(selection).ConfigureAwait(false));

    private async Task<ActiveRunState> BuyShopEntryAsync(ShopSelection selection) =>
        Create(await adapter.BuyShopEntryAsync(selection).ConfigureAwait(false));

    private async Task<ActiveRunState> LeaveSimpleRoomAsync(SimpleRoomKind room) =>
        Create(await adapter.LeaveSimpleRoomAsync(room).ConfigureAwait(false));

    private static bool IsCardPrompt(DecisionFrame frame) =>
        frame.LegalActions.Count > 0
        && frame.LegalActions.All(action => PromptActionKind.IsCard(action.Kind));

    private static bool IsRewardPrompt(DecisionFrame frame) =>
        frame.LegalActions.Count > 0
        && frame.LegalActions.All(action => PromptActionKind.IsReward(action.Kind));

    private SuspendedNativeDecision Parent(CompatibilityCapture capture) => new(
        adapter,
        this,
        capture.PromptParent
            ?? throw new ProtocolException(
                "protocol_desync",
                "The native adapter exposed a prompt without its suspended-parent token."));
}

/// <summary>
/// The typed route back to the native parent suspended by a prompt. The adapter owns the actual
/// native task/completion source; this object owns only the semantic way to resume it.
/// </summary>
internal sealed class SuspendedNativeDecision(
    IRunSessionCompatibilityAdapter adapter,
    ActiveRunStateFactory states,
    PromptResumeToken parent)
{
    public async Task<ActiveRunState> ResumeAsync(CardSelection selection) =>
        states.Create(await adapter.ResumeCardSelectAsync(parent, selection).ConfigureAwait(false));

    public async Task<ActiveRunState> ResumeAsync(RewardSelection selection) =>
        states.Create(await adapter.ResumeRewardAsync(parent, selection).ConfigureAwait(false));
}

internal static class PromptActionKind
{
    public static bool IsCard(string kind) => kind == "choose_cards";
    public static bool IsReward(string kind) => kind is "choose_custom_reward" or "skip_custom_rewards";
}
