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
    // different encodings of one state. 4 was the fight's five ordered piles of converged card rows
    // replacing the hand list and the three pile counts. 5 carried the game build, the run block —
    // act identity, both floors, the named RNG counters and the map coordinate — and the inventory
    // of relic objects and potions by slot, replacing the flat run and inventory members. 6 is a
    // potion row that is the record's row exactly, without the empty native state no comparison has
    // a counterpart for.
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 6;

    [JsonPropertyName("phase")]
    public string Phase { get; set; } = "";

    [JsonPropertyName("is_terminal")]
    public bool IsTerminal { get; set; }

    [JsonPropertyName("is_victory")]
    public bool IsVictory { get; set; }

    // The shipped build this observation was taken on. A record carries the same three values, so a
    // comparison attributes a mismatch to a build instead of to a state.
    [JsonPropertyName("game_build")]
    public GameBuildDto GameBuild { get; set; } = new();

    [JsonPropertyName("character")]
    public string Character { get; set; } = "";

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

    // Where the run is: its seed, Ascension and gold, the Act it is in and how far into it, the named
    // RNG counters, and the run's total floor. Absent only when no run exists to describe.
    [JsonPropertyName("run")]
    public RunObservationDto? Run { get; set; }

    // The coordinate the run stands on, absent until it has travelled to one. The shipped game
    // travels to its act's Ancient before the first decision the bridge reports, so this is the
    // row-0 Ancient coordinate from the first observation on — the check that the oracle drove the
    // game to the node a record names.
    [JsonPropertyName("map_coord")]
    public CoordObservationDto? MapCoord { get; set; }

    // The run's inventory as objects: relics in the order the run holds them, potions by slot.
    [JsonPropertyName("inventory")]
    public InventoryObservationDto? Inventory { get; set; }

    [JsonPropertyName("combat")]
    public CombatObservationDto? Combat { get; set; }

    [JsonPropertyName("room")]
    public RoomObservationDto? Room { get; set; }

    [JsonPropertyName("state_hash")]
    public string StateHash { get; set; } = "";
}

/// <summary>
/// The build an observation was taken on, worded as the simulator's worker, the trace exporter and
/// the published canonical-state schema all word it, because it is compared against them literally.
/// </summary>
public sealed class GameBuildDto
{
    [JsonPropertyName("version")]
    public string Version { get; set; } = "";

    [JsonPropertyName("assembly_sha256")]
    public string AssemblySha256 { get; set; } = "";

    [JsonPropertyName("pck_sha256")]
    public string PckSha256 { get; set; } = "";
}

/// <summary>
/// Where the run is, as the simulator's own run block reports it. `act_index` is the run's own
/// zero-based act index — the base every other projection in the repository reports — and
/// `act_variant` is the Act model in play, so neither has to be re-derived from the seed.
/// `total_floor` counts the map points the run has travelled, which is the floor the Ancient room
/// advances and the counter the per-encounter generator is seeded with.
/// </summary>
public sealed class RunObservationDto
{
    [JsonPropertyName("seed")]
    public string Seed { get; set; } = "";

    [JsonPropertyName("ascension")]
    public int Ascension { get; set; }

    [JsonPropertyName("gold")]
    public int Gold { get; set; }

    [JsonPropertyName("act_variant")]
    public string ActVariant { get; set; } = "";

    [JsonPropertyName("act_index")]
    public int ActIndex { get; set; }

    [JsonPropertyName("act_floor")]
    public int ActFloor { get; set; }

    [JsonPropertyName("total_floor")]
    public int TotalFloor { get; set; }

    [JsonPropertyName("rng_counters")]
    public SortedDictionary<string, int> RngCounters { get; set; } = new(StringComparer.Ordinal);
}

/// <summary>One map coordinate, worded as the schema's own coord.</summary>
public sealed class CoordObservationDto
{
    [JsonPropertyName("col")]
    public int Col { get; set; }

    [JsonPropertyName("row")]
    public int Row { get; set; }
}

/// <summary>
/// The run's inventory, worded as the simulator's own inventory block words it.
/// </summary>
public sealed class InventoryObservationDto
{
    [JsonPropertyName("relics")]
    public List<RelicObservationDto> Relics { get; set; } = new();

    // One entry per potion slot, in slot order. An empty slot is a null entry rather than a hole, so
    // a slot index survives the serialisation — which is what makes a potion's slot usable as an
    // identity and an empty belt readable as "three slots, none of them full".
    [JsonPropertyName("potions")]
    public List<PotionObservationDto?> Potions { get; set; } = new();
}

/// <summary>
/// One relic of the run, in the order the run holds them. `counter` is present only for a relic that
/// shows one, which is how the game itself reports the two cases; `native_state` is the relic's own
/// saved properties, so a comparison can see a relic that has been charged or consumed.
/// </summary>
public sealed class RelicObservationDto
{
    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("counter")]
    public int? Counter { get; set; }

    [JsonPropertyName("native_state")]
    public SortedDictionary<string, object?> NativeState { get; set; } = new(StringComparer.Ordinal);
}

/// <summary>
/// One potion of the run, by the slot it sits in. It carries the slot and the model and nothing else,
/// which is the whole of what the shipped potion's serializable form saves: a potion has no saved
/// scalar state to report, and the parity contract's inventory row for a potion — and the published
/// schema's — says the same, so a comparison reads this row without an exception.
/// </summary>
public sealed class PotionObservationDto
{
    [JsonPropertyName("slot")]
    public int Slot { get; set; }

    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";
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
