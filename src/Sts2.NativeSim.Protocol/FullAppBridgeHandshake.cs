namespace Sts2.NativeSim.Protocol;

/// <summary>The progression-gated portion of the full-app bridge's public RPC surface.</summary>
public static class FullAppBridgeHandshake
{
    public static IReadOnlyDictionary<string, object?> CreateHello(
        ProgressionReadinessSnapshot readiness,
        Func<object> gameBuild,
        int pid,
        int boundPort,
        string processMode)
    {
        var hello = new Dictionary<string, object?>
        {
            ["status"] = readiness.Status,
            ["pid"] = pid,
            ["bound_port"] = boundPort,
            ["unlock_policy"] = "all",
            ["progression_policy"] = ProgressionCompletePolicy.Revision,
            ["process_mode"] = processMode,
        };
        if (readiness.State == ProgressionReadinessState.Ready)
        {
            hello["profile_fingerprint"] = readiness.ProfileFingerprint;
            hello["game_build"] = gameBuild();
        }
        else if (readiness.State == ProgressionReadinessState.Failed)
        {
            hello["error"] = readiness.FailureMessage;
        }
        return hello;
    }

    public static void EnsureCanStart(ProgressionReadiness readiness) => readiness.EnsureReadyForStart();
}
