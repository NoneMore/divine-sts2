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

/// <summary>
/// Build identity of the shipped application this bridge is embedded in. Read once at
/// startup from the loaded assembly and the PCK beside the executable, never from
/// configuration, so a report can pin the exact build the projection came from.
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

/// <summary>One native saved property, extracted exactly as the fast path extracts it.</summary>
public sealed class CardProjectionDto
{
    [JsonPropertyName("index")]
    public int Index { get; set; }

    /// <summary>Environment-local combat registration id; never a cross-environment identity.</summary>
    [JsonPropertyName("net_id")]
    public ulong NetId { get; set; }

    /// <summary>Environment-local stable pile identity; never a cross-environment identity.</summary>
    [JsonPropertyName("instance_id")]
    public string InstanceId { get; set; } = "";

    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("card_type")]
    public string CardType { get; set; } = "";

    [JsonPropertyName("target_type")]
    public string TargetType { get; set; } = "";

    [JsonPropertyName("energy_cost")]
    public int EnergyCost { get; set; }

    [JsonPropertyName("costs_x")]
    public bool CostsX { get; set; }

    [JsonPropertyName("upgrades")]
    public int Upgrades { get; set; }

    [JsonPropertyName("enchantment")]
    public EnchantmentProjectionDto? Enchantment { get; set; }

    [JsonPropertyName("native_state")]
    public SortedDictionary<string, object?> NativeState { get; set; } = new(StringComparer.Ordinal);
}

public sealed class EnchantmentProjectionDto
{
    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("amount")]
    public int Amount { get; set; }
}

public sealed class PileProjectionDto
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("type")]
    public string Type { get; set; } = "";

    [JsonPropertyName("cards")]
    public List<CardProjectionDto> Cards { get; set; } = new();
}

public sealed class PowerProjectionDto
{
    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("amount")]
    public int Amount { get; set; }
}

public sealed class IntentProjectionDto
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

public sealed class NextMoveProjectionDto
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("intents")]
    public List<IntentProjectionDto> Intents { get; set; } = new();
}

public sealed class CreatureProjectionDto
{
    [JsonPropertyName("combat_id")]
    public ulong CombatId { get; set; }

    /// <summary>Position in the native creature list; the cross-environment target identity.</summary>
    [JsonPropertyName("index")]
    public int Index { get; set; }

    [JsonPropertyName("side")]
    public string Side { get; set; } = "";

    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("hp")]
    public int Hp { get; set; }

    [JsonPropertyName("max_hp")]
    public int MaxHp { get; set; }

    [JsonPropertyName("block")]
    public int Block { get; set; }

    [JsonPropertyName("alive")]
    public bool Alive { get; set; }

    [JsonPropertyName("is_player")]
    public bool IsPlayer { get; set; }

    [JsonPropertyName("next_move")]
    public NextMoveProjectionDto? NextMove { get; set; }

    [JsonPropertyName("powers")]
    public List<PowerProjectionDto> Powers { get; set; } = new();
}

public sealed class EncounterProjectionDto
{
    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("room_type")]
    public string RoomType { get; set; } = "";

    /// <summary>The encounter's declared monster list, independent of what is currently alive.</summary>
    [JsonPropertyName("monster_models")]
    public List<string> MonsterModels { get; set; } = new();

    [JsonPropertyName("slots")]
    public List<string> Slots { get; set; } = new();
}

public sealed class OrbProjectionDto
{
    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("passive")]
    public decimal Passive { get; set; }

    [JsonPropertyName("evoke")]
    public decimal Evoke { get; set; }

    [JsonPropertyName("native_state")]
    public SortedDictionary<string, object?> NativeState { get; set; } = new(StringComparer.Ordinal);
}

public sealed class OrbQueueProjectionDto
{
    [JsonPropertyName("capacity")]
    public int Capacity { get; set; }

    [JsonPropertyName("entries")]
    public List<OrbProjectionDto> Entries { get; set; } = new();
}

public sealed class RelicProjectionDto
{
    [JsonPropertyName("index")]
    public int Index { get; set; }

    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("counter")]
    public int? Counter { get; set; }

    [JsonPropertyName("native_state")]
    public SortedDictionary<string, object?> NativeState { get; set; } = new(StringComparer.Ordinal);
}

public sealed class PotionProjectionDto
{
    [JsonPropertyName("slot")]
    public int Slot { get; set; }

    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("native_state")]
    public SortedDictionary<string, object?> NativeState { get; set; } = new(StringComparer.Ordinal);
}

public sealed class RunProjectionDto
{
    [JsonPropertyName("seed")]
    public string Seed { get; set; } = "";

    [JsonPropertyName("character")]
    public string Character { get; set; } = "";

    [JsonPropertyName("ascension")]
    public int Ascension { get; set; }

    [JsonPropertyName("gold")]
    public int Gold { get; set; }

    [JsonPropertyName("current_hp")]
    public int CurrentHp { get; set; }

    [JsonPropertyName("max_hp")]
    public int MaxHp { get; set; }

    [JsonPropertyName("act_index")]
    public int ActIndex { get; set; }

    [JsonPropertyName("act_floor")]
    public int ActFloor { get; set; }

    [JsonPropertyName("total_floor")]
    public int TotalFloor { get; set; }

    [JsonPropertyName("act_id")]
    public string ActId { get; set; } = "";

    [JsonPropertyName("rng_counters")]
    public SortedDictionary<string, int> RngCounters { get; set; } = new(StringComparer.Ordinal);

    [JsonPropertyName("deck")]
    public List<CardProjectionDto> Deck { get; set; } = new();

    [JsonPropertyName("relics")]
    public List<RelicProjectionDto> Relics { get; set; } = new();

    /// <summary>Slot-indexed potion array; a null entry is an empty slot, so the length is the capacity.</summary>
    [JsonPropertyName("potions")]
    public List<PotionProjectionDto?> Potions { get; set; } = new();

    [JsonPropertyName("potion_capacity")]
    public int PotionCapacity { get; set; }
}

/// <summary>One selectable entry of a pending nested choice, in native option order.</summary>
public sealed class ChoiceOptionDto
{
    [JsonPropertyName("option_id")]
    public string OptionId { get; set; } = "";

    [JsonPropertyName("model_id")]
    public string? ModelId { get; set; }

    /// <summary>Bundle options carry their card list; card options carry their own identity.</summary>
    [JsonPropertyName("cards")]
    public List<CardRefDto>? Cards { get; set; }
}

public sealed class CardRefDto
{
    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";
}

/// <summary>The pending nested choice, shaped like the reconstructed environment's `outstanding_choice`.</summary>
public sealed class BridgeChoiceProjectionDto
{
    [JsonPropertyName("choice_id")]
    public string ChoiceId { get; set; } = "";

    [JsonPropertyName("kind")]
    public string Kind { get; set; } = "";

    [JsonPropertyName("min_select")]
    public int MinSelect { get; set; }

    [JsonPropertyName("max_select")]
    public int MaxSelect { get; set; }

    [JsonPropertyName("options")]
    public List<ChoiceOptionDto> Options { get; set; } = new();
}

public sealed class DecisionDto
{
    [JsonPropertyName("kind")]
    public string Kind { get; set; } = "";
}

/// <summary>
/// A nested choice the shipped game is currently awaiting. Mirrors the reconstructed
/// environment's `PendingNativeChoice`: legal actions are all selections of size
/// <see cref="MinSelect"/>..<see cref="MaxSelect"/>, and the caller resolves it with the option ids.
/// </summary>
public sealed class BridgePendingChoice
{
    public string ChoiceId { get; init; } = "";

    /// <summary>Wire decision kind: `card_choice` or `option_choice`.</summary>
    public string DecisionKind { get; init; } = "";

    /// <summary>Wire action kind: `choose_cards` or `choose_option`.</summary>
    public string ActionKind { get; init; } = "";

    public string[] OptionIds { get; init; } = Array.Empty<string>();

    public int MinSelect { get; init; }

    public int MaxSelect { get; init; }

    public List<ChoiceOptionDto> Options { get; init; } = new();

    /// <summary>Completes the native await with the options the protocol selected.</summary>
    public Action<string[]>? Resolve { get; set; }
}

public sealed class ObservationDto
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 3;

    [JsonPropertyName("game_build")]
    public GameBuildDto? GameBuild { get; set; }

    [JsonPropertyName("decision")]
    public DecisionDto? Decision { get; set; }

    [JsonPropertyName("outstanding_choice")]
    public BridgeChoiceProjectionDto? OutstandingChoice { get; set; }

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

    /// <summary>
    /// The first-combat root projection the differential gate compares against the fast path:
    /// unsorted deck, relics with counters/native state, slot-indexed potions, and every run RNG
    /// stream counter. Null outside a run.
    /// </summary>
    [JsonPropertyName("run")]
    public RunProjectionDto? Run { get; set; }

    [JsonPropertyName("combat")]
    public CombatObservationDto? Combat { get; set; }

    [JsonPropertyName("room")]
    public RoomObservationDto? Room { get; set; }

    [JsonPropertyName("state_hash")]
    public string StateHash { get; set; } = "";
}

public sealed class CombatObservationDto
{
    [JsonPropertyName("turn")]
    public int Turn { get; set; }

    /// <summary>
    /// The native <c>PlayerCombatState.Phase</c>. The plan's root boundary is
    /// <c>combat.turn == 1 &amp;&amp; combat.phase == "Play"</c>; the bridge-level
    /// <c>phase == "combat"</c> string is not a substitute for it.
    /// </summary>
    [JsonPropertyName("phase")]
    public string Phase { get; set; } = "";

    [JsonPropertyName("energy")]
    public int Energy { get; set; }

    [JsonPropertyName("max_energy")]
    public int MaxEnergy { get; set; }

    [JsonPropertyName("stars")]
    public int Stars { get; set; }

    [JsonPropertyName("encounter")]
    public EncounterProjectionDto? Encounter { get; set; }

    [JsonPropertyName("creatures")]
    public List<CreatureProjectionDto> Creatures { get; set; } = new();

    [JsonPropertyName("piles")]
    public List<PileProjectionDto> Piles { get; set; } = new();

    [JsonPropertyName("orbs")]
    public OrbQueueProjectionDto? Orbs { get; set; }

    [JsonPropertyName("hand")]
    public List<CardObservationDto> Hand { get; set; } = new();

    [JsonPropertyName("draw_pile_count")]
    public int DrawPileCount { get; set; }

    [JsonPropertyName("discard_pile_count")]
    public int DiscardPileCount { get; set; }

    [JsonPropertyName("exhaust_pile_count")]
    public int ExhaustPileCount { get; set; }

    [JsonPropertyName("enemies")]
    public List<EnemyObservationDto> Enemies { get; set; } = new();
}

public sealed class CardObservationDto
{
    [JsonPropertyName("index")]
    public int Index { get; set; }

    [JsonPropertyName("card_id")]
    public string CardId { get; set; } = "";

    [JsonPropertyName("cost")]
    public int Cost { get; set; }

    [JsonPropertyName("can_play")]
    public bool CanPlay { get; set; }

    [JsonPropertyName("target_type")]
    public string TargetType { get; set; } = "";

    [JsonPropertyName("upgrades")]
    public int Upgrades { get; set; }
}

public sealed class EnemyObservationDto
{
    [JsonPropertyName("combat_id")]
    public ulong CombatId { get; set; }

    [JsonPropertyName("model_id")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("hp")]
    public int Hp { get; set; }

    [JsonPropertyName("max_hp")]
    public int MaxHp { get; set; }

    [JsonPropertyName("block")]
    public int Block { get; set; }

    [JsonPropertyName("is_alive")]
    public bool IsAlive { get; set; }

    [JsonPropertyName("intent")]
    public string Intent { get; set; } = "";

    [JsonPropertyName("powers")]
    public Dictionary<string, int> Powers { get; set; } = new();
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
