using System.Diagnostics;
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
internal abstract class SimpleRoomDecisionState : ActiveRunState
{
    private readonly IReadOnlyDictionary<string, Func<Task<ActiveRunState>>> _executors;

    protected SimpleRoomDecisionState(
        DecisionFrame frame,
        SimpleRoomKind room,
        Func<LegalAction, Func<Task<ActiveRunState>>?> executor) : base(frame)
    {
        Dictionary<string, Func<Task<ActiveRunState>>> executors = new(StringComparer.Ordinal);
        foreach (LegalAction action in frame.LegalActions)
        {
            executors.Add(
                action.ActionId,
                executor(action) ?? throw new ProtocolException(
                    "protocol_desync",
                    $"{room.Stage()} projection advertised non-{room.Stage()} action '{action.Kind}'."));
        }
        _executors = executors;
    }

    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return _executors[actionId]();
    }
}

internal sealed class RestDecisionState : SimpleRoomDecisionState
{
    public RestDecisionState(
        DecisionFrame frame,
        Func<RestSelection, Task<ActiveRunState>> choose,
        Func<Task<ActiveRunState>> leave) : base(
            frame,
            SimpleRoomKind.Rest,
            action => action.Kind switch
            {
                "choose_rest" => () => choose(new(Convert.ToString(action.Parameters["option_id"])!)),
                "leave_rest" => leave,
                _ => null
            }) { }
}

/// <summary>A treasure-room projection paired with semantic open, relic-pick and skip executors.</summary>
internal sealed class TreasureDecisionState : SimpleRoomDecisionState
{
    public TreasureDecisionState(
        DecisionFrame frame,
        Func<Task<ActiveRunState>> open,
        Func<TreasureSelection, Task<ActiveRunState>> choose,
        Func<Task<ActiveRunState>> leave) : base(
            frame,
            SimpleRoomKind.Treasure,
            action => action.Kind switch
            {
                "open_treasure" => open,
                "choose_treasure" => () => choose(new(Convert.ToInt32(action.Parameters["option_index"]))),
                "skip_treasure" => () => choose(new(null)),
                "leave_treasure" => leave,
                _ => null
            }) { }
}

/// <summary>A shop projection paired with semantic inventory-index and leave executors.</summary>
internal sealed class ShopDecisionState : SimpleRoomDecisionState
{
    public ShopDecisionState(
        DecisionFrame frame,
        Func<ShopSelection, Task<ActiveRunState>> buy,
        Func<Task<ActiveRunState>> leave) : base(
            frame,
            SimpleRoomKind.Shop,
            action => action.Kind switch
            {
                "buy_shop" => () => buy(new(Convert.ToInt32(action.Parameters["entry_index"]))),
                "leave_shop" => leave,
                _ => null
            }) { }
}

/// <summary>An Ancient or ordinary event projection paired with its semantic executors.</summary>
internal sealed class EventDecisionState : ActiveRunState
{
    private readonly IReadOnlyDictionary<string, Func<Task<ActiveRunState>>> _executors;

    public EventDecisionState(
        DecisionFrame frame,
        Func<EventSelection, Task<ActiveRunState>> choose,
        Func<Task<ActiveRunState>> leave) : base(frame)
    {
        _executors = frame.LegalActions.ToDictionary(
            action => action.ActionId,
            action => action.Kind switch
            {
                "choose_event" => (Func<Task<ActiveRunState>>)(() =>
                    choose(new(Convert.ToInt32(action.Parameters["option_index"])))),
                "leave_event" => leave,
                _ => throw new ProtocolException(
                    "protocol_desync",
                    $"Event projection advertised non-event action '{action.Kind}'.")
            },
            StringComparer.Ordinal);
    }

    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return _executors[actionId]();
    }
}

/// <summary>A standalone card, relic, or potion reward paired with its semantic selection.</summary>
internal sealed class StandaloneRewardDecisionState : ActiveRunState
{
    private readonly IReadOnlyDictionary<string, Func<Task<ActiveRunState>>> _executors;

    public StandaloneRewardDecisionState(
        DecisionFrame frame,
        Func<StandaloneRewardSelection, Task<ActiveRunState>> choose) : base(frame)
    {
        _executors = frame.LegalActions.ToDictionary(
            action => action.ActionId,
            action => action.Kind == "choose_reward"
                ? (Func<Task<ActiveRunState>>)(() => choose(new(Convert.ToInt32(action.Parameters["option_index"]))))
                : throw new ProtocolException(
                    "protocol_desync",
                    $"Standalone reward projection advertised non-reward action '{action.Kind}'."),
            StringComparer.Ordinal);
    }

    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return _executors[actionId]();
    }
}

/// <summary>A combat room's reward flow, including generation, choices, and leaving.</summary>
internal sealed class RoomRewardDecisionState : ActiveRunState
{
    private readonly IReadOnlyDictionary<string, Func<Task<ActiveRunState>>> _executors;

    public RoomRewardDecisionState(
        DecisionFrame frame,
        Func<Task<ActiveRunState>> generate,
        Func<RoomRewardSelection, Task<ActiveRunState>> choose,
        Func<Task<ActiveRunState>> leave) : base(frame)
    {
        _executors = frame.LegalActions.ToDictionary(
            action => action.ActionId,
            action => action.Kind switch
            {
                "generate_room_rewards" => generate,
                "choose_room_reward" => () => choose(new(
                    Convert.ToInt32(action.Parameters["reward_index"]),
                    Convert.ToInt32(action.Parameters["option_index"]))),
                "leave_room_rewards" => leave,
                _ => throw new ProtocolException(
                    "protocol_desync",
                    $"Room reward projection advertised non-reward action '{action.Kind}'.")
            },
            StringComparer.Ordinal);
    }

    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        return _executors[actionId]();
    }
}

/// <summary>The one legal transition between acts.</summary>
internal sealed class ActTransitionDecisionState(
    DecisionFrame frame,
    Func<Task<ActiveRunState>> advance) : ActiveRunState(frame)
{
    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        LegalAction action = RequireAction(actionId);
        if (action.Kind != "advance_act")
            throw new ProtocolException(
                "protocol_desync",
                $"Act transition projection advertised non-transition action '{action.Kind}'.");
        return advance();
    }
}

/// <summary>A completed run. It has no executor and cannot mutate native state.</summary>
internal sealed class TerminalRunState(DecisionFrame frame) : ActiveRunState(frame)
{
    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        _ = RequireAction(actionId);
        throw new UnreachableException();
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
        if (frame.Terminated)
            return new TerminalRunState(frame);
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
        if (capture.Event is not null)
            return new EventDecisionState(frame, ChooseEventAsync, LeaveEventAsync);
        if (capture.Reward is RewardDecisionKind.Standalone)
            return new StandaloneRewardDecisionState(frame, ChooseStandaloneRewardAsync);
        if (capture.Reward is RewardDecisionKind.Room)
            return new RoomRewardDecisionState(
                frame,
                GenerateRoomRewardsAsync,
                ChooseRoomRewardAsync,
                LeaveRoomRewardsAsync);
        if (capture.ActTransition)
            return new ActTransitionDecisionState(frame, AdvanceActAsync);
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

    private async Task<ActiveRunState> ChooseEventAsync(EventSelection selection) =>
        Create(await adapter.ChooseEventAsync(selection).ConfigureAwait(false));

    private async Task<ActiveRunState> LeaveEventAsync() =>
        Create(await adapter.LeaveEventAsync().ConfigureAwait(false));

    private async Task<ActiveRunState> ChooseStandaloneRewardAsync(StandaloneRewardSelection selection) =>
        Create(await adapter.ChooseStandaloneRewardAsync(selection).ConfigureAwait(false));

    private async Task<ActiveRunState> GenerateRoomRewardsAsync() =>
        Create(await adapter.GenerateRoomRewardsAsync().ConfigureAwait(false));

    private async Task<ActiveRunState> ChooseRoomRewardAsync(RoomRewardSelection selection) =>
        Create(await adapter.ChooseRoomRewardAsync(selection).ConfigureAwait(false));

    private async Task<ActiveRunState> LeaveRoomRewardsAsync() =>
        Create(await adapter.LeaveRoomRewardsAsync().ConfigureAwait(false));

    private async Task<ActiveRunState> AdvanceActAsync() =>
        Create(await adapter.AdvanceActAsync().ConfigureAwait(false));

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
