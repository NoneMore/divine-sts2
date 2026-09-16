using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// The bridge's own card identity registry.
///
/// Card instance ids belong to whichever encoder produced the state: the shipped game never mints
/// one, and the simulator and the trace exporter each mint their own, so two encoders will never
/// agree on the string for the same card. A parity comparison therefore treats an instance id
/// structurally — a card's position within one ordered pile plus the card's other attributes — and
/// what the bridge owes it is an id that is stable within one observation and unique across the
/// piles. This is where that id comes from; the game's own identities (a model id, the net card id,
/// the encounter id) are reported literally instead.
///
/// The registry recalls an id for a card it has already seen, keyed by object identity, so the same
/// card keeps its id across observations of one situation — which is what lets a caller watch a card
/// move from the draw pile to the hand and still recognise it. An id is shaped the way the
/// simulator's own registry shapes one, <c>dynamic-&lt;ordinal&gt;-&lt;model id&gt;</c>, so the two
/// projections of one situation read alike. Ids are scoped to one fight's player combat state: a new
/// fight resets that state, so its cards are new objects and the ordinals start over.
/// </summary>
internal sealed class CardIdentityRegistry
{
    private readonly Dictionary<CardModel, string> _ids = new(ReferenceEqualityComparer.Instance);
    private PlayerCombatState? _fight;
    private int _nextOrdinal;

    /// <summary>
    /// The bridge's id for one card of one fight, minted the first time this fight's card is seen.
    /// </summary>
    public string IdFor(PlayerCombatState fight, CardModel card)
    {
        if (!ReferenceEquals(_fight, fight))
        {
            _ids.Clear();
            _nextOrdinal = 0;
            _fight = fight;
        }

        if (_ids.TryGetValue(card, out string? id))
        {
            return id;
        }

        id = $"dynamic-{_nextOrdinal++}-{card.Id.Entry}";
        _ids[card] = id;
        return id;
    }
}
