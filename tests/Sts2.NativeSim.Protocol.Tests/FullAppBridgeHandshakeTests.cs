using Sts2.NativeSim.Protocol;
using Xunit;

namespace Sts2.NativeSim.Protocol.Tests;

public sealed class FullAppBridgeHandshakeTests
{
    [Fact]
    public void Initializing_handshake_rejects_start_without_hashing_the_game_build()
    {
        var readiness = new ProgressionReadiness();

        IReadOnlyDictionary<string, object?> hello = FullAppBridgeHandshake.CreateHello(
            readiness.Snapshot(),
            () => throw new InvalidOperationException("game build must not be read while initializing"),
            pid: 123,
            boundPort: 456,
            processMode: "fresh");

        Assert.Equal("initializing", hello["status"]);
        Assert.False(hello.ContainsKey("profile_fingerprint"));
        Assert.False(hello.ContainsKey("game_build"));
        Assert.Throws<InvalidOperationException>(() => FullAppBridgeHandshake.EnsureCanStart(readiness));
    }

    [Fact]
    public void Ready_handshake_reports_policy_profile_process_and_game_build()
    {
        var readiness = new ProgressionReadiness();
        readiness.Complete("canonical-profile");
        var build = new GameBuildSpec("v-test", "AA", "BB");

        IReadOnlyDictionary<string, object?> hello = FullAppBridgeHandshake.CreateHello(
            readiness.Snapshot(), () => build, pid: 123, boundPort: 456, processMode: "fresh");

        Assert.Equal("ready", hello["status"]);
        Assert.Equal(ProgressionCompletePolicy.Revision, hello["progression_policy"]);
        Assert.Equal("canonical-profile", hello["profile_fingerprint"]);
        Assert.Equal("fresh", hello["process_mode"]);
        Assert.Equal(123, hello["pid"]);
        Assert.Equal(456, hello["bound_port"]);
        Assert.Same(build, hello["game_build"]);
        FullAppBridgeHandshake.EnsureCanStart(readiness);
    }
}
