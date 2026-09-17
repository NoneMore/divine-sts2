using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.TestSupport;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// Wraps the card selector the shipped AutoSlay installs, so a flat card-set prompt becomes a
/// decision this bridge reports and a caller answers by identity instead of one the wrapped selector
/// answers at random.
///
/// The game consults <see cref="CardSelectCmd.Selector"/> before it pushes any card-selection screen,
/// which makes this the one seam every card choice the game routes that way arrives at — the removal,
/// upgrade, transform and choose-a-card prompts several of the act-1 Ancient's choices open, and the
/// selections a card effect opens inside a fight. Without it those prompts are resolved before any
/// bridge stage sees them, so a shipped run that reaches one cannot be driven by a caller at all.
///
/// Two things are deliberately left with the wrapped selector. A card *reward* draft, because the
/// rewards stage already reports that decision and a second stage claiming it would describe one
/// situation twice. And any prompt no client is connected for, because a run nobody is driving is
/// still a run: the shipped selector answers it the way it does without this bridge.
/// </summary>
internal sealed class BridgeCardSelector : ICardSelector
{
    private readonly ICardSelector _inner;

    public BridgeCardSelector(ICardSelector inner)
    {
        _inner = inner;
    }

    /// <summary>
    /// The offered cards as a decision for the coordinator, which selects one by the identity the
    /// action names.
    /// </summary>
    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        if (!FullAppBridgeServer.HasClient)
        {
            return _inner.GetSelectedCards(options, minSelect, maxSelect);
        }

        return FullAppBridgeServer.CoordinateCardChoiceAsync(options, minSelect, maxSelect);
    }

    /// <summary>A card reward draft, which the rewards stage's own decision reports.</summary>
    public CardRewardSelection GetSelectedCardReward(
        IReadOnlyList<CardCreationResult> options,
        IReadOnlyList<CardRewardAlternative> alternatives)
    {
        return _inner.GetSelectedCardReward(options, alternatives);
    }
}
