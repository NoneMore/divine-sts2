using Sts2.NativeSim.Protocol;
using Xunit;

namespace Sts2.NativeSim.Protocol.Tests;

public sealed class ProgressionCompletePolicyTests
{
    private static readonly ProgressionCatalog Catalog = new(
        Cards: ["CARD.B", "CARD.A"],
        Relics: ["RELIC.A"],
        Potions: ["POTION.A"],
        Monsters: ["MONSTER.A"],
        Encounters: ["ENCOUNTER.A"],
        Acts: ["ACT.B", "ACT.A"],
        Events: ["EVENT.A"],
        Epochs: ["epoch_b", "epoch_a"],
        Characters: ["CHARACTER.IRONCLAD", "CHARACTER.DEFECT"],
        RandomCharacter: "CHARACTER.RANDOM");

    [Fact]
    public void Missing_progress_materializes_the_progression_complete_baseline()
    {
        ProgressionSemanticProfile profile = ProgressionCompletePolicy.Materialize(Catalog);

        Assert.Equal(["ACT.A", "ACT.B"], profile.DiscoveredActs);
        Assert.Equal(["CARD.A", "CARD.B"], profile.DiscoveredCards);
        Assert.Equal(["MONSTER.A|CHARACTER.DEFECT", "MONSTER.A|CHARACTER.IRONCLAD"], profile.EnemyStatisticRows);
        Assert.Equal(["ENCOUNTER.A|CHARACTER.DEFECT", "ENCOUNTER.A|CHARACTER.IRONCLAD"], profile.EncounterStatisticRows);
        Assert.All(profile.Epochs, epoch => Assert.Equal(ProgressionCompletePolicy.RevealedEpochState, epoch.State));
        Assert.Equal(10, profile.CharacterAscension["CHARACTER.RANDOM"].Maximum);
        Assert.Equal(10, profile.CharacterAscension["CHARACTER.RANDOM"].Preferred);
        Assert.Equal(ProgressionCompletePolicy.NoPendingCharacterUnlock, profile.PendingCharacterUnlock);
        Assert.Equal(10, profile.MaximumMultiplayerAscension);
        Assert.Equal(10, profile.PreferredMultiplayerAscension);
        Assert.Equal(18, profile.TotalUnlocks);
        Assert.False(profile.TutorialsEnabled);
        Assert.Equal(ProgressionCompletePolicy.CompletedTutorials, profile.CompletedTutorials);
    }

    [Fact]
    public void Fingerprint_is_idempotent_and_ignores_non_semantic_metadata()
    {
        ProgressionSemanticProfile first = ProgressionCompletePolicy.Materialize(Catalog);
        ProgressionSemanticProfile reordered = first with
        {
            DiscoveredCards = first.DiscoveredCards.Reverse().ToArray(),
            Epochs = first.Epochs.Reverse().Select(epoch => epoch with { ObtainDate = 1_999_999_999 }).ToArray(),
        };

        string firstFingerprint = ProgressionCompletePolicy.Fingerprint(first);
        string secondFingerprint = ProgressionCompletePolicy.Fingerprint(reordered);

        Assert.Equal(firstFingerprint, secondFingerprint);
        Assert.Equal(64, firstFingerprint.Length);
        Assert.Equal("8d76da28b9165d348598f5c03844ae6f3805bc7155f4110e90c7fe381c85fc00", firstFingerprint);
    }

    [Fact]
    public void Stored_preferences_do_not_change_the_semantic_fingerprint()
    {
        ProgressionSemanticProfile baseline = ProgressionCompletePolicy.Materialize(Catalog);
        ProgressionSemanticProfile changedPreferences = baseline with
        {
            CharacterAscension = baseline.CharacterAscension.ToDictionary(
                pair => pair.Key,
                pair => pair.Value with { Preferred = 0 },
                StringComparer.Ordinal),
            PreferredMultiplayerAscension = 0,
        };

        Assert.Equal(
            ProgressionCompletePolicy.Fingerprint(baseline),
            ProgressionCompletePolicy.Fingerprint(changedPreferences));
    }

    [Fact]
    public void Existing_progress_with_semantic_drift_fails_closed()
    {
        ProgressionSemanticProfile drifted = ProgressionCompletePolicy.Materialize(Catalog) with
        {
            DiscoveredActs = ["ACT.A"],
        };

        ProgressionBaselineMismatchException error = Assert.Throws<ProgressionBaselineMismatchException>(
            () => ProgressionCompletePolicy.Validate(Catalog, drifted));

        Assert.Contains("expected", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("actual", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Pending_character_unlock_is_semantic_drift()
    {
        ProgressionSemanticProfile drifted = ProgressionCompletePolicy.Materialize(Catalog) with
        {
            PendingCharacterUnlock = "CHARACTER.SILENT",
        };

        Assert.Throws<ProgressionBaselineMismatchException>(() => ProgressionCompletePolicy.Validate(Catalog, drifted));
    }
}
