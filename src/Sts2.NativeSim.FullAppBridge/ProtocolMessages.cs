using System.Text.Json.Serialization;

namespace Sts2.NativeSim.FullAppBridge;

public sealed class RpcRequest
{
    [JsonPropertyName("id")]
    public int Id { get; set; }

    [JsonPropertyName("method")]
    public string Method { get; set; } = "";

    [JsonPropertyName("params")]
    public Dictionary<string, object?>? Params { get; set; }
}

public sealed class RpcResponse
{
    [JsonPropertyName("id")]
    public int Id { get; set; }

    [JsonPropertyName("result")]
    public object? Result { get; set; }

    [JsonPropertyName("error")]
    public string? Error { get; set; }
}

public sealed class LegalActionDto
{
    [JsonPropertyName("action_id")]
    public string ActionId { get; set; } = "";

    [JsonPropertyName("action_type")]
    public string ActionType { get; set; } = "";

    [JsonPropertyName("description")]
    public string Description { get; set; } = "";

    [JsonPropertyName("metadata")]
    public Dictionary<string, object?>? Metadata { get; set; }
}

public sealed class ObservationDto
{
    // The bridge's own observation version, not the simulator's: the two observations are
    // different encodings of one state. 4 is the fight's five ordered piles of converged card rows
    // replacing the hand list and the three pile counts. The run block and the inventory are still
    // to converge, and each moves this number again when it does.
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 4;

    [JsonPropertyName("phase")]
    public string Phase { get; set; } = "";

    [JsonPropertyName("is_terminal")]
    public bool IsTerminal { get; set; }

    [JsonPropertyName("is_victory")]
    public bool IsVictory { get; set; }

    [JsonPropertyName("seed")]
    public string Seed { get; set; } = "";

    [JsonPropertyName("character")]
    public string Character { get; set; } = "";

    [JsonPropertyName("ascension")]
    public int Ascension { get; set; }

    [JsonPropertyName("act")]
    public int Act { get; set; }

    [JsonPropertyName("floor")]
    public int Floor { get; set; }

    [JsonPropertyName("gold")]
    public int Gold { get; set; }

    [JsonPropertyName("player_hp")]
    public int PlayerHp { get; set; }

    [JsonPropertyName("player_max_hp")]
    public int PlayerMaxHp { get; set; }

    [JsonPropertyName("player_block")]
    public int PlayerBlock { get; set; }

    // The fight's energy is also on the combat block, which is where a comparison of two combat
    // observations reads it. This flat copy is the bridge's older seam and reports the same
    // accessor, so a caller that still reads it cannot disagree with the block.
    [JsonPropertyName("player_energy")]
    public int PlayerEnergy { get; set; }

    [JsonPropertyName("player_powers")]
    public Dictionary<string, int> PlayerPowers { get; set; } = new();

    [JsonPropertyName("deck_cards")]
    public List<string> DeckCards { get; set; } = new();

    [JsonPropertyName("relics")]
    public List<string> Relics { get; set; } = new();

    [JsonPropertyName("potions")]
    public List<string> Potions { get; set; } = new();

    [JsonPropertyName("combat")]
    public CombatObservationDto? Combat { get; set; }

    [JsonPropertyName("room")]
    public RoomObservationDto? Room { get; set; }

    [JsonPropertyName("state_hash")]
    public string StateHash { get; set; } = "";
}

/// <summary>
/// A fight as the simulator's own per-combat projection words it, so the two encoders' combat
/// blocks compare field by field instead of being two vocabularies for one situation. Every pile is
/// its ordered contents — a draw pile's order is what a policy learns from, and a count is not a
/// substitute — and every card is <see cref="CardObservationDto"/>.
/// </summary>
public sealed class CombatObservationDto
{
    // The encounter's own id: the identity `catalog` lists, the trace exporter reports and the
    // simulator's `combat.encounter` carries. Nullable on purpose — a fight that cannot name itself
    // reports no encounter at all, which is what the simulator reports for one too, rather than an
    // empty string that no comparison could tell from a name.
    [JsonPropertyName("encounter")]
    public string? Encounter { get; set; }

    [JsonPropertyName("turn")]
    public int Turn { get; set; }

    [JsonPropertyName("phase")]
    public string Phase { get; set; } = "";

    [JsonPropertyName("energy")]
    public int Energy { get; set; }

    [JsonPropertyName("max_energy")]
    public int MaxEnergy { get; set; }

    [JsonPropertyName("stars")]
    public int Stars { get; set; }

    [JsonPropertyName("creatures")]
    public List<CreatureObservationDto> Creatures { get; set; } = new();

    [JsonPropertyName("piles")]
    public List<PileObservationDto> Piles { get; set; } = new();
}

/// <summary>
/// One pile: the hand, the draw pile, the discard pile, the exhaust pile or the play pile, in the
/// order every projection reports them. `type` is the game's own word for the pile the bridge
/// walked, so the pairing of a name and a type is never the bridge's own invention.
/// </summary>
public sealed class PileObservationDto
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("type")]
    public string Type { get; set; } = "";

    [JsonPropertyName("cards")]
    public List<CardObservationDto> Cards { get; set; } = new();
}

/// <summary>
/// One card of one pile, worded exactly as the simulator's own pile projection words it, so two
/// encoders' cards for one situation compare field by field. `instance_id` is the bridge's own
/// identity — minted by <see cref="CardIdentityRegistry"/>, because card instances belong to
/// whichever encoder produced the state and two encoders will never agree on them — while `net_id`
/// is an identity the game itself mints and is therefore reported literally.
/// </summary>
public sealed class CardObservationDto
{
    [JsonPropertyName("instance_id")]
    public string InstanceId { get; set; } = "";

    [JsonPropertyName("net_id")]
    public uint NetId { get; set; }

    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("card_type")]
    public string CardType { get; set; } = "";

    [JsonPropertyName("target_type")]
    public string TargetType { get; set; } = "";

    // The cost every other projection reports: the one the card would actually be played for,
    // after modifiers, not the card's own canonical number.
    [JsonPropertyName("energy_cost")]
    public int EnergyCost { get; set; }

    [JsonPropertyName("costs_x")]
    public bool CostsX { get; set; }

    [JsonPropertyName("upgrades")]
    public int Upgrades { get; set; }

    // Absent rather than null on a card that is not enchanted, which is how every other projection
    // reports the two cases.
    [JsonPropertyName("enchantment")]
    public EnchantmentObservationDto? Enchantment { get; set; }

    [JsonPropertyName("native_state")]
    public SortedDictionary<string, object?> NativeState { get; set; } = new(StringComparer.Ordinal);
}

public sealed class EnchantmentObservationDto
{
    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("amount")]
    public int Amount { get; set; }
}

/// <summary>
/// One creature row, including the player's own, worded exactly as the simulator words its rows.
/// </summary>
public sealed class CreatureObservationDto
{
    [JsonPropertyName("combat_id")]
    public uint? CombatId { get; set; }

    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("side")]
    public string Side { get; set; } = "";

    [JsonPropertyName("hp")]
    public int Hp { get; set; }

    [JsonPropertyName("max_hp")]
    public int MaxHp { get; set; }

    [JsonPropertyName("block")]
    public int Block { get; set; }

    [JsonPropertyName("alive")]
    public bool Alive { get; set; }

    [JsonPropertyName("next_move")]
    public NextMoveObservationDto? NextMove { get; set; }

    [JsonPropertyName("powers")]
    public List<PowerObservationDto> Powers { get; set; } = new();
}

public sealed class NextMoveObservationDto
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("intents")]
    public List<IntentObservationDto> Intents { get; set; } = new();
}

/// <summary>
/// One intent of a move. Damage and repeats are the attack intent's own; an intent that is not an
/// attack leaves both absent, which is what the simulator reports for it too.
/// </summary>
public sealed class IntentObservationDto
{
    [JsonPropertyName("intent_type")]
    public string IntentType { get; set; } = "";

    [JsonPropertyName("implementation")]
    public string Implementation { get; set; } = "";

    [JsonPropertyName("damage")]
    public int? Damage { get; set; }

    [JsonPropertyName("repeats")]
    public int? Repeats { get; set; }
}

public sealed class PowerObservationDto
{
    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("amount")]
    public int Amount { get; set; }
}

public sealed class RoomObservationDto
{
    [JsonPropertyName("room_type")]
    public string RoomType { get; set; } = "";

    [JsonPropertyName("options")]
    public List<string> Options { get; set; } = new();

    [JsonPropertyName("details")]
    public Dictionary<string, object?> Details { get; set; } = new();
}
