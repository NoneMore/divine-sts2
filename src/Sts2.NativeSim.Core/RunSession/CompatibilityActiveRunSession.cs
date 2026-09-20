using Sts2.NativeSim.Protocol;
using Sts2.NativeSim.Core.RunSession.States;

namespace Sts2.NativeSim.Core.RunSession;

/// <summary>
/// Temporary port implemented by the legacy room/combat state machine. It is deliberately private
/// to the RunSession module so no new caller can depend on capture or execution by room kind.
/// </summary>
internal interface IRunSessionCompatibilityAdapter
{
    CompatibilityCapture Reset(ResetRequest request);
    CompatibilityCapture ResetMap(ResetRequest request);
    CompatibilityCapture ResetReward(ResetRequest request);
    CompatibilityCapture ResetItemReward(ItemRewardResetRequest request);
    Task<CompatibilityCapture> ResetCustomRewardAsync(CustomRewardResetRequest request);
    CompatibilityCapture ResetRest(ResetRequest request);
    Task<CompatibilityCapture> ResetEventAsync(EventResetRequest request);
    Task<CompatibilityCapture> ApplyAsync(string actionId);
    Task<CompatibilityCapture> EnterMapPointAsync(MapPointSelection selection);
    Task<CompatibilityCapture> ChooseRestAsync(RestSelection selection);
    Task<CompatibilityCapture> OpenTreasureAsync();
    Task<CompatibilityCapture> ChooseTreasureAsync(TreasureSelection selection);
    Task<CompatibilityCapture> BuyShopEntryAsync(ShopSelection selection);
    Task<CompatibilityCapture> LeaveSimpleRoomAsync(SimpleRoomKind room);
    Task<CompatibilityCapture> ChooseEventAsync(EventSelection selection);
    Task<CompatibilityCapture> LeaveEventAsync();
    Task<CompatibilityCapture> ChooseStandaloneRewardAsync(StandaloneRewardSelection selection);
    Task<CompatibilityCapture> GenerateRoomRewardsAsync();
    Task<CompatibilityCapture> ChooseRoomRewardAsync(RoomRewardSelection selection);
    Task<CompatibilityCapture> LeaveRoomRewardsAsync();
    Task<CompatibilityCapture> AdvanceActAsync();
    Task<CompatibilityCapture> ResumeCardSelectAsync(PromptResumeToken parent, CardSelection selection);
    Task<CompatibilityCapture> ResumeRewardAsync(PromptResumeToken parent, RewardSelection selection);
    object CaptureCheckpoint();
    Task<CompatibilityCapture> RestoreAsync(object checkpoint);
}

internal sealed record CompatibilityCapture(
    DecisionFrame Frame,
    CompatibilityRestore? Restore = null,
    PromptResumeToken? PromptParent = null,
    IReadOnlyDictionary<string, MapPointSelection>? MapActions = null,
    SimpleRoomKind? SimpleRoom = null,
    EventDecisionMetadata? Event = null,
    RewardDecisionKind? Reward = null,
    bool ActTransition = false);

internal sealed record CompatibilityRestore(
    string Kind,
    int ReplayedActions,
    bool? ResidentPrefixHit = null);

/// <summary>
/// Serial compatibility implementation of the active-run interface. Its action table is built
/// from the same frame it exposes, so validation always precedes native mutation.
/// </summary>
internal sealed class CompatibilityActiveRunSession : IActiveRunSession
{
    private const string PoisonedMessage =
        "Worker state is corrupted and must be reconstructed. Discard and replace this worker.";

    private readonly IRunSessionCompatibilityAdapter _adapter;
    private readonly ActiveRunStateFactory _states;
    private readonly SemaphoreSlim _serial = new(1, 1);
    private ActiveRunState _active;
    private bool _poisoned;

    public CompatibilityActiveRunSession(
        IRunSessionCompatibilityAdapter adapter,
        CompatibilityCapture initial)
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
                    CompatibilityCapture restored = await _adapter.RestoreAsync(checkpoint).ConfigureAwait(false);
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

    internal async Task<CompatibilityCapture> RestoreAsync(object checkpoint)
    {
        await _serial.WaitAsync().ConfigureAwait(false);
        try
        {
            ThrowIfPoisoned();
            try
            {
                CompatibilityCapture restored = await _adapter.RestoreAsync(checkpoint).ConfigureAwait(false);
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
