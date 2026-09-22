using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Sts2.NativeSim.Protocol;

public sealed record ProgressionCatalog(
    IReadOnlyCollection<string> Cards,
    IReadOnlyCollection<string> Relics,
    IReadOnlyCollection<string> Potions,
    IReadOnlyCollection<string> Monsters,
    IReadOnlyCollection<string> Encounters,
    IReadOnlyCollection<string> Acts,
    IReadOnlyCollection<string> Events,
    IReadOnlyCollection<string> Epochs,
    IReadOnlyCollection<string> Characters,
    string RandomCharacter);

public sealed record ProgressionAscension(int Maximum, int Preferred);

public sealed record ProgressionEpoch(string Id, int State, long? ObtainDate = null);

public sealed record ProgressionSemanticProfile
{
    public required IReadOnlyList<string> DiscoveredCards { get; init; }
    public required IReadOnlyList<string> DiscoveredRelics { get; init; }
    public required IReadOnlyList<string> DiscoveredPotions { get; init; }
    public required IReadOnlyList<string> DiscoveredActs { get; init; }
    public required IReadOnlyList<string> DiscoveredEvents { get; init; }
    public required IReadOnlyList<string> EnemyStatisticRows { get; init; }
    public required IReadOnlyList<string> EncounterStatisticRows { get; init; }
    public required IReadOnlyList<ProgressionEpoch> Epochs { get; init; }
    public required IReadOnlyDictionary<string, ProgressionAscension> CharacterAscension { get; init; }
    public required string PendingCharacterUnlock { get; init; }
    public required int MaximumMultiplayerAscension { get; init; }
    public required int PreferredMultiplayerAscension { get; init; }
    public required int TotalUnlocks { get; init; }
    public required bool TutorialsEnabled { get; init; }
    public required IReadOnlyList<string> CompletedTutorials { get; init; }
}

public sealed class ProgressionBaselineMismatchException(string message) : InvalidOperationException(message);

public static class ProgressionCompletePolicy
{
    public const string Revision = "progression-complete-v1";
    public const int RevealedEpochState = 5;
    public const int MaximumAscension = 10;
    public const int TotalUnlockCount = 18;
    public const string NoPendingCharacterUnlock = "NONE.NONE";

    public static readonly IReadOnlyList<string> CompletedTutorials =
    [
        "accept_tutorials_ftue",
        "ascension_multiplayer_ftue",
        "ascension_singleplayer_ftue",
        "can_play_cards_ftue",
        "cannot_play_card_ftue",
        "combat_reward_ftue",
        "combat_rules_ftue",
        "map_select_ftue",
        "merchant_ftue",
        "multiplayer_warning",
        "obtain_potion_ftue",
        "obtain_relic_ftue",
        "power_card_ftue",
        "rest_site_ftue",
        "shuffle_ftue",
    ];

    public static ProgressionSemanticProfile Materialize(ProgressionCatalog catalog)
    {
        string[] characters = catalog.Characters.Append(catalog.RandomCharacter).Order(StringComparer.Ordinal).ToArray();
        return new ProgressionSemanticProfile
        {
            DiscoveredCards = Sorted(catalog.Cards),
            DiscoveredRelics = Sorted(catalog.Relics),
            DiscoveredPotions = Sorted(catalog.Potions),
            DiscoveredActs = Sorted(catalog.Acts),
            DiscoveredEvents = Sorted(catalog.Events),
            EnemyStatisticRows = CrossRows(catalog.Monsters, catalog.Characters),
            EncounterStatisticRows = CrossRows(catalog.Encounters, catalog.Characters),
            Epochs = catalog.Epochs.Select(id => new ProgressionEpoch(id, RevealedEpochState))
                .OrderBy(epoch => epoch.Id, StringComparer.Ordinal).ToArray(),
            CharacterAscension = characters.ToDictionary(
                character => character,
                _ => new ProgressionAscension(MaximumAscension, MaximumAscension),
                StringComparer.Ordinal),
            PendingCharacterUnlock = NoPendingCharacterUnlock,
            MaximumMultiplayerAscension = MaximumAscension,
            PreferredMultiplayerAscension = MaximumAscension,
            TotalUnlocks = TotalUnlockCount,
            TutorialsEnabled = false,
            CompletedTutorials = CompletedTutorials,
        };
    }

    public static string Fingerprint(ProgressionSemanticProfile profile)
    {
        ProgressionSemanticProfile normalized = Normalize(profile);
        // Preferred Ascension is a user preference, and the shipped lobby updates and persists it
        // when a caller requests a run. It is intentionally absent from the semantic projection:
        // maximum Ascension is the progression gate, while the request always wins over preference.
        var semanticProjection = new
        {
            policy = Revision,
            normalized.DiscoveredCards,
            normalized.DiscoveredRelics,
            normalized.DiscoveredPotions,
            normalized.DiscoveredActs,
            normalized.DiscoveredEvents,
            normalized.EnemyStatisticRows,
            normalized.EncounterStatisticRows,
            Epochs = normalized.Epochs.Select(epoch => new { epoch.Id, epoch.State }).ToArray(),
            CharacterMaximumAscension = normalized.CharacterAscension.ToDictionary(
                pair => pair.Key, pair => pair.Value.Maximum, StringComparer.Ordinal),
            normalized.PendingCharacterUnlock,
            normalized.MaximumMultiplayerAscension,
            normalized.TotalUnlocks,
            normalized.TutorialsEnabled,
            normalized.CompletedTutorials,
        };
        string json = JsonSerializer.Serialize(semanticProjection);
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(json)));
    }

    public static string Validate(ProgressionCatalog catalog, ProgressionSemanticProfile existing)
    {
        string expected = Fingerprint(Materialize(catalog));
        string actual = Fingerprint(existing);
        if (!StringComparer.Ordinal.Equals(expected, actual))
        {
            throw new ProgressionBaselineMismatchException(
                $"Existing full-app sandbox progress does not match the progression-complete baseline: expected {expected}, actual {actual}.");
        }
        return actual;
    }

    private static ProgressionSemanticProfile Normalize(ProgressionSemanticProfile profile) => profile with
    {
        DiscoveredCards = Sorted(profile.DiscoveredCards),
        DiscoveredRelics = Sorted(profile.DiscoveredRelics),
        DiscoveredPotions = Sorted(profile.DiscoveredPotions),
        DiscoveredActs = Sorted(profile.DiscoveredActs),
        DiscoveredEvents = Sorted(profile.DiscoveredEvents),
        EnemyStatisticRows = Sorted(profile.EnemyStatisticRows),
        EncounterStatisticRows = Sorted(profile.EncounterStatisticRows),
        Epochs = profile.Epochs.OrderBy(epoch => epoch.Id, StringComparer.Ordinal).ThenBy(epoch => epoch.State).ToArray(),
        CharacterAscension = profile.CharacterAscension.OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal),
        CompletedTutorials = Sorted(profile.CompletedTutorials),
    };

    private static string[] Sorted(IEnumerable<string> values) =>
        values.Order(StringComparer.Ordinal).ToArray();

    private static string[] CrossRows(IEnumerable<string> left, IEnumerable<string> right) =>
        left.SelectMany(first => right.Select(second => $"{first}|{second}"))
            .Order(StringComparer.Ordinal).ToArray();
}
