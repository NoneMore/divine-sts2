using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Sts2.NativeSim.Protocol;

[AttributeUsage(AttributeTargets.Class | AttributeTargets.Struct, Inherited = false)]
internal sealed class CanonicalSchemaDefinitionAttribute(string name) : Attribute
{
    public string Name { get; } = name;
}

[AttributeUsage(AttributeTargets.Class | AttributeTargets.Struct, Inherited = false)]
internal sealed class CanonicalSchemaOneOfAttribute(params Type[] types) : Attribute
{
    public IReadOnlyList<Type> Types { get; } = types;
}

[AttributeUsage(AttributeTargets.Property)]
internal sealed class CanonicalSchemaConstantAttribute(int value) : Attribute
{
    public int Value { get; } = value;
}

[AttributeUsage(AttributeTargets.Property)]
internal sealed class CanonicalSchemaMinLengthAttribute(int value) : Attribute
{
    public int Value { get; } = value;
}

[AttributeUsage(AttributeTargets.Property)]
internal sealed class CanonicalSchemaNullableItemsAttribute : Attribute;

[AttributeUsage(AttributeTargets.Class, Inherited = false)]
internal sealed class CanonicalStageAttribute(string[] requiredBlocks, params string[] decisionKinds) : Attribute
{
    public IReadOnlyList<string> RequiredBlocks { get; } = requiredBlocks;
    public IReadOnlyList<string> DecisionKinds { get; } = decisionKinds;
}

public sealed record CanonicalObservation
{
    [JsonPropertyName("schema_version"), CanonicalSchemaConstant(ProtocolConstants.ObservationSchemaVersion)]
    public required int SchemaVersion { get; init; }

    [JsonPropertyName("game_build")]
    public required CanonicalGameBuild GameBuild { get; init; }

    [JsonPropertyName("run")]
    public required CanonicalRun Run { get; init; }

    [JsonPropertyName("combat")]
    public CanonicalCombat? Combat { get; init; }

    [JsonPropertyName("inventory")]
    public CanonicalInventory? Inventory { get; init; }

    [JsonPropertyName("map")]
    public CanonicalMap? Map { get; init; }

    [JsonPropertyName("reward")]
    public CanonicalReward? Reward { get; init; }

    [JsonPropertyName("rest_site")]
    public CanonicalRestSite? RestSite { get; init; }

    [JsonPropertyName("event")]
    public CanonicalEvent? Event { get; init; }

    [JsonPropertyName("treasure")]
    public CanonicalTreasure? Treasure { get; init; }

    [JsonPropertyName("shop")]
    public CanonicalShop? Shop { get; init; }

    [JsonPropertyName("room_rewards")]
    public CanonicalRoomRewards? RoomRewards { get; init; }

    [JsonPropertyName("custom_rewards")]
    public CanonicalCustomRewards? CustomRewards { get; init; }

    [JsonPropertyName("outstanding_rewards")]
    public CanonicalCustomRewards? OutstandingRewards { get; init; }

    [JsonPropertyName("outstanding_choice")]
    public CanonicalChoice? OutstandingChoice { get; init; }

    [JsonPropertyName("decision")]
    public required CanonicalDecision Decision { get; init; }

    [JsonPropertyName("terminal")]
    public required bool Terminal { get; init; }

    [JsonPropertyName("victory")]
    public required bool Victory { get; init; }

    [JsonIgnore]
    public CanonicalObservationStage Stage => CanonicalObservationStage.Create(this);
}

public abstract record CanonicalObservationStage
{
    private static readonly string[] PrimaryBlocks =
        ["combat", "map", "reward", "rest_site", "event", "treasure", "shop", "room_rewards", "custom_rewards"];

    internal static IReadOnlyList<Type> Types { get; } = typeof(CanonicalObservationStage).Assembly.GetTypes()
        .Where(type => !type.IsAbstract && type.IsSubclassOf(typeof(CanonicalObservationStage)))
        .OrderBy(type => type.Name, StringComparer.Ordinal)
        .ToArray();

    internal static CanonicalObservationStage Create(CanonicalObservation observation)
    {
        Dictionary<string, object?> blocks = new(StringComparer.Ordinal)
        {
            ["combat"] = observation.Combat,
            ["map"] = observation.Map,
            ["reward"] = observation.Reward,
            ["rest_site"] = observation.RestSite,
            ["event"] = observation.Event,
            ["treasure"] = observation.Treasure,
            ["shop"] = observation.Shop,
            ["room_rewards"] = observation.RoomRewards,
            ["custom_rewards"] = observation.CustomRewards,
            ["inventory"] = observation.Inventory,
        };
        Type[] matches = Types.Where(type =>
        {
            CanonicalStageAttribute stage = type.GetCustomAttribute<CanonicalStageAttribute>()!;
            bool requiredPresent = stage.RequiredBlocks.All(block => blocks[block] is not null);
            bool noOtherPrimary = PrimaryBlocks.All(block => blocks[block] is null || stage.RequiredBlocks.Contains(block));
            bool inventoryValid = observation.Inventory is null || stage.RequiredBlocks.Contains("inventory");
            return requiredPresent && noOtherPrimary && inventoryValid
                && stage.DecisionKinds.Contains(observation.Decision.Kind, StringComparer.Ordinal);
        }).ToArray();
        if (matches.Length != 1)
        {
            throw new JsonException($"Decision '{observation.Decision.Kind}' and its stage blocks do not name one canonical observation variant.");
        }
        return matches[0] == typeof(CanonicalCombatObservationStage) ? new CanonicalCombatObservationStage(observation.Combat!, observation.Inventory!)
            : matches[0] == typeof(CanonicalMapObservationStage) ? new CanonicalMapObservationStage(observation.Map!)
            : matches[0] == typeof(CanonicalRewardObservationStage) ? new CanonicalRewardObservationStage(observation.Reward!)
            : matches[0] == typeof(CanonicalRestObservationStage) ? new CanonicalRestObservationStage(observation.RestSite!)
            : matches[0] == typeof(CanonicalEventObservationStage) ? new CanonicalEventObservationStage(observation.Event!)
            : matches[0] == typeof(CanonicalTreasureObservationStage) ? new CanonicalTreasureObservationStage(observation.Treasure!)
            : matches[0] == typeof(CanonicalShopObservationStage) ? new CanonicalShopObservationStage(observation.Shop!)
            : matches[0] == typeof(CanonicalRoomRewardsObservationStage) ? new CanonicalRoomRewardsObservationStage(observation.RoomRewards!)
            : matches[0] == typeof(CanonicalCustomRewardsObservationStage) ? new CanonicalCustomRewardsObservationStage(observation.CustomRewards!)
            : new CanonicalRunOnlyObservationStage();
    }
}

[CanonicalStage(new[] { "combat", "inventory" }, "combat_action", "terminal", "card_choice", "option_choice", "custom_reward_choice")]
public sealed record CanonicalCombatObservationStage(CanonicalCombat Combat, CanonicalInventory Inventory) : CanonicalObservationStage;

[CanonicalStage(new[] { "map" }, "map_choice", "map_terminal", "card_choice", "option_choice", "custom_reward_choice")]
public sealed record CanonicalMapObservationStage(CanonicalMap Map) : CanonicalObservationStage;

[CanonicalStage(new[] { "reward" }, "reward_choice", "reward_complete", "card_choice", "option_choice", "custom_reward_choice")]
public sealed record CanonicalRewardObservationStage(CanonicalReward Reward) : CanonicalObservationStage;

[CanonicalStage(new[] { "rest_site" }, "rest_choice", "rest_complete", "card_choice", "option_choice", "custom_reward_choice")]
public sealed record CanonicalRestObservationStage(CanonicalRestSite RestSite) : CanonicalObservationStage;

[CanonicalStage(new[] { "event" }, "event_choice", "event_complete", "card_choice", "option_choice", "custom_reward_choice")]
public sealed record CanonicalEventObservationStage(CanonicalEvent Event) : CanonicalObservationStage;

[CanonicalStage(new[] { "treasure" }, "treasure_open", "treasure_relic_choice", "treasure_complete", "card_choice", "option_choice", "custom_reward_choice")]
public sealed record CanonicalTreasureObservationStage(CanonicalTreasure Treasure) : CanonicalObservationStage;

[CanonicalStage(new[] { "shop" }, "shop_choice", "card_choice", "option_choice", "custom_reward_choice")]
public sealed record CanonicalShopObservationStage(CanonicalShop Shop) : CanonicalObservationStage;

[CanonicalStage(new[] { "room_rewards" }, "room_reward_choice", "card_choice", "option_choice", "custom_reward_choice")]
public sealed record CanonicalRoomRewardsObservationStage(CanonicalRoomRewards RoomRewards) : CanonicalObservationStage;

[CanonicalStage(new[] { "custom_rewards" }, "custom_reward_choice", "custom_reward_complete", "card_choice", "option_choice")]
public sealed record CanonicalCustomRewardsObservationStage(CanonicalCustomRewards CustomRewards) : CanonicalObservationStage;

[CanonicalStage(new string[] { }, "act_transition", "run_terminal")]
public sealed record CanonicalRunOnlyObservationStage : CanonicalObservationStage;

[CanonicalSchemaOneOf(typeof(int), typeof(bool), typeof(string), typeof(int[]))]
[JsonConverter(typeof(CanonicalNativeValueJsonConverter))]
public readonly record struct CanonicalNativeValue(JsonElement Value);

[CanonicalSchemaDefinition("game_build")]
public sealed record CanonicalGameBuild
{
    [JsonPropertyName("version")] public required string Version { get; init; }
    [JsonPropertyName("assembly_sha256")] public required string AssemblySha256 { get; init; }
    [JsonPropertyName("pck_sha256")] public required string PckSha256 { get; init; }
}

[CanonicalSchemaDefinition("run")]
public sealed record CanonicalRun
{
    [JsonPropertyName("seed")] public required string Seed { get; init; }
    [JsonPropertyName("ascension")] public required int Ascension { get; init; }
    [JsonPropertyName("gold")] public int? Gold { get; init; }
    [JsonPropertyName("act_variant")] public required string ActVariant { get; init; }
    [JsonPropertyName("act_index")] public int? ActIndex { get; init; }
    [JsonPropertyName("act_floor")] public int? ActFloor { get; init; }
    [JsonPropertyName("total_floor")] public int? TotalFloor { get; init; }
    [JsonPropertyName("current_hp")] public int? CurrentHp { get; init; }
    [JsonPropertyName("max_hp")] public int? MaxHp { get; init; }
    [JsonPropertyName("deck")] public IReadOnlyList<CanonicalRunCard>? Deck { get; init; }
    [JsonPropertyName("relics")] public IReadOnlyList<string>? Relics { get; init; }
    [JsonPropertyName("potions"), CanonicalSchemaNullableItems] public IReadOnlyList<string?>? Potions { get; init; }
    [JsonPropertyName("rng_counters")] public required IReadOnlyDictionary<string, int> RngCounters { get; init; }
}

[CanonicalSchemaOneOf(typeof(string), typeof(CanonicalCardReference))]
[JsonConverter(typeof(CanonicalRunCardJsonConverter))]
public readonly record struct CanonicalRunCard(string? ModelId, CanonicalCardReference? Reference);

[CanonicalSchemaDefinition("card_reference")]
public sealed record CanonicalCardReference
{
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
    [JsonPropertyName("upgrades")] public required int Upgrades { get; init; }
}

[CanonicalSchemaDefinition("combat")]
public sealed record CanonicalCombat
{
    [JsonPropertyName("encounter"), CanonicalSchemaMinLength(1)] public required string Encounter { get; init; }
    [JsonPropertyName("turn")] public required int Turn { get; init; }
    [JsonPropertyName("phase")] public required string Phase { get; init; }
    [JsonPropertyName("energy")] public required int Energy { get; init; }
    [JsonPropertyName("max_energy")] public required int MaxEnergy { get; init; }
    [JsonPropertyName("stars")] public required int Stars { get; init; }
    [JsonPropertyName("creatures")] public required IReadOnlyList<CanonicalCreature> Creatures { get; init; }
    [JsonPropertyName("piles")] public required IReadOnlyList<CanonicalPile> Piles { get; init; }
    [JsonPropertyName("orbs")] public CanonicalOrbs? Orbs { get; init; }
}

[CanonicalSchemaDefinition("creature")]
public sealed record CanonicalCreature
{
    [JsonPropertyName("combat_id")] public required long CombatId { get; init; }
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
    [JsonPropertyName("side")] public required string Side { get; init; }
    [JsonPropertyName("hp")] public required int Hp { get; init; }
    [JsonPropertyName("max_hp")] public required int MaxHp { get; init; }
    [JsonPropertyName("block")] public required int Block { get; init; }
    [JsonPropertyName("alive")] public required bool Alive { get; init; }
    [JsonPropertyName("next_move")] public CanonicalNextMove? NextMove { get; init; }
    [JsonPropertyName("powers")] public required IReadOnlyList<CanonicalPower> Powers { get; init; }
}

[CanonicalSchemaDefinition("next_move")]
public sealed record CanonicalNextMove
{
    [JsonPropertyName("id")] public required string Id { get; init; }
    [JsonPropertyName("intents")] public required IReadOnlyList<CanonicalIntent> Intents { get; init; }
}

[CanonicalSchemaDefinition("intent")]
public sealed record CanonicalIntent
{
    [JsonPropertyName("intent_type")] public required string IntentType { get; init; }
    [JsonPropertyName("implementation")] public required string Implementation { get; init; }
    [JsonPropertyName("damage")] public int? Damage { get; init; }
    [JsonPropertyName("repeats")] public int? Repeats { get; init; }
}

[CanonicalSchemaDefinition("power")]
public sealed record CanonicalPower
{
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
    [JsonPropertyName("amount")] public required int Amount { get; init; }
}

[CanonicalSchemaDefinition("orbs")]
public sealed record CanonicalOrbs
{
    [JsonPropertyName("capacity")] public required int Capacity { get; init; }
    [JsonPropertyName("entries")] public required IReadOnlyList<CanonicalOrb> Entries { get; init; }
}

[CanonicalSchemaDefinition("orb")]
public sealed record CanonicalOrb
{
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
    [JsonPropertyName("passive")] public required int Passive { get; init; }
    [JsonPropertyName("evoke")] public required int Evoke { get; init; }
    [JsonPropertyName("native_state")] public required IReadOnlyDictionary<string, CanonicalNativeValue> NativeState { get; init; }
}

[CanonicalSchemaDefinition("pile")]
public sealed record CanonicalPile
{
    [JsonPropertyName("name")] public required string Name { get; init; }
    [JsonPropertyName("type")] public required string Type { get; init; }
    [JsonPropertyName("cards")] public required IReadOnlyList<CanonicalCard> Cards { get; init; }
}

[CanonicalSchemaDefinition("card")]
public sealed record CanonicalCard
{
    [JsonPropertyName("instance_id")] public required string InstanceId { get; init; }
    [JsonPropertyName("net_id")] public required long NetId { get; init; }
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
    [JsonPropertyName("card_type")] public required string CardType { get; init; }
    [JsonPropertyName("target_type")] public required string TargetType { get; init; }
    [JsonPropertyName("energy_cost")] public required int EnergyCost { get; init; }
    [JsonPropertyName("costs_x")] public required bool CostsX { get; init; }
    [JsonPropertyName("upgrades")] public required int Upgrades { get; init; }
    [JsonPropertyName("enchantment")] public CanonicalEnchantment? Enchantment { get; init; }
    [JsonPropertyName("native_state")] public required IReadOnlyDictionary<string, CanonicalNativeValue> NativeState { get; init; }
}

[CanonicalSchemaDefinition("enchantment")]
public sealed record CanonicalEnchantment
{
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
    [JsonPropertyName("amount")] public required int Amount { get; init; }
}

[CanonicalSchemaDefinition("inventory")]
public sealed record CanonicalInventory
{
    [JsonPropertyName("relics")] public required IReadOnlyList<CanonicalInventoryRelic> Relics { get; init; }
    [JsonPropertyName("potions"), CanonicalSchemaNullableItems] public required IReadOnlyList<CanonicalPotion?> Potions { get; init; }
}

[CanonicalSchemaDefinition("inventory_relic")]
public sealed record CanonicalInventoryRelic
{
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
    [JsonPropertyName("counter")] public int? Counter { get; init; }
    [JsonPropertyName("native_state")] public required IReadOnlyDictionary<string, CanonicalNativeValue> NativeState { get; init; }
}

[CanonicalSchemaDefinition("potion")]
public sealed record CanonicalPotion
{
    [JsonPropertyName("slot")] public required int Slot { get; init; }
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
}

[CanonicalSchemaDefinition("coord")]
public sealed record CanonicalCoord
{
    [JsonPropertyName("col")] public required int Col { get; init; }
    [JsonPropertyName("row")] public required int Row { get; init; }
}

[CanonicalSchemaDefinition("map")]
public sealed record CanonicalMap
{
    [JsonPropertyName("points")] public required IReadOnlyList<CanonicalMapPoint> Points { get; init; }
    [JsonPropertyName("visited")] public required IReadOnlyList<CanonicalCoord> Visited { get; init; }
    [JsonPropertyName("current")] public CanonicalCoord? Current { get; init; }
}

[CanonicalSchemaDefinition("map_point")]
public sealed record CanonicalMapPoint
{
    [JsonPropertyName("coord")] public required CanonicalCoord Coord { get; init; }
    [JsonPropertyName("point_type")] public required string PointType { get; init; }
    [JsonPropertyName("children")] public required IReadOnlyList<CanonicalCoord> Children { get; init; }
}

[CanonicalSchemaDefinition("reward")]
public sealed record CanonicalReward
{
    [JsonPropertyName("kind")] public required string Kind { get; init; }
    [JsonPropertyName("options")] public required IReadOnlyList<CanonicalRewardOption> Options { get; init; }
    [JsonPropertyName("can_skip")] public required bool CanSkip { get; init; }
    [JsonPropertyName("selected")] public required bool Selected { get; init; }
}

[CanonicalSchemaDefinition("reward_option")]
public sealed record CanonicalRewardOption
{
    [JsonPropertyName("option_id")] public required string OptionId { get; init; }
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
}

[CanonicalSchemaDefinition("rest_site")]
public sealed record CanonicalRestSite
{
    [JsonPropertyName("options")] public required IReadOnlyList<CanonicalRestOption> Options { get; init; }
    [JsonPropertyName("selected")] public required bool Selected { get; init; }
}

[CanonicalSchemaDefinition("rest_option")]
public sealed record CanonicalRestOption
{
    [JsonPropertyName("option_id")] public required string OptionId { get; init; }
    [JsonPropertyName("enabled")] public required bool Enabled { get; init; }
    [JsonPropertyName("implementation")] public required string Implementation { get; init; }
}

[CanonicalSchemaDefinition("event")]
public sealed record CanonicalEvent
{
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
    [JsonPropertyName("options")] public required IReadOnlyList<CanonicalEventOption> Options { get; init; }
    [JsonPropertyName("finished")] public required bool Finished { get; init; }
}

[CanonicalSchemaDefinition("event_option")]
public sealed record CanonicalEventOption
{
    [JsonPropertyName("option_index")] public required int OptionIndex { get; init; }
    [JsonPropertyName("text_key")] public required string TextKey { get; init; }
    [JsonPropertyName("locked")] public required bool Locked { get; init; }
    [JsonPropertyName("chosen")] public required bool Chosen { get; init; }
    [JsonPropertyName("is_proceed")] public required bool IsProceed { get; init; }
    [JsonPropertyName("relic_model_id")] public string? RelicModelId { get; init; }
}

[CanonicalSchemaDefinition("treasure")]
public sealed record CanonicalTreasure
{
    [JsonPropertyName("opened")] public required bool Opened { get; init; }
    [JsonPropertyName("resolved")] public required bool Resolved { get; init; }
    [JsonPropertyName("relic_options")] public required IReadOnlyList<CanonicalTreasureOption> RelicOptions { get; init; }
}

[CanonicalSchemaDefinition("treasure_option")]
public sealed record CanonicalTreasureOption
{
    [JsonPropertyName("option_index")] public required int OptionIndex { get; init; }
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
}

[CanonicalSchemaDefinition("shop")]
public sealed record CanonicalShop
{
    [JsonPropertyName("entries")] public required IReadOnlyList<CanonicalShopEntry> Entries { get; init; }
}

[CanonicalSchemaDefinition("shop_entry")]
public sealed record CanonicalShopEntry
{
    [JsonPropertyName("entry_index")] public required int EntryIndex { get; init; }
    [JsonPropertyName("kind")] public required string Kind { get; init; }
    [JsonPropertyName("model_id")] public string? ModelId { get; init; }
    [JsonPropertyName("cost")] public required int Cost { get; init; }
    [JsonPropertyName("stocked")] public required bool Stocked { get; init; }
    [JsonPropertyName("enough_gold")] public required bool EnoughGold { get; init; }
}

[CanonicalSchemaDefinition("room_rewards")]
public sealed record CanonicalRoomRewards
{
    [JsonPropertyName("rewards")] public required IReadOnlyList<CanonicalRoomReward> Rewards { get; init; }
}

[CanonicalSchemaDefinition("room_reward")]
public sealed record CanonicalRoomReward
{
    [JsonPropertyName("reward_index")] public required int RewardIndex { get; init; }
    [JsonPropertyName("kind")] public required string Kind { get; init; }
    [JsonPropertyName("options")] public required IReadOnlyList<CanonicalModelOption> Options { get; init; }
    [JsonPropertyName("resolved")] public required bool Resolved { get; init; }
}

[CanonicalSchemaDefinition("model_option")]
public sealed record CanonicalModelOption
{
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
}

[CanonicalSchemaDefinition("custom_rewards")]
public sealed record CanonicalCustomRewards
{
    [JsonPropertyName("rewards")] public required IReadOnlyList<CanonicalCustomRewardEntry> Rewards { get; init; }
    [JsonPropertyName("can_skip")] public required bool CanSkip { get; init; }
    [JsonPropertyName("depth")] public required int Depth { get; init; }
}

[CanonicalSchemaDefinition("custom_reward_entry")]
public sealed record CanonicalCustomRewardEntry
{
    [JsonPropertyName("reward_index")] public required int RewardIndex { get; init; }
    [JsonPropertyName("reward")] public required CanonicalCustomReward Reward { get; init; }
    [JsonPropertyName("children")] public required IReadOnlyList<CanonicalCustomReward> Children { get; init; }
}

[CanonicalSchemaDefinition("custom_reward")]
public sealed record CanonicalCustomReward
{
    [JsonPropertyName("kind")] public required string Kind { get; init; }
    [JsonPropertyName("model_id")] public string? ModelId { get; init; }
    [JsonPropertyName("implementation")] public required string Implementation { get; init; }
    [JsonPropertyName("selected")] public required bool Selected { get; init; }
}

[CanonicalSchemaDefinition("choice")]
public sealed record CanonicalChoice
{
    [JsonPropertyName("choice_id")] public required string ChoiceId { get; init; }
    [JsonPropertyName("kind")] public required string Kind { get; init; }
    [JsonPropertyName("min_select")] public required int MinSelect { get; init; }
    [JsonPropertyName("max_select")] public required int MaxSelect { get; init; }
    [JsonPropertyName("provenance")] public required string Provenance { get; init; }
    [JsonPropertyName("options")] public required IReadOnlyList<CanonicalChoiceOption> Options { get; init; }
}

[CanonicalSchemaOneOf(typeof(CanonicalModelChoiceOption), typeof(CanonicalBundleChoiceOption))]
[JsonConverter(typeof(CanonicalChoiceOptionJsonConverter))]
public abstract record CanonicalChoiceOption;

[CanonicalSchemaDefinition("model_choice_option")]
public sealed record CanonicalModelChoiceOption : CanonicalChoiceOption
{
    [JsonPropertyName("option_id")] public required string OptionId { get; init; }
    [JsonPropertyName("model_id")] public required string ModelId { get; init; }
}

[CanonicalSchemaDefinition("bundle_choice_option")]
public sealed record CanonicalBundleChoiceOption : CanonicalChoiceOption
{
    [JsonPropertyName("option_id")] public required string OptionId { get; init; }
    [JsonPropertyName("cards")] public required IReadOnlyList<CanonicalModelOption> Cards { get; init; }
}

[CanonicalSchemaDefinition("decision")]
public sealed record CanonicalDecision
{
    [JsonPropertyName("kind")] public required string Kind { get; init; }
    [JsonPropertyName("legal_actions")] public required IReadOnlyList<CanonicalLegalAction> LegalActions { get; init; }
}

[CanonicalSchemaDefinition("legal_action")]
public sealed record CanonicalLegalAction
{
    [JsonPropertyName("action_id")] public required string ActionId { get; init; }
    [JsonPropertyName("kind")] public required string Kind { get; init; }
    [JsonPropertyName("parameters")] public required IReadOnlyDictionary<string, JsonElement> Parameters { get; init; }
}
