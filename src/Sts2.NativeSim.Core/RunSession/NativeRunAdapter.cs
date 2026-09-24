using System.Text.Json;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.RunSession;

/// <summary>The shipped-game implementation of the semantic run command/query port.</summary>
internal sealed class NativeRunAdapter : INativeRunAdapter
{
    private readonly PersistentNativeCombatEnvironment _environment;

    public NativeRunAdapter(PersistentNativeCombatEnvironment environment) => _environment = environment;

    public NativeDecisionCapture ResetCombat(ResetRequest request) => Capture(_environment.Reset(request));
    public NativeDecisionCapture ResetRun(ResetRequest request) => Capture(_environment.RunReset(request));
    public NativeDecisionCapture ResetMap(ResetRequest request) => Capture(_environment.MapReset(request));
    public NativeDecisionCapture ResetReward(ResetRequest request) => Capture(_environment.RewardReset(request));
    public NativeDecisionCapture ResetItemReward(ItemRewardResetRequest request) =>
        Capture(_environment.ItemRewardReset(request));
    public async Task<NativeDecisionCapture> ResetCustomRewardAsync(CustomRewardResetRequest request) =>
        Capture(await _environment.CustomRewardResetAsync(request).ConfigureAwait(false));
    public NativeDecisionCapture ResetRest(ResetRequest request) => Capture(_environment.RestReset(request));
    public async Task<NativeDecisionCapture> ResetEventAsync(EventResetRequest request) =>
        Capture(await _environment.EventResetAsync(request).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ApplyAsync(string actionId) =>
        Capture(await _environment.StepAsync(actionId).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> EnterMapPointAsync(MapPointSelection selection) =>
        Capture(await _environment.EnterMapPointAsync(selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ChooseRestAsync(RestSelection selection) =>
        Capture(await _environment.ChooseRestOptionAsync(selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> OpenTreasureAsync() =>
        Capture(await _environment.OpenTreasureRoomAsync().ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ChooseTreasureAsync(TreasureSelection selection) =>
        Capture(await _environment.ChooseTreasureRelicAsync(selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> BuyShopEntryAsync(ShopSelection selection) =>
        Capture(await _environment.BuyShopEntryAsync(selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> LeaveSimpleRoomAsync(SimpleRoomKind room) =>
        Capture(await _environment.LeaveSimpleRoomAsync(room).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ChooseEventAsync(EventSelection selection) =>
        Capture(await _environment.ChooseEventOptionAsync(selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> LeaveEventAsync() =>
        Capture(await _environment.LeaveEventAsync().ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ChooseStandaloneRewardAsync(StandaloneRewardSelection selection) =>
        Capture(await _environment.ChooseStandaloneRewardAsync(selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> GenerateRoomRewardsAsync() =>
        Capture(await _environment.GenerateActiveRoomRewardsAsync().ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ChooseRoomRewardAsync(RoomRewardSelection selection) =>
        Capture(await _environment.ChooseActiveRoomRewardAsync(selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> LeaveRoomRewardsAsync() =>
        Capture(await _environment.LeaveActiveRoomRewardsAsync().ConfigureAwait(false));
    public async Task<NativeDecisionCapture> AdvanceActAsync() =>
        Capture(await _environment.AdvanceActiveActAsync().ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ResumeCardSelectAsync(
        PromptResumeToken parent,
        CardSelection selection) =>
        Capture(await _environment.ResumeCardSelectAsync(parent, selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ResumeOptionPickAsync(
        PromptResumeToken parent,
        OptionSelection selection) =>
        Capture(await _environment.ResumeOptionPickAsync(parent, selection).ConfigureAwait(false));
    public async Task<NativeDecisionCapture> ResumeRewardAsync(
        PromptResumeToken parent,
        RewardSelection selection) =>
        Capture(await _environment.ResumeRewardAsync(parent, selection).ConfigureAwait(false));
    public object CaptureCheckpoint() => _environment.Fork();
    public async Task<NativeDecisionCapture> RestoreAsync(object checkpoint) =>
        Capture(
            await _environment.RestoreAsync((string)checkpoint).ConfigureAwait(false),
            includeRestore: true);

    private NativeDecisionCapture Capture(EnvironmentResult result, bool includeRestore = false)
    {
        DecisionFrame frame = new(
            result.Observation,
            result.LegalActions,
            result.Terminated,
            result.Victory,
            _environment.TransitionKernelProjection(),
            result.ScoringFeatures);
        string projectedHash = NativeRunCoordinator.ComputeStateHash(frame);
        if (!StringComparer.Ordinal.Equals(projectedHash, result.StateHash))
            throw new ProtocolException(
                "protocol_desync",
                $"The compatibility frame projected hash {projectedHash}, but the legacy state reported {result.StateHash}.");
        return new(
            frame,
            includeRestore ? RestoreProjection(result.Transition) : null,
            _environment.ActivePromptParent(),
            _environment.HasActiveMapDecision ? MapActions(frame.LegalActions) : null,
            SimpleRoom(frame.LegalActions),
            Event: EventDecision(frame.LegalActions),
            Reward: _environment.ActiveRewardDecision.ForActions(frame.LegalActions),
            ActTransition: _environment.HasActiveActTransition);
    }

    private EventDecisionMetadata? EventDecision(IReadOnlyList<LegalAction> actions)
        => EventDecisionMetadata.ForActions(_environment.ActiveEventDecision, actions);

    private SimpleRoomKind? SimpleRoom(IReadOnlyList<LegalAction> actions)
    {
        SimpleRoomKind? room = _environment.ActiveSimpleRoom;
        if (room is null) return null;
        return actions.Count == 0 || actions.All(action => room.Value.Owns(action.Kind)) ? room : null;
    }

    private static IReadOnlyDictionary<string, MapPointSelection> MapActions(
        IReadOnlyList<LegalAction> actions)
    {
        Dictionary<string, MapPointSelection> result = new(StringComparer.Ordinal);
        foreach (LegalAction action in actions)
            result.Add(action.ActionId, MapPointSelection.FromAction(action));
        return result;
    }

    private static NativeRestore RestoreProjection(object? transition)
    {
        JsonElement value = JsonSerializer.SerializeToElement(transition);
        return new(
            value.GetProperty("kind").GetString()!,
            value.GetProperty("replayed_actions").GetInt32(),
            value.TryGetProperty("resident_prefix_hit", out JsonElement resident)
                ? resident.GetBoolean()
                : null,
            // Only a profiled restore carries one, so a worker that was not asked to time itself
            // reports no profile rather than a profile of zeroes.
            value.TryGetProperty("profile", out JsonElement profile) && profile.ValueKind == JsonValueKind.Object
                ? profile.Deserialize<RestoreProfile>()
                : null);
    }
}
