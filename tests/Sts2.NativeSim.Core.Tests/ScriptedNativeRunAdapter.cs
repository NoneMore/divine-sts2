using System.Text.Json;
using Sts2.NativeSim.Core;
using Sts2.NativeSim.Core.RunSession;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.Tests;

internal sealed class ScriptedNativeRunAdapter : IRunSessionCompatibilityAdapter
{
    private readonly Dictionary<string, ScriptedFrame> _frames = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Frame, string Action), string> _transitions = new();
    private readonly Dictionary<(string Frame, int Col, int Row, string PointType), string> _mapTransitions = new();
    private readonly Dictionary<(string Frame, string OptionId), string> _restTransitions = new();
    private readonly Dictionary<string, string> _openTreasureTransitions = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Frame, int? OptionIndex), string> _treasureTransitions = new();
    private readonly Dictionary<(string Frame, int EntryIndex), string> _shopTransitions = new();
    private readonly Dictionary<(string Frame, SimpleRoomKind Room), string> _leaveSimpleRoomTransitions = new();
    private readonly Dictionary<(string Frame, int OptionIndex), string> _eventTransitions = new();
    private readonly Dictionary<string, string> _leaveEventTransitions = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Frame, int OptionIndex), string> _standaloneRewardTransitions = new();
    private readonly Dictionary<string, string> _generateRoomRewardTransitions = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Frame, int RewardIndex, int OptionIndex), string> _roomRewardTransitions = new();
    private readonly Dictionary<string, string> _leaveRoomRewardTransitions = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _advanceActTransitions = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Frame, string Selection), string> _cardTransitions = new();
    private readonly Dictionary<(string Frame, int? RewardIndex, int? ChildIndex, int? OptionIndex), ScriptedRewardTransition> _rewardTransitions = new();
    private readonly Stack<object> _suspendedRewardParents = new();
    private readonly Dictionary<(string Frame, string Action), string> _errorsAfterMutation = new();
    private readonly Dictionary<string, ScriptedCheckpoint> _branches = new(StringComparer.Ordinal);
    private readonly string _resetFrame;
    private string _currentFrame;
    private object _promptMarker = new();
    private int _checkpointOrdinal;

    public ScriptedNativeRunAdapter(string resetFrame)
    {
        _resetFrame = resetFrame;
        _currentFrame = resetFrame;
    }

    public int MutationCount { get; private set; }
    public int GenericApplyCount { get; private set; }
    public TimeSpan ApplyDelay { get; init; }
    public List<CardSelection> CardSelections { get; } = [];
    public List<RewardSelection> RewardSelections { get; } = [];
    public List<PromptResumeToken> CardResumeTokens { get; } = [];
    public List<PromptResumeToken> RewardResumeTokens { get; } = [];
    public List<(int Col, int Row)> EnteredMapPoints { get; } = [];
    public List<RestSelection> RestSelections { get; } = [];
    public int OpenTreasureCount { get; private set; }
    public List<TreasureSelection> TreasureSelections { get; } = [];
    public List<ShopSelection> ShopSelections { get; } = [];
    public List<SimpleRoomKind> LeftSimpleRooms { get; } = [];
    public List<EventSelection> EventSelections { get; } = [];
    public int LeaveEventCount { get; private set; }
    public List<StandaloneRewardSelection> StandaloneRewardSelections { get; } = [];
    public int GenerateRoomRewardsCount { get; private set; }
    public List<RoomRewardSelection> RoomRewardSelections { get; } = [];
    public int LeaveRoomRewardsCount { get; private set; }
    public int AdvanceActCount { get; private set; }
    public int RewardResetCount { get; private set; }
    public int ItemRewardResetCount { get; private set; }
    public int CustomRewardResetCount { get; private set; }

    public ScriptedNativeRunAdapter Frame(string name, string observation, params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(document.RootElement.Clone(), Kernel(name), actions, false, false));
        return this;
    }

    public ScriptedNativeRunAdapter EventFrame(string name, string observation, params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(
            document.RootElement.Clone(),
            Kernel(name),
            actions,
            false,
            false,
            Event: new(name)));
        return this;
    }

    public ScriptedNativeRunAdapter MapFrame(string name, string observation, params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(document.RootElement.Clone(), Kernel(name), actions, false, false, IsMap: true));
        return this;
    }

    public ScriptedNativeRunAdapter RestFrame(string name, string observation, params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(document.RootElement.Clone(), Kernel(name), actions, false, false, SimpleRoom: SimpleRoomKind.Rest));
        return this;
    }

    public ScriptedNativeRunAdapter TreasureFrame(string name, string observation, params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(document.RootElement.Clone(), Kernel(name), actions, false, false, SimpleRoom: SimpleRoomKind.Treasure));
        return this;
    }

    public ScriptedNativeRunAdapter ShopFrame(string name, string observation, params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(document.RootElement.Clone(), Kernel(name), actions, false, false, SimpleRoom: SimpleRoomKind.Shop));
        return this;
    }

    public ScriptedNativeRunAdapter StandaloneRewardFrame(
        string name,
        string observation,
        params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(
            document.RootElement.Clone(), Kernel(name), actions, false, false,
            Reward: RewardDecisionKind.Standalone));
        return this;
    }

    public ScriptedNativeRunAdapter RoomRewardFrame(
        string name,
        string observation,
        params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(
            document.RootElement.Clone(), Kernel(name), actions, false, false,
            Reward: RewardDecisionKind.Room));
        return this;
    }

    public ScriptedNativeRunAdapter ActTransitionFrame(
        string name,
        string observation,
        params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(
            document.RootElement.Clone(), Kernel(name), actions, false, false,
            ActTransition: true));
        return this;
    }

    public ScriptedNativeRunAdapter TerminalFrame(string name, string observation, bool victory)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(document.RootElement.Clone(), Kernel(name), [], true, victory));
        return this;
    }

    public ScriptedNativeRunAdapter Transition(string from, string actionId, string to)
    {
        _transitions.Add((from, actionId), to);
        return this;
    }

    public ScriptedNativeRunAdapter EnterMapPoint(
        string from,
        int col,
        int row,
        string pointType,
        string to)
    {
        _mapTransitions.Add((from, col, row, pointType), to);
        return this;
    }

    public ScriptedNativeRunAdapter RestTransition(string from, RestSelection selection, string to)
    {
        _restTransitions.Add((from, selection.OptionId), to);
        return this;
    }

    public ScriptedNativeRunAdapter OpenTreasure(string from, string to)
    {
        _openTreasureTransitions.Add(from, to);
        return this;
    }

    public ScriptedNativeRunAdapter TreasureTransition(string from, TreasureSelection selection, string to)
    {
        _treasureTransitions.Add((from, selection.OptionIndex), to);
        return this;
    }

    public ScriptedNativeRunAdapter ShopTransition(string from, ShopSelection selection, string to)
    {
        _shopTransitions.Add((from, selection.EntryIndex), to);
        return this;
    }

    public ScriptedNativeRunAdapter LeaveSimpleRoom(string from, SimpleRoomKind room, string to)
    {
        _leaveSimpleRoomTransitions.Add((from, room), to);
        return this;
    }

    public ScriptedNativeRunAdapter EventTransition(string from, EventSelection selection, string to)
    {
        _eventTransitions.Add((from, selection.OptionIndex), to);
        return this;
    }

    public ScriptedNativeRunAdapter LeaveEvent(string from, string to)
    {
        _leaveEventTransitions.Add(from, to);
        return this;
    }

    public ScriptedNativeRunAdapter ChooseStandaloneReward(
        string from,
        StandaloneRewardSelection selection,
        string to)
    {
        _standaloneRewardTransitions.Add((from, selection.OptionIndex), to);
        return this;
    }

    public ScriptedNativeRunAdapter GenerateRoomRewards(string from, string to)
    {
        _generateRoomRewardTransitions.Add(from, to);
        return this;
    }

    public ScriptedNativeRunAdapter ChooseRoomReward(
        string from,
        RoomRewardSelection selection,
        string to)
    {
        _roomRewardTransitions.Add((from, selection.RewardIndex, selection.OptionIndex), to);
        return this;
    }

    public ScriptedNativeRunAdapter LeaveRoomRewards(string from, string to)
    {
        _leaveRoomRewardTransitions.Add(from, to);
        return this;
    }

    public ScriptedNativeRunAdapter AdvanceAct(string from, string to)
    {
        _advanceActTransitions.Add(from, to);
        return this;
    }

    public ScriptedNativeRunAdapter CardPrompt(
        string name,
        string observation,
        string choiceId,
        IReadOnlyList<string> optionIds,
        int minSelect,
        int maxSelect)
    {
        List<LegalAction> actions = [];
        foreach (string[] selection in EnumerateSelections(optionIds, minSelect, maxSelect))
        {
            string suffix = selection.Length == 0 ? "skip" : string.Join('+', selection.Select(Uri.EscapeDataString));
            LegalAction action = new(
                $"choose_cards:{choiceId}:{suffix}",
                "choose_cards",
                new Dictionary<string, object?>
                {
                    ["choice_id"] = choiceId,
                    ["option_ids"] = selection
                });
            actions.Add(action);
        }
        return Frame(name, observation, actions.ToArray());
    }

    public ScriptedNativeRunAdapter ResumeCardPrompt(
        string prompt,
        IReadOnlyList<string> selectedOptionIds,
        string to)
    {
        _cardTransitions.Add((prompt, SelectionKey(selectedOptionIds)), to);
        return this;
    }

    public ScriptedNativeRunAdapter RewardPrompt(
        string name,
        string observation,
        IReadOnlyList<int> rewardIndices)
    {
        List<LegalAction> actions = [];
        foreach (int rewardIndex in rewardIndices)
        {
            LegalAction action = new(
                $"choose_custom_reward:{rewardIndex}:-1:0:gold:none",
                "choose_custom_reward",
                new Dictionary<string, object?>
                {
                    ["reward_index"] = rewardIndex,
                    ["child_index"] = -1,
                    ["option_index"] = 0,
                    ["reward_kind"] = "gold",
                    ["model_id"] = null
                });
            actions.Add(action);
        }
        LegalAction skip = new(
            "skip_custom_rewards",
            "skip_custom_rewards",
            new Dictionary<string, object?>());
        actions.Add(skip);
        return Frame(name, observation, actions.ToArray());
    }

    public ScriptedNativeRunAdapter ResumeRewardPrompt(string prompt, int rewardIndex, string to)
    {
        _rewardTransitions.Add((prompt, rewardIndex, -1, 0), new(to, ResumeParent: false));
        return this;
    }

    public ScriptedNativeRunAdapter ResumeRewardParent(string prompt, int rewardIndex, string to)
    {
        _rewardTransitions.Add((prompt, rewardIndex, -1, 0), new(to, ResumeParent: true));
        return this;
    }

    public ScriptedNativeRunAdapter SkipRewardPrompt(string prompt, string to)
    {
        _rewardTransitions.Add((prompt, null, null, null), new(to, ResumeParent: false));
        return this;
    }

    public ScriptedNativeRunAdapter ErrorAfterMutation(
        string from,
        string actionId,
        string code = "scripted_native_error")
    {
        _errorsAfterMutation.Add((from, actionId), code);
        return this;
    }

    public CompatibilityCapture Reset(ResetRequest request)
    {
        ValidateResetMode(request, ResetModes.Run);
        return Reset();
    }

    public CompatibilityCapture ResetMap(ResetRequest request)
    {
        ValidateResetMode(request, ResetModes.Combat);
        return Reset();
    }

    public CompatibilityCapture ResetReward(ResetRequest request)
    {
        ValidateResetMode(request, ResetModes.Combat);
        RewardResetCount++;
        return Reset();
    }

    public CompatibilityCapture ResetItemReward(ItemRewardResetRequest request)
    {
        ValidateResetMode(request.State, ResetModes.Combat);
        ItemRewardResetCount++;
        return Reset();
    }

    public Task<CompatibilityCapture> ResetCustomRewardAsync(CustomRewardResetRequest request)
    {
        ValidateResetMode(request.State, ResetModes.Combat);
        CustomRewardResetCount++;
        return Task.FromResult(Reset());
    }

    public CompatibilityCapture ResetRest(ResetRequest request)
    {
        ValidateResetMode(request, ResetModes.Combat);
        return Reset();
    }

    public Task<CompatibilityCapture> ResetEventAsync(EventResetRequest request)
    {
        ValidateResetMode(request.State, ResetModes.Combat);
        return Task.FromResult(Reset());
    }

    private CompatibilityCapture Reset()
    {
        _currentFrame = _resetFrame;
        _promptMarker = new();
        _suspendedRewardParents.Clear();
        return Capture();
    }

    private static void ValidateResetMode(ResetRequest request, string expected)
    {
        if (request.ResetMode is not null && !StringComparer.Ordinal.Equals(request.ResetMode, expected))
            throw new ProtocolException(
                "invalid_reset",
                $"A '{expected}' reset was asked for with reset_mode '{request.ResetMode}'.");
    }

    public CompatibilityCapture Capture()
    {
        ScriptedFrame frame = _frames[_currentFrame];
        return Result(frame);
    }

    public async Task<CompatibilityCapture> ApplyAsync(string actionId)
    {
        GenericApplyCount++;
        string nextFrame = _transitions[(_currentFrame, actionId)];
        return await ApplyTransitionAsync(actionId, nextFrame);
    }

    public Task<CompatibilityCapture> EnterMapPointAsync(MapPointSelection selection)
    {
        EnteredMapPoints.Add((selection.Col, selection.Row));
        string nextFrame = _mapTransitions[
            (_currentFrame, selection.Col, selection.Row, selection.PointType)];
        return ApplyTransitionAsync(
            _frames[_currentFrame].Actions.Single(action =>
                Convert.ToInt32(action.Parameters["col"]) == selection.Col
                && Convert.ToInt32(action.Parameters["row"]) == selection.Row).ActionId,
            nextFrame);
    }

    public Task<CompatibilityCapture> ChooseRestAsync(RestSelection selection)
    {
        RestSelections.Add(selection);
        string nextFrame = _restTransitions[(_currentFrame, selection.OptionId)];
        return ApplyTransitionAsync(
            _frames[_currentFrame].Actions.Single(action =>
                action.Kind == "choose_rest"
                && StringComparer.Ordinal.Equals(Convert.ToString(action.Parameters["option_id"]), selection.OptionId)).ActionId,
            nextFrame);
    }

    public Task<CompatibilityCapture> OpenTreasureAsync()
    {
        OpenTreasureCount++;
        return ApplyTransitionAsync("open_treasure", _openTreasureTransitions[_currentFrame]);
    }

    public Task<CompatibilityCapture> ChooseTreasureAsync(TreasureSelection selection)
    {
        TreasureSelections.Add(selection);
        string nextFrame = _treasureTransitions[(_currentFrame, selection.OptionIndex)];
        string actionId = selection.OptionIndex is { } index
            ? _frames[_currentFrame].Actions.Single(action =>
                action.Kind == "choose_treasure"
                && Convert.ToInt32(action.Parameters["option_index"]) == index).ActionId
            : "skip_treasure";
        return ApplyTransitionAsync(actionId, nextFrame);
    }

    public Task<CompatibilityCapture> BuyShopEntryAsync(ShopSelection selection)
    {
        ShopSelections.Add(selection);
        string nextFrame = _shopTransitions[(_currentFrame, selection.EntryIndex)];
        string actionId = _frames[_currentFrame].Actions.Single(action =>
            action.Kind == "buy_shop"
            && Convert.ToInt32(action.Parameters["entry_index"]) == selection.EntryIndex).ActionId;
        return ApplyTransitionAsync(actionId, nextFrame);
    }

    public Task<CompatibilityCapture> LeaveSimpleRoomAsync(SimpleRoomKind room)
    {
        LeftSimpleRooms.Add(room);
        string nextFrame = _leaveSimpleRoomTransitions[(_currentFrame, room)];
        return ApplyTransitionAsync($"leave_{room.ToString().ToLowerInvariant()}", nextFrame);
    }

    public Task<CompatibilityCapture> ChooseEventAsync(EventSelection selection)
    {
        EventSelections.Add(selection);
        string nextFrame = _eventTransitions[(_currentFrame, selection.OptionIndex)];
        string actionId = _frames[_currentFrame].Actions.Single(action =>
            action.Kind == "choose_event"
            && Convert.ToInt32(action.Parameters["option_index"]) == selection.OptionIndex).ActionId;
        return ApplyTransitionAsync(actionId, nextFrame);
    }

    public Task<CompatibilityCapture> LeaveEventAsync()
    {
        LeaveEventCount++;
        return ApplyTransitionAsync("leave_event", _leaveEventTransitions[_currentFrame]);
    }

    public Task<CompatibilityCapture> ChooseStandaloneRewardAsync(StandaloneRewardSelection selection)
    {
        StandaloneRewardSelections.Add(selection);
        string nextFrame = _standaloneRewardTransitions[(_currentFrame, selection.OptionIndex)];
        string actionId = _frames[_currentFrame].Actions.Single(action =>
            action.Kind == "choose_reward"
            && Convert.ToInt32(action.Parameters["option_index"]) == selection.OptionIndex).ActionId;
        return ApplyTransitionAsync(actionId, nextFrame);
    }

    public Task<CompatibilityCapture> GenerateRoomRewardsAsync()
    {
        GenerateRoomRewardsCount++;
        return ApplyTransitionAsync("generate_room_rewards", _generateRoomRewardTransitions[_currentFrame]);
    }

    public Task<CompatibilityCapture> ChooseRoomRewardAsync(RoomRewardSelection selection)
    {
        RoomRewardSelections.Add(selection);
        string nextFrame = _roomRewardTransitions[(_currentFrame, selection.RewardIndex, selection.OptionIndex)];
        string actionId = _frames[_currentFrame].Actions.Single(action =>
            action.Kind == "choose_room_reward"
            && Convert.ToInt32(action.Parameters["reward_index"]) == selection.RewardIndex
            && Convert.ToInt32(action.Parameters["option_index"]) == selection.OptionIndex).ActionId;
        return ApplyTransitionAsync(actionId, nextFrame);
    }

    public Task<CompatibilityCapture> LeaveRoomRewardsAsync()
    {
        LeaveRoomRewardsCount++;
        return ApplyTransitionAsync("leave_room_rewards", _leaveRoomRewardTransitions[_currentFrame]);
    }

    public Task<CompatibilityCapture> AdvanceActAsync()
    {
        AdvanceActCount++;
        return ApplyTransitionAsync("advance_act", _advanceActTransitions[_currentFrame]);
    }

    public Task<CompatibilityCapture> ResumeCardSelectAsync(
        PromptResumeToken parent,
        CardSelection selection)
    {
        ValidateParent(parent);
        CardResumeTokens.Add(parent);
        CardSelections.Add(selection);
        string nextFrame = _cardTransitions[(_currentFrame, SelectionKey(selection.OptionIds))];
        return ApplyTransitionAsync(selection.ActionId, nextFrame);
    }

    public Task<CompatibilityCapture> ResumeRewardAsync(
        PromptResumeToken parent,
        RewardSelection selection)
    {
        ValidateParent(parent);
        RewardResumeTokens.Add(parent);
        RewardSelections.Add(selection);
        ScriptedRewardTransition transition = _rewardTransitions[
            (_currentFrame, selection.RewardIndex, selection.ChildIndex, selection.OptionIndex)];
        object? nextParent = null;
        if (transition.ResumeParent)
        {
            nextParent = _suspendedRewardParents.Pop();
        }
        else if (IsRewardPrompt(_frames[transition.Frame]))
        {
            _suspendedRewardParents.Push(_promptMarker);
        }
        return ApplyTransitionAsync(selection.ActionId, transition.Frame, nextParent);
    }

    private async Task<CompatibilityCapture> ApplyTransitionAsync(
        string actionId,
        string nextFrame,
        object? nextPromptMarker = null)
    {
        if (ApplyDelay > TimeSpan.Zero) await Task.Delay(ApplyDelay);
        ScriptedFrame next = _frames[nextFrame];
        string previousFrame = _currentFrame;
        _currentFrame = nextFrame;
        _promptMarker = nextPromptMarker ?? new();
        CompatibilityCapture result = Result(next);
        MutationCount++;
        if (_errorsAfterMutation.TryGetValue((previousFrame, actionId), out string? code))
            throw new ProtocolException(code, "The scripted native adapter failed after mutation.");
        return result;
    }

    public object CaptureCheckpoint()
    {
        string checkpoint = $"checkpoint-{++_checkpointOrdinal}";
        _branches.Add(checkpoint, new(_currentFrame, _suspendedRewardParents.Count));
        return checkpoint;
    }

    public Task<CompatibilityCapture> RestoreAsync(object checkpoint)
    {
        ScriptedCheckpoint restored = _branches[(string)checkpoint];
        _currentFrame = restored.Frame;
        _promptMarker = new();
        _suspendedRewardParents.Clear();
        for (int index = 0; index < restored.SuspendedRewardDepth; index++)
            _suspendedRewardParents.Push(new());
        return Task.FromResult(Capture());
    }

    private CompatibilityCapture Result(ScriptedFrame frame)
    {
        bool prompt = frame.Actions.Count > 0 && frame.Actions.All(action =>
            action.Kind == "choose_cards"
            || action.Kind is "choose_custom_reward" or "skip_custom_rewards");
        return new(
            new(frame.Observation, frame.Actions, frame.Terminated, frame.Victory, frame.KernelProjection, null),
            PromptParent: prompt ? new(_promptMarker) : null,
            MapActions: frame.IsMap ? MapActions(frame.Actions) : null,
            SimpleRoom: prompt ? null : frame.SimpleRoom,
            Event: EventDecision(frame),
            Reward: frame.Reward.ForActions(frame.Actions),
            ActTransition: frame.ActTransition);
    }

    private static EventDecisionMetadata? EventDecision(ScriptedFrame frame) =>
        EventDecisionMetadata.ForActions(frame.Event, frame.Actions);

    private static IReadOnlyDictionary<string, MapPointSelection> MapActions(IReadOnlyList<LegalAction> actions) =>
        actions.ToDictionary(
            action => action.ActionId,
            MapPointSelection.FromAction,
            StringComparer.Ordinal);

    private static bool IsRewardPrompt(ScriptedFrame frame) =>
        frame.Actions.Count > 0
        && frame.Actions.All(action => action.Kind is "choose_custom_reward" or "skip_custom_rewards");

    private void ValidateParent(PromptResumeToken parent)
    {
        if (!ReferenceEquals(parent.Marker, _promptMarker))
            throw new ProtocolException("stale_continuation", "The scripted prompt parent is no longer active.");
    }

    private static object Kernel(string frame) => new
    {
        run_mode = true,
        run_stage = frame is "map" or "route" ? "map" : frame == "combat" ? "combat" : "event",
        map_mode = false,
        reward_mode = false,
        reward_kind = "card",
        reward_model_id = (string?)null,
        rest_mode = false,
        event_mode = frame is not ("map" or "route" or "combat"),
        event_id = (string?)null,
        custom_reward_mode = false,
        custom_rewards_linked = false,
        custom_reward_kinds = Array.Empty<string>()
    };

    private static IEnumerable<string[]> EnumerateSelections(
        IReadOnlyList<string> options,
        int minSelect,
        int maxSelect)
    {
        List<string[]> result = [];
        List<string> current = [];
        void Visit(int index)
        {
            if (current.Count >= minSelect && current.Count <= maxSelect) result.Add(current.ToArray());
            if (current.Count == maxSelect) return;
            for (int i = index; i < options.Count; i++)
            {
                current.Add(options[i]);
                Visit(i + 1);
                current.RemoveAt(current.Count - 1);
            }
        }
        Visit(0);
        return result;
    }

    private static string SelectionKey(IEnumerable<string> optionIds) => string.Join('\u001f', optionIds);

    private sealed record ScriptedFrame(
        JsonElement Observation,
        object KernelProjection,
        IReadOnlyList<LegalAction> Actions,
        bool Terminated,
        bool Victory,
        bool IsMap = false,
        SimpleRoomKind? SimpleRoom = null,
        EventDecisionMetadata? Event = null,
        RewardDecisionKind? Reward = null,
        bool ActTransition = false);

    private sealed record ScriptedRewardTransition(string Frame, bool ResumeParent);
    private sealed record ScriptedCheckpoint(string Frame, int SuspendedRewardDepth);
}
