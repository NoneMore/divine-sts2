using System.Text.Json;
using Sts2.NativeSim.Core;
using Sts2.NativeSim.Core.RunSession;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.Tests;

internal sealed class ScriptedNativeRunAdapter : IRunSessionCompatibilityAdapter
{
    private readonly Dictionary<string, ScriptedFrame> _frames = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Frame, string Action), string> _transitions = new();
    private readonly HashSet<(string Frame, string Action)> _errorsAfterMutation = [];
    private readonly Dictionary<string, string> _branches = new(StringComparer.Ordinal);
    private readonly string _resetFrame;
    private string _currentFrame;
    private int _checkpointOrdinal;

    public ScriptedNativeRunAdapter(string resetFrame)
    {
        _resetFrame = resetFrame;
        _currentFrame = resetFrame;
    }

    public int MutationCount { get; private set; }
    public TimeSpan ApplyDelay { get; init; }

    public ScriptedNativeRunAdapter Frame(string name, string observation, params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(document.RootElement.Clone(), Kernel(name), actions));
        return this;
    }

    public ScriptedNativeRunAdapter Transition(string from, string actionId, string to)
    {
        _transitions.Add((from, actionId), to);
        return this;
    }

    public ScriptedNativeRunAdapter ErrorAfterMutation(string from, string actionId)
    {
        _errorsAfterMutation.Add((from, actionId));
        return this;
    }

    public CompatibilityCapture Reset(ResetRequest request)
    {
        _currentFrame = _resetFrame;
        return Capture();
    }

    public CompatibilityCapture Capture()
    {
        ScriptedFrame frame = _frames[_currentFrame];
        return Result(frame);
    }

    public async Task<CompatibilityCapture> ApplyAsync(string actionId)
    {
        if (ApplyDelay > TimeSpan.Zero) await Task.Delay(ApplyDelay);
        string nextFrame = _transitions[(_currentFrame, actionId)];
        ScriptedFrame next = _frames[nextFrame];
        CompatibilityCapture result = Result(next);
        MutationCount++;
        string previousFrame = _currentFrame;
        _currentFrame = nextFrame;
        if (_errorsAfterMutation.Contains((previousFrame, actionId)))
            throw new ProtocolException("scripted_native_error", "The scripted native adapter failed after mutation.");
        return result;
    }

    public object CaptureCheckpoint()
    {
        string checkpoint = $"checkpoint-{++_checkpointOrdinal}";
        _branches.Add(checkpoint, _currentFrame);
        return checkpoint;
    }

    public Task<CompatibilityCapture> RestoreAsync(object checkpoint)
    {
        _currentFrame = _branches[(string)checkpoint];
        return Task.FromResult(Capture());
    }

    private static CompatibilityCapture Result(ScriptedFrame frame) => new(
        new(frame.Observation, frame.Actions, false, false, frame.KernelProjection, null));

    private static object Kernel(string frame) => new
    {
        run_mode = true,
        run_stage = frame is "map" or "route" ? "map" : frame == "combat" ? "combat" : "event",
        map_mode = false,
        reward_mode = false,
        reward_kind = "card",
        reward_model_id = (string?)null,
        rest_mode = false,
        event_mode = frame is not ("map" or "route" or "combat"),
        event_id = (string?)null,
        custom_reward_mode = false,
        custom_rewards_linked = false,
        custom_reward_kinds = Array.Empty<string>()
    };

    private sealed record ScriptedFrame(JsonElement Observation, object KernelProjection, IReadOnlyList<LegalAction> Actions);
}
