using MegaCrit.Sts2.Core.Models;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// One flat card-set prompt as the game asked for it: the cards still on offer, how many of them the
/// game expects to be chosen, and the cards already chosen for the prompt.
///
/// The game asks for a set of cards through two seams — the selector it consults first and the screen
/// it pushes when nothing answers for it — and both arrive at the snapshot as this one value, so the
/// stage is described once rather than twice. The range is the seam's own report: the selector is
/// handed the game's own minimum and maximum, while the screen's loop chooses exactly one card and
/// reports that limit through <see cref="OneCardFrom"/>, because the preferences the screen was built
/// with are not reachable from it and guessing them would be worse than saying what the seam can do.
///
/// `Selected` names the chosen cards by model id. Two copies of one card are interchangeable for
/// every prompt the game opens — a removal, an upgrade, a transform, an added card — so a list of
/// model ids says which cards were chosen even when the deck holds several copies of one.
/// </summary>
internal sealed record CardSelectPrompt(
    IReadOnlyList<CardModel> Offered,
    int MinSelect,
    int MaxSelect,
    IReadOnlyList<string> Selected)
{
    /// <summary>
    /// The action that ends a prompt once the caller is done with it, which is also how a prompt whose
    /// minimum is zero is skipped: the game accepts an empty selection exactly then.
    /// </summary>
    public const string FinishActionId = "finish_card_select";

    /// <summary>A prompt whose one card is chosen from the cards the screen is showing.</summary>
    public static CardSelectPrompt OneCardFrom(IReadOnlyList<CardModel> offered)
    {
        return new CardSelectPrompt(offered, 1, 1, []);
    }
}
