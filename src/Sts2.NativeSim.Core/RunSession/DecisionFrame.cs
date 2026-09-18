using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.RunSession;

/// <summary>
/// One coherent projection of the active run decision. Callers never combine an observation from
/// one native state with the actions or terminal status from another.
/// </summary>
internal sealed record DecisionFrame(
    object Observation,
    IReadOnlyList<LegalAction> LegalActions,
    bool Terminated,
    bool Victory,
    object KernelProjection,
    object? ScoringFeatures);

