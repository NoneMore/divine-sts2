using Sts2.NativeSim.Protocol;
using Sts2.NativeSim.Core.RunSession.States;

namespace Sts2.NativeSim.Core.RunSession;

/// <summary>
/// Semantic command/query port implemented by the shipped-game adapter and scripted test adapter.
/// Reflection objects and room dispatch never cross this boundary.
/// </summary>
internal interface INativeRunAdapter
{
    NativeDecisionCapture ResetCombat(ResetRequest request);
    NativeDecisionCapture ResetRun(ResetRequest request);
    NativeDecisionCapture ResetMap(ResetRequest request);
    NativeDecisionCapture ResetReward(ResetRequest request);
    NativeDecisionCapture ResetItemReward(ItemRewardResetRequest request);
    Task<NativeDecisionCapture> ResetCustomRewardAsync(CustomRewardResetRequest request);
    NativeDecisionCapture ResetRest(ResetRequest request);
    Task<NativeDecisionCapture> ResetEventAsync(EventResetRequest request);
    Task<NativeDecisionCapture> ApplyAsync(string actionId);
    Task<NativeDecisionCapture> EnterMapPointAsync(MapPointSelection selection);
    Task<NativeDecisionCapture> ChooseRestAsync(RestSelection selection);
    Task<NativeDecisionCapture> OpenTreasureAsync();
    Task<NativeDecisionCapture> ChooseTreasureAsync(TreasureSelection selection);
    Task<NativeDecisionCapture> BuyShopEntryAsync(ShopSelection selection);
    Task<NativeDecisionCapture> LeaveSimpleRoomAsync(SimpleRoomKind room);
    Task<NativeDecisionCapture> ChooseEventAsync(EventSelection selection);
    Task<NativeDecisionCapture> LeaveEventAsync();
    Task<NativeDecisionCapture> ChooseStandaloneRewardAsync(StandaloneRewardSelection selection);
    Task<NativeDecisionCapture> GenerateRoomRewardsAsync();
    Task<NativeDecisionCapture> ChooseRoomRewardAsync(RoomRewardSelection selection);
    Task<NativeDecisionCapture> LeaveRoomRewardsAsync();
    Task<NativeDecisionCapture> AdvanceActAsync();
    Task<NativeDecisionCapture> ResumeCardSelectAsync(PromptResumeToken parent, CardSelection selection);
    Task<NativeDecisionCapture> ResumeOptionPickAsync(PromptResumeToken parent, OptionSelection selection);
    Task<NativeDecisionCapture> ResumeRewardAsync(PromptResumeToken parent, RewardSelection selection);
    object CaptureCheckpoint();
    Task<NativeDecisionCapture> RestoreAsync(object checkpoint);
}

internal sealed record NativeDecisionCapture(
    DecisionFrame Frame,
    NativeRestore? Restore = null,
    PromptResumeToken? PromptParent = null,
    IReadOnlyDictionary<string, MapPointSelection>? MapActions = null,
    SimpleRoomKind? SimpleRoom = null,
    EventDecisionMetadata? Event = null,
    RewardDecisionKind? Reward = null,
    bool ActTransition = false);

internal sealed record NativeRestore(
    string Kind,
    int ReplayedActions,
    bool? ResidentPrefixHit = null,
    RestoreProfile? Profile = null);

/// <summary>
/// Serial implementation of the active-run interface. Its action table is built
/// from the same frame it exposes, so validation always precedes native mutation.
/// </summary>
internal sealed class ActiveRunSession : IActiveRunSession
{
    private const string PoisonedMessage =
        "Worker state is corrupted and must be reconstructed. Discard and replace this worker.";

    private readonly INativeRunAdapter _adapter;
    private readonly ActiveRunStateFactory _states;
    private readonly SemaphoreSlim _serial = new(1, 1);
    private ActiveRunState _active;
    private bool _poisoned;

    public ActiveRunSession(
        INativeRunAdapter adapter,
        NativeDecisionCapture initial)
    {
        _adapter = adapter;
        _states = new(adapter);
        _active = _states.Create(initial);
    }

    public DecisionFrame Current
    {
        get
        {
            _serial.Wait();
            try
            {
                ThrowIfPoisoned();
                return _active.Frame;
            }
            finally
            {
                _serial.Release();
            }
        }
    }

    public async Task ApplyAsync(string actionId)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            ThrowIfPoisoned();
            object checkpoint = _adapter.CaptureCheckpoint();
            try
            {
                _active = await _active.ApplyAsync(actionId).ConfigureAwait(false);
            }
            catch
            {
                try
                {
                    NativeDecisionCapture restored = await _adapter.RestoreAsync(checkpoint).ConfigureAwait(false);
                    _active = _states.Create(restored);
                }
                catch
                {
                    _poisoned = true;
                    throw Poisoned();
                }
                throw;
            }
        }
        finally
        {
            _serial.Release();
        }
    }

    internal async Task<NativeDecisionCapture> RestoreAsync(object checkpoint)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            ThrowIfPoisoned();
            try
            {
                NativeDecisionCapture restored = await _adapter.RestoreAsync(checkpoint).ConfigureAwait(false);
                _active = _states.Create(restored);
                return restored;
            }
            catch
            {
                _poisoned = true;
                throw;
            }
        }
        finally
        {
            _serial.Release();
        }
    }

    private void ThrowIfPoisoned()
    {
        if (_poisoned) throw Poisoned();
    }

    private static ProtocolException Poisoned() => new("worker_poisoned", PoisonedMessage);
}
