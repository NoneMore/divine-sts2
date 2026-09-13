using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.TestSupport;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// Wraps the card selector the shipped AutoSlay installs so nested choices can be answered by the
/// protocol instead of being auto-picked at random.
///
/// The game consults <see cref="CardSelectCmd.Selector"/> before it pushes any card-selection
/// screen, so intercepting this one seam covers every nested card choice a Neow blessing opens
/// (New Leaf, Pomander, Precise Scissors, Precarious Shears, Hefty Tablet, Lead Paperweight, and
/// in-combat pile/hand selections such as Gambling Chip's discard). Card *reward* selection is left
/// with the wrapped selector so the existing reward-screen flow is unchanged.
/// </summary>
public sealed class BridgeCardSelector(ICardSelector inner) : ICardSelector
{
    private readonly ICardSelector _inner = inner;

    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        if (!FullAppBridgeServer.ProtocolNestedChoices)
        {
            return _inner.GetSelectedCards(options, minSelect, maxSelect);
        }
        return CoordinateAsync(options.ToList(), minSelect, maxSelect);
    }

    private static async Task<IEnumerable<CardModel>> CoordinateAsync(
        IReadOnlyList<CardModel> options,
        int minSelect,
        int maxSelect)
    {
        return await FullAppBridgeServer.CoordinateCardChoiceAsync(options, minSelect, maxSelect);
    }

    public CardRewardSelection GetSelectedCardReward(
        IReadOnlyList<CardCreationResult> options,
        IReadOnlyList<CardRewardAlternative> alternatives)
    {
        return _inner.GetSelectedCardReward(options, alternatives);
    }
}
