using System.Text.Json;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.RunSession;

/// <summary>The sole temporary route from the active-session module to legacy run states.</summary>
internal sealed class LegacyRunSessionAdapter : IRunSessionCompatibilityAdapter
{
    private readonly PersistentNativeCombatEnvironment _environment;

    public LegacyRunSessionAdapter(PersistentNativeCombatEnvironment environment) => _environment = environment;

    public CompatibilityCapture Reset(ResetRequest request) => Capture(_environment.RunReset(request));
    public async Task<CompatibilityCapture> ApplyAsync(string actionId) =>
        Capture(await _environment.StepAsync(actionId).ConfigureAwait(false));
    public async Task<CompatibilityCapture> EnterMapPointAsync(MapPointSelection selection) =>
        Capture(await _environment.EnterMapPointAsync(selection).ConfigureAwait(false));
    public async Task<CompatibilityCapture> ResumeCardSelectAsync(
        PromptResumeToken parent,
        CardSelection selection) =>
        Capture(await _environment.ResumeCardSelectAsync(parent, selection).ConfigureAwait(false));
    public async Task<CompatibilityCapture> ResumeRewardAsync(
        PromptResumeToken parent,
        RewardSelection selection) =>
        Capture(await _environment.ResumeRewardAsync(parent, selection).ConfigureAwait(false));
    public object CaptureCheckpoint() => _environment.Fork();
    public async Task<CompatibilityCapture> RestoreAsync(object checkpoint) =>
        Capture(
            await _environment.RestoreAsync((string)checkpoint).ConfigureAwait(false),
            includeRestore: true);

    private CompatibilityCapture Capture(EnvironmentResult result, bool includeRestore = false)
    {
        DecisionFrame frame = new(
            result.Observation,
            result.LegalActions,
            result.Terminated,
            result.Victory,
            _environment.TransitionKernelProjection(),
            result.ScoringFeatures);
        string projectedHash = NativeRunCoordinator.ComputeStateHash(frame);
        if (!StringComparer.Ordinal.Equals(projectedHash, result.StateHash))
            throw new ProtocolException(
                "protocol_desync",
                $"The compatibility frame projected hash {projectedHash}, but the legacy state reported {result.StateHash}.");
        return new(
            frame,
            includeRestore ? RestoreProjection(result.Transition) : null,
            _environment.ActivePromptParent(),
            _environment.HasActiveMapDecision ? MapActions(frame.LegalActions) : null);
    }

    private static IReadOnlyDictionary<string, MapPointSelection> MapActions(
        IReadOnlyList<LegalAction> actions)
    {
        Dictionary<string, MapPointSelection> result = new(StringComparer.Ordinal);
        foreach (LegalAction action in actions)
            result.Add(action.ActionId, MapPointSelection.FromAction(action));
        return result;
    }

    private static CompatibilityRestore RestoreProjection(object? transition)
    {
        JsonElement value = JsonSerializer.SerializeToElement(transition);
        return new(
            value.GetProperty("kind").GetString()!,
            value.GetProperty("replayed_actions").GetInt32(),
            value.TryGetProperty("resident_prefix_hit", out JsonElement resident)
                ? resident.GetBoolean()
                : null);
    }
}
