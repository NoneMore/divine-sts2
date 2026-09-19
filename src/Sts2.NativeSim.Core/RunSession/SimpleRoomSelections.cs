namespace Sts2.NativeSim.Core.RunSession;

internal enum SimpleRoomKind
{
    Rest,
    Treasure,
    Shop
}

internal static class SimpleRoomKindExtensions
{
    public static string Stage(this SimpleRoomKind room) => room switch
    {
        SimpleRoomKind.Rest => "rest",
        SimpleRoomKind.Treasure => "treasure",
        SimpleRoomKind.Shop => "shop",
        _ => throw new ArgumentOutOfRangeException(nameof(room), room, null)
    };

    public static bool Owns(this SimpleRoomKind room, string actionKind) => room switch
    {
        SimpleRoomKind.Rest => actionKind is "choose_rest" or "leave_rest",
        SimpleRoomKind.Treasure => actionKind is
            "open_treasure" or "choose_treasure" or "skip_treasure" or "leave_treasure",
        SimpleRoomKind.Shop => actionKind is "buy_shop" or "leave_shop",
        _ => false
    };
}

internal sealed record RestSelection(string OptionId);
internal sealed record TreasureSelection(int? OptionIndex);
internal sealed record ShopSelection(int EntryIndex);
