namespace Sts2.NativeSim.Core;

/// <summary>
/// First-class initialization provenance for a worker. Reset RPCs, resident restore, and
/// portable replay all dispatch on this single value instead of inferring the reconstruction
/// path from a combination of mode booleans, so an unknown or contradictory mode fails loudly
/// rather than silently degrading to a direct combat reset.
/// </summary>
public enum ResetMode
{
    /// <summary>Direct combat reset: run construction followed by combat construction.</summary>
    Combat,
    /// <summary>Map-only reset: direct construction plus native act-map generation.</summary>
    Map,
    /// <summary>Composed run reset: run construction plus native rooms and act map, no combat.</summary>
    Run,
    /// <summary>
    /// Faithful run-start reset: run construction from the pinned unlock profile plus native
    /// rooms and act map, then the shipped starting Ancient (Neow) event room. Neow is resolved
    /// through shipped option/nested-choice machinery before the first map decision appears.
    /// </summary>
    NeowRun,
    /// <summary>Card reward reset.</summary>
    CardReward,
    /// <summary>Item (relic or potion) reward reset.</summary>
    ItemReward,
    /// <summary>Custom or linked reward reset.</summary>
    CustomReward,
    /// <summary>Rest-site reset.</summary>
    Rest,
    /// <summary>Standalone event reset.</summary>
    Event
}

/// <summary>
/// Wire names for <see cref="ResetMode"/>. Provenance crosses the protocol as a stable
/// snake_case string inside `diagnostics`, branch identities, and portable branch records, so
/// every direction is explicit and an unrecognized name is a protocol error.
/// </summary>
public static class ResetModes
{
    private static readonly Dictionary<ResetMode, string> Names = new()
    {
        [ResetMode.Combat] = "combat",
        [ResetMode.Map] = "map",
        [ResetMode.Run] = "run",
        [ResetMode.NeowRun] = "neow_run",
        [ResetMode.CardReward] = "card_reward",
        [ResetMode.ItemReward] = "item_reward",
        [ResetMode.CustomReward] = "custom_reward",
        [ResetMode.Rest] = "rest",
        [ResetMode.Event] = "event"
    };

    public static string Wire(this ResetMode mode) => Names.TryGetValue(mode, out string? name)
        ? name
        : throw new ProtocolException("unknown_reset_mode", $"Reset mode '{mode}' has no wire name.");

    public static ResetMode Parse(string? name) => TryParse(name, out ResetMode mode)
        ? mode
        : throw new ProtocolException("unknown_reset_mode", $"Unknown reset mode '{name ?? "<null>"}'.", new { supported = Names.Values.Order(StringComparer.Ordinal).ToArray() });

    public static bool TryParse(string? name, out ResetMode mode)
    {
        foreach ((ResetMode candidate, string wire) in Names)
        {
            if (StringComparer.Ordinal.Equals(wire, name))
            {
                mode = candidate;
                return true;
            }
        }
        mode = default;
        return false;
    }
}
