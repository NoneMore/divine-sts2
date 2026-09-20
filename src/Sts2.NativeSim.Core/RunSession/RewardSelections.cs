using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.RunSession;

internal enum RewardDecisionKind
{
    Standalone,
    Room
}

internal static class RewardDecisionKindExtensions
{
    public static RewardDecisionKind? ForActions(
        this RewardDecisionKind? reward,
        IReadOnlyList<LegalAction> actions)
    {
        if (reward is null) return null;
        return actions.Count == 0 || actions.All(action => reward.Value.Owns(action.Kind))
            ? reward
            : null;
    }

    private static bool Owns(this RewardDecisionKind reward, string actionKind) => reward switch
    {
        RewardDecisionKind.Standalone => actionKind == "choose_reward",
        RewardDecisionKind.Room => actionKind is
            "generate_room_rewards" or "choose_room_reward" or "leave_room_rewards",
        _ => throw new ArgumentOutOfRangeException(nameof(reward), reward, null)
    };
}

internal sealed record StandaloneRewardSelection(int OptionIndex);

internal sealed record RoomRewardSelection(int RewardIndex, int OptionIndex);
