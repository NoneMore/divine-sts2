namespace Sts2.NativeSim.Core.RunSession;

internal enum SimpleRoomKind
{
    Rest,
    Treasure,
    Shop
}

internal sealed record RestSelection(string OptionId);
internal sealed record TreasureSelection(int? OptionIndex);
internal sealed record ShopSelection(int EntryIndex);
