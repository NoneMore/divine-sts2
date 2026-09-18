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
internal sealed class RunContinuation<T>(Func<T, Task<ActiveRunState>> resume)
{
    public Task<ActiveRunState> ResumeAsync(T value) => resume(value);
}

internal sealed record CardSelection(string ActionId, IReadOnlyList<string> OptionIds);

internal sealed record RewardSelection(
    string ActionId,
    int? RewardIndex,
    int? ChildIndex,
    int? OptionIndex);

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

/// <summary>The sole active state while the shipped game is waiting for cards.</summary>
internal sealed class CardSelectPromptState(
    DecisionFrame frame,
    RunContinuation<CardSelection> continuation) : ActiveRunState(frame)
{
    public override Task<ActiveRunState> ApplyAsync(string actionId)
    {
        LegalAction action = RequireAction(actionId);
        if (!StringComparer.Ordinal.Equals(action.Kind, "choose_cards"))
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
        if (action.Kind is not ("choose_custom_reward" or "skip_custom_rewards"))
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
        if (IsCardPrompt(frame))
            return new CardSelectPromptState(frame, new(selection => ContinueAsync(selection.ActionId)));
        if (IsRewardPrompt(frame))
            return new RewardPromptState(frame, new(selection => ContinueAsync(selection.ActionId)));
        return new NativeDecisionState(frame, ContinueAsync);
    }

    private async Task<ActiveRunState> ContinueAsync(string actionId) =>
        Create(await adapter.ApplyAsync(actionId).ConfigureAwait(false));

    private static bool IsCardPrompt(DecisionFrame frame) =>
        frame.LegalActions.Count > 0
        && frame.LegalActions.All(action => action.Kind == "choose_cards");

    private static bool IsRewardPrompt(DecisionFrame frame) =>
        frame.LegalActions.Count > 0
        && frame.LegalActions.All(action => action.Kind is "choose_custom_reward" or "skip_custom_rewards");
}
