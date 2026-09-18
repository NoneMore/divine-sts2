using System.Text.Json;
using Sts2.NativeSim.Core;
using Sts2.NativeSim.Protocol;

namespace Sts2.NativeSim.Core.Tests;

internal sealed class ScriptedNativeRunAdapter : INativeRunAdapter
{
    private readonly Dictionary<string, ScriptedFrame> _frames = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Frame, string Action), string> _transitions = new();
    private readonly Dictionary<string, string> _branches = new(StringComparer.Ordinal);
    private readonly string _resetFrame;
    private string _currentFrame;
    private int _branchOrdinal;

    public ScriptedNativeRunAdapter(string resetFrame)
    {
        _resetFrame = resetFrame;
        _currentFrame = resetFrame;
    }

    public int MutationCount { get; private set; }

    public ScriptedNativeRunAdapter Frame(string name, string hash, string observation, params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse(observation);
        _frames.Add(name, new(document.RootElement.Clone(), hash, actions));
        return this;
    }

    public ScriptedNativeRunAdapter Transition(string from, string actionId, string to)
    {
        _transitions.Add((from, actionId), to);
        return this;
    }

    public EnvironmentResult RunReset(ResetRequest request)
    {
        _currentFrame = _resetFrame;
        return Capture();
    }

    public EnvironmentResult Capture()
    {
        ScriptedFrame frame = _frames[_currentFrame];
        return Result(_currentFrame, frame);
    }

    public Task<EnvironmentResult> ApplyAsync(string actionId)
    {
        string nextFrame = _transitions[(_currentFrame, actionId)];
        ScriptedFrame next = _frames[nextFrame];
        EnvironmentResult result = Result(nextFrame, next);
        NativeRunCoordinator.EnsureUnambiguous(result);
        MutationCount++;
        _currentFrame = nextFrame;
        return Task.FromResult(result);
    }

    public string Fork()
    {
        string handle = $"branch-{++_branchOrdinal}";
        _branches.Add(handle, _currentFrame);
        return handle;
    }

    public Task<EnvironmentResult> RestoreAsync(string stateHandle)
    {
        _currentFrame = _branches[stateHandle];
        return Task.FromResult(Capture());
    }

    public void Dispose() { }

    private static EnvironmentResult Result(string name, ScriptedFrame frame) =>
        new(frame.Observation, frame.Hash, frame.Actions, false, false, $"script:{name}");

    private sealed record ScriptedFrame(JsonElement Observation, string Hash, IReadOnlyList<LegalAction> Actions);
}
