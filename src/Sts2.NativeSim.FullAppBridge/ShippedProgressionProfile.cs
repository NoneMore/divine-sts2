using System.Reflection;
using HarmonyLib;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Timeline;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// Adapts the project's progression-complete policy to the shipped game's progress APIs.
/// The policy owns only gameplay progression semantics; career totals, achievements, run saves,
/// profiles, and multiplayer session state never enter its snapshot or its mutations.
/// </summary>
public static class ShippedProgressionProfile
{
    public static string MaterializeMissing(ProgressState progress)
    {
        foreach (CardModel card in ModelDb.AllCards) progress.MarkCardAsSeen(card.Id);
        foreach (RelicModel relic in ModelDb.AllRelics) progress.MarkRelicAsSeen(relic.Id);
        foreach (PotionModel potion in ModelDb.AllPotions) progress.MarkPotionAsSeen(potion.Id);

        foreach (MonsterModel monster in ModelDb.Monsters)
        {
            EnemyStats stats = progress.GetOrCreateEnemyStats(monster.Id);
            if (stats.FightStats.Count != 0) continue;
            foreach (CharacterModel character in ModelDb.AllCharacters)
            {
                stats.FightStats.Add(new FightStats { Character = character.Id });
            }
        }

        foreach (EncounterModel encounter in ModelDb.AllEncounters)
        {
            EncounterStats stats = progress.GetOrCreateEncounterStats(encounter.Id);
            if (stats.FightStats.Count != 0) continue;
            foreach (CharacterModel character in ModelDb.AllCharacters)
            {
                stats.FightStats.Add(new FightStats { Character = character.Id });
            }
        }

        foreach (string epochId in EpochModel.AllEpochIds)
        {
            progress.ObtainEpochOverride(epochId, (EpochState)ProgressionCompletePolicy.RevealedEpochState);
        }
        foreach (ActModel act in ModelDb.Acts) progress.MarkActAsSeen(act.Id);
        foreach (EventModel gameEvent in ModelDb.AllEvents) progress.MarkEventAsSeen(gameEvent.Id);

        progress.PendingCharacterUnlock = ModelId.none;
        foreach (CharacterModel character in ModelDb.AllCharacters.Append(ModelDb.Character<RandomCharacter>()))
        {
            CharacterStats stats = progress.GetOrCreateCharacterStats(character.Id);
            stats.MaxAscension = ProgressionCompletePolicy.MaximumAscension;
            stats.PreferredAscension = ProgressionCompletePolicy.MaximumAscension;
        }
        progress.MaxMultiplayerAscension = ProgressionCompletePolicy.MaximumAscension;
        progress.PreferredMultiplayerAscension = ProgressionCompletePolicy.MaximumAscension;

        PropertyInfo totalUnlocks = AccessTools.Property(typeof(ProgressState), nameof(ProgressState.TotalUnlocks))
            ?? throw new MissingMemberException(typeof(ProgressState).FullName, nameof(ProgressState.TotalUnlocks));
        totalUnlocks.SetValue(progress, ProgressionCompletePolicy.TotalUnlockCount);

        progress.EnableFtues = false;
        foreach (string tutorial in ProgressionCompletePolicy.CompletedTutorials)
        {
            progress.MarkFtueAsComplete(tutorial);
        }

        string fingerprint = ProgressionCompletePolicy.Validate(Catalog(), Snapshot(progress));
        return fingerprint;
    }

    public static string ValidateExisting(ProgressState progress) =>
        ProgressionCompletePolicy.Validate(Catalog(), Snapshot(progress));

    public static ProgressionSemanticProfile Snapshot(ProgressState progress)
    {
        return new ProgressionSemanticProfile
        {
            DiscoveredCards = Entries(progress.DiscoveredCards),
            DiscoveredRelics = Entries(progress.DiscoveredRelics),
            DiscoveredPotions = Entries(progress.DiscoveredPotions),
            DiscoveredActs = Entries(progress.DiscoveredActs),
            DiscoveredEvents = Entries(progress.DiscoveredEvents),
            EnemyStatisticRows = progress.EnemyStats.Values.SelectMany(
                stats => stats.FightStats.Select(row => $"{stats.Id!.Entry}|{row.Character!.Entry}")).ToArray(),
            EncounterStatisticRows = progress.EncounterStats.Values.SelectMany(
                stats => stats.FightStats.Select(row => $"{stats.Id!.Entry}|{row.Character!.Entry}")).ToArray(),
            Epochs = progress.Epochs.Select(
                epoch => new ProgressionEpoch(epoch.Id, (int)epoch.State, epoch.ObtainDate)).ToArray(),
            CharacterAscension = progress.CharacterStats.Values.ToDictionary(
                stats => stats.Id!.Entry,
                stats => new ProgressionAscension(stats.MaxAscension, stats.PreferredAscension),
                StringComparer.Ordinal),
            PendingCharacterUnlock = progress.PendingCharacterUnlock.ToString(),
            MaximumMultiplayerAscension = progress.MaxMultiplayerAscension,
            PreferredMultiplayerAscension = progress.PreferredMultiplayerAscension,
            TotalUnlocks = progress.TotalUnlocks,
            TutorialsEnabled = progress.EnableFtues,
            CompletedTutorials = progress.FtueCompleted.ToArray(),
        };
    }

    private static ProgressionCatalog Catalog() => new(
        Entries(ModelDb.AllCards.Select(model => model.Id)),
        Entries(ModelDb.AllRelics.Select(model => model.Id)),
        Entries(ModelDb.AllPotions.Select(model => model.Id)),
        Entries(ModelDb.Monsters.Select(model => model.Id)),
        Entries(ModelDb.AllEncounters.Select(model => model.Id)),
        Entries(ModelDb.Acts.Select(model => model.Id)),
        Entries(ModelDb.AllEvents.Select(model => model.Id)),
        EpochModel.AllEpochIds.ToArray(),
        Entries(ModelDb.AllCharacters.Select(model => model.Id)),
        ModelDb.Character<RandomCharacter>().Id.Entry);

    private static string[] Entries(IEnumerable<ModelId> ids) => ids.Select(id => id.Entry).ToArray();
}
