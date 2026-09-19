using System.Text.Json;
using Sts2.NativeSim.Core.RunSession;
using Sts2.NativeSim.Protocol;
using Xunit;

namespace Sts2.NativeSim.Core.Tests;

public sealed class ActiveRunSessionTests
{
    [Fact]
    public void Current_frame_is_one_atomic_projection()
    {
        DecisionFrame expected = Frame(Action("continue"));
        RecordingCompatibilityAdapter adapter = new(expected);
        CompatibilityActiveRunSession session = new(adapter, new(expected));

        DecisionFrame current = session.Current;

        Assert.Same(expected.Observation, current.Observation);
        Assert.Equal("continue", Assert.Single(current.LegalActions).ActionId);
        Assert.False(current.Terminated);
        Assert.False(current.Victory);
        Assert.Same(expected.KernelProjection, current.KernelProjection);
    }

    [Fact]
    public async Task Apply_is_serial_and_validates_each_action_before_native_mutation()
    {
        RecordingCompatibilityAdapter adapter = new(Frame(Action("continue"))) { ApplyDelay = TimeSpan.FromMilliseconds(40) };
        CompatibilityActiveRunSession session = new(adapter, new(Frame(Action("continue"))));

        await Task.WhenAll(session.ApplyAsync("continue"), session.ApplyAsync("continue"));
        ProtocolException error = await Assert.ThrowsAsync<ProtocolException>(() => session.ApplyAsync("missing"));

        Assert.Equal("invalid_action", error.Code);
        Assert.Equal(2, adapter.MutationCount);
        Assert.Equal(1, adapter.MaximumConcurrentMutations);
    }

    [Fact]
    public async Task Failed_recovery_poisons_the_session_deterministically()
    {
        RecordingCompatibilityAdapter adapter = new(Frame(Action("break")))
        {
            ApplyFailure = new InvalidOperationException("native mutation failed"),
            RestoreFailure = new InvalidOperationException("native recovery failed")
        };
        CompatibilityActiveRunSession session = new(adapter, new(Frame(Action("break"))));

        ProtocolException first = await Assert.ThrowsAsync<ProtocolException>(() => session.ApplyAsync("break"));
        ProtocolException current = Assert.Throws<ProtocolException>(() => _ = session.Current);
        ProtocolException next = await Assert.ThrowsAsync<ProtocolException>(() => session.ApplyAsync("break"));

        Assert.Equal("worker_poisoned", first.Code);
        Assert.Equal(first.Message, current.Message);
        Assert.Equal(first.Message, next.Message);
        Assert.Equal(1, adapter.MutationCount);
    }

    private static DecisionFrame Frame(params LegalAction[] actions)
    {
        using JsonDocument document = JsonDocument.Parse("""{"schema_version":3,"decision":{"kind":"event"}}""");
        return new(
            document.RootElement.Clone(),
            actions,
            Terminated: false,
            Victory: false,
            KernelProjection: new { run_mode = true, run_stage = "event" },
            ScoringFeatures: null);
    }

    private static LegalAction Action(string id) => new(id, "choose_event", new Dictionary<string, object?>());

    private sealed class RecordingCompatibilityAdapter(DecisionFrame initial) : IRunSessionCompatibilityAdapter
    {
        private DecisionFrame _current = initial;
        private int _concurrentMutations;

        public TimeSpan ApplyDelay { get; init; }
        public Exception? ApplyFailure { get; init; }
        public Exception? RestoreFailure { get; init; }
        public int MutationCount { get; private set; }
        public int MaximumConcurrentMutations { get; private set; }

        public CompatibilityCapture Reset(ResetRequest request) => new(_current);
        public object CaptureCheckpoint() => "checkpoint";

        public async Task<CompatibilityCapture> ApplyAsync(string actionId)
        {
            int concurrent = Interlocked.Increment(ref _concurrentMutations);
            MaximumConcurrentMutations = Math.Max(MaximumConcurrentMutations, concurrent);
            MutationCount++;
            try
            {
                if (ApplyDelay > TimeSpan.Zero) await Task.Delay(ApplyDelay);
                if (ApplyFailure is not null) throw ApplyFailure;
                return new(_current);
            }
            finally
            {
                Interlocked.Decrement(ref _concurrentMutations);
            }
        }

        public Task<CompatibilityCapture> ResumeCardSelectAsync(
            PromptResumeToken parent,
            CardSelection selection) =>
            ApplyAsync(selection.ActionId);

        public Task<CompatibilityCapture> ResumeRewardAsync(
            PromptResumeToken parent,
            RewardSelection selection) =>
            ApplyAsync(selection.ActionId);

        public Task<CompatibilityCapture> RestoreAsync(object checkpoint)
        {
            if (RestoreFailure is not null) throw RestoreFailure;
            return Task.FromResult(new CompatibilityCapture(_current));
        }
    }
}
