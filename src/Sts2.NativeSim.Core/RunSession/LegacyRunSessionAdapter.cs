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
    public string Fork() => _environment.Fork();
    public async Task<CompatibilityCapture> RestoreAsync(string stateHandle) =>
        Capture(await _environment.RestoreAsync(stateHandle).ConfigureAwait(false));
    public void Retain(string stateHandle) { }

    private CompatibilityCapture Capture(EnvironmentResult result)
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
        return new(frame, result.Transition);
    }
}
