using Sts2.NativeSim.Protocol;
using Xunit;

namespace Sts2.NativeSim.Protocol.Tests;

public sealed class ProgressionReadinessTests
{
    [Fact]
    public void Start_is_rejected_until_progress_is_ready()
    {
        var readiness = new ProgressionReadiness();

        Assert.Equal("initializing", readiness.Status);
        InvalidOperationException error = Assert.Throws<InvalidOperationException>(readiness.EnsureReadyForStart);

        Assert.Contains("initializing", error.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Ready_state_exposes_the_canonical_profile_fingerprint()
    {
        var readiness = new ProgressionReadiness();

        readiness.Complete("abc123");
        readiness.EnsureReadyForStart();

        Assert.Equal("ready", readiness.Status);
        Assert.Equal("abc123", readiness.ProfileFingerprint);
    }

    [Fact]
    public void Failed_validation_never_becomes_ready()
    {
        var readiness = new ProgressionReadiness();
        readiness.Fail(new ProgressionBaselineMismatchException("drift"));

        InvalidOperationException error = Assert.Throws<InvalidOperationException>(readiness.EnsureReadyForStart);

        Assert.Equal("failed", readiness.Status);
        Assert.Contains("drift", error.Message);
    }
}
