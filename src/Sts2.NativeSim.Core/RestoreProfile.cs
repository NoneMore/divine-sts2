using System.Diagnostics;
using System.Text.Json.Serialization;

namespace Sts2.NativeSim.Core;

/// <summary>
/// Where one restore spent its time, timed where each part happened rather than inferred from the
/// total. The parts are the ones a restore's own code can name: the resident-prefix check that
/// decides whether anything has to happen at all, the run it rebuilt, the room it rebuilt, the action
/// history it replayed, the combat snapshot it restored, and the capture that closes it. Whatever the
/// named parts leave over is reported as <see cref="UnattributedMs"/>, so the parts and the residue
/// add up to the total by construction instead of by a reader's assumption.
///
/// A profile is a wall-clock measurement of one call, so it is <em>recorded</em> only when the worker
/// is started with <c>STS2_RESTORE_PROFILE=1</c>; with the switch off the only cost is a handful of
/// clock reads per restore (tens of nanoseconds against a call that costs milliseconds), and no part
/// is reported at all. Where it is reported is the restore's transition — never a corpus, and never a
/// row or a summary (ADR-0008).
///
/// <see cref="TotalMs"/> is the environment's own span for the restore. The same transition also
/// carries the coordinator's wider <c>elapsed_ms</c>, which includes the projection and hashing done
/// after the environment returns; a reader that wants the whole call measures it from the outside.
/// </summary>
internal sealed class RestoreProfile
{
    /// <summary>The one switch that turns profiling on, read once rather than at every call site.</summary>
    private const string EnvironmentVariable = "STS2_RESTORE_PROFILE";

    internal static bool Enabled { get; } = StringComparer.Ordinal.Equals(
        System.Environment.GetEnvironmentVariable(EnvironmentVariable), "1");

    /// <summary>A profile for a restore that is about to run, or null when profiling is off.</summary>
    internal static RestoreProfile? Begin() => Enabled ? new RestoreProfile() : null;

    /// <summary>A timestamp to measure one part from, in the clock <see cref="Since"/> reads.</summary>
    internal static long Tick() => Stopwatch.GetTimestamp();

    /// <summary>The milliseconds between one <see cref="Tick"/> and now.</summary>
    internal static double Since(long startedAt) =>
        (Stopwatch.GetTimestamp() - startedAt) * 1000.0 / Stopwatch.Frequency;

    /// <summary>Comparing the current state with the one asked for, which decides the whole path.</summary>
    [JsonPropertyName("resident_check_ms")] public double? ResidentCheckMs { get; set; }

    /// <summary>Rebuilding the run: the player, deck, relics and act, before any room is entered.</summary>
    [JsonPropertyName("run_rebuild_ms")] public double? RunRebuildMs { get; set; }

    /// <summary>Regenerating the act a run-mode recipe stands on: its rooms and its map.</summary>
    [JsonPropertyName("map_rebuild_ms")] public double? MapRebuildMs { get; set; }

    /// <summary>Rebuilding the room any other reset kind stands in, which is its own construction.</summary>
    [JsonPropertyName("mode_init_ms")] public double? ModeInitMs { get; set; }

    /// <summary>Replaying the checkpoint's action history onto the rebuilt run.</summary>
    [JsonPropertyName("replay_ms")] public double? ReplayMs { get; set; }

    /// <summary>Restoring the combat snapshot a combat-mode checkpoint carries.</summary>
    [JsonPropertyName("snapshot_ms")] public double? SnapshotMs { get; set; }

    /// <summary>Capturing the restored state: its observation, its legal actions and its hash.</summary>
    [JsonPropertyName("capture_ms")] public double? CaptureMs { get; set; }

    /// <summary>The whole restore inside the environment, from the branch lookup to the last capture.</summary>
    [JsonPropertyName("total_ms")] public double? TotalMs { get; set; }

    /// <summary>The part of <see cref="TotalMs"/> no named part accounts for.</summary>
    [JsonPropertyName("unattributed_ms")] public double? UnattributedMs { get; set; }

    // A part accumulates rather than overwrites: one restore can attempt a step twice — a snapshot
    // whose hash did not match falls through to a reconstruction — and both attempts are time the
    // restore spent, so neither may be dropped into the residue.

    internal void RecordResidentCheck(long startedAt) => ResidentCheckMs = Add(ResidentCheckMs, startedAt);
    internal void RecordRunRebuild(long startedAt) => RunRebuildMs = Add(RunRebuildMs, startedAt);
    internal void RecordMapRebuild(long startedAt) => MapRebuildMs = Add(MapRebuildMs, startedAt);
    internal void RecordModeInit(long startedAt) => ModeInitMs = Add(ModeInitMs, startedAt);
    internal void RecordReplay(long startedAt) => ReplayMs = Add(ReplayMs, startedAt);
    internal void RecordSnapshot(long startedAt) => SnapshotMs = Add(SnapshotMs, startedAt);
    internal void RecordCapture(long startedAt) => CaptureMs = Add(CaptureMs, startedAt);

    /// <summary>Closes a profile: the total is the whole restore and the residue is what it left.</summary>
    internal void Close(long startedAt)
    {
        TotalMs = Since(startedAt);
        double named = (ResidentCheckMs ?? 0) + (RunRebuildMs ?? 0) + (MapRebuildMs ?? 0)
            + (ModeInitMs ?? 0) + (ReplayMs ?? 0) + (SnapshotMs ?? 0) + (CaptureMs ?? 0);
        UnattributedMs = Math.Max(0, TotalMs.Value - named);
    }

    private static double Add(double? recorded, long startedAt) => (recorded ?? 0) + Since(startedAt);
}
