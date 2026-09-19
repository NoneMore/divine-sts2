namespace Sts2.NativeSim.Core.RunSession;

internal enum SimpleRoomKind
{
    Rest,
    Treasure,
    Shop
}

internal static class SimpleRoomKindExtensions
{
    private static readonly IReadOnlyDictionary<SimpleRoomKind, SimpleRoomDescription> Descriptions =
        new Dictionary<SimpleRoomKind, SimpleRoomDescription>
        {
            [SimpleRoomKind.Rest] = new("rest", ["choose_rest", "leave_rest"]),
            [SimpleRoomKind.Treasure] = new(
                "treasure",
                ["open_treasure", "choose_treasure", "skip_treasure", "leave_treasure"]),
            [SimpleRoomKind.Shop] = new("shop", ["buy_shop", "leave_shop"])
        };

    public static string Stage(this SimpleRoomKind room) => Describe(room).Stage;

    public static bool Owns(this SimpleRoomKind room, string actionKind) =>
        Describe(room).ActionKinds.Contains(actionKind, StringComparer.Ordinal);

    private static SimpleRoomDescription Describe(SimpleRoomKind room)
    {
        if (Descriptions.TryGetValue(room, out SimpleRoomDescription? description)) return description;
        throw new ArgumentOutOfRangeException(nameof(room), room, null);
    }

    private sealed record SimpleRoomDescription(string Stage, IReadOnlyList<string> ActionKinds);
}

internal sealed record RestSelection(string OptionId);
internal sealed record TreasureSelection(int? OptionIndex);
internal sealed record ShopSelection(int EntryIndex);
