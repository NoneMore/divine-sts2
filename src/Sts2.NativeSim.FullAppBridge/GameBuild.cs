using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using MegaCrit.Sts2.Core.Runs;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// The shipped build the bridge is running inside, fingerprinted the way the simulator's worker and
/// the trace exporter fingerprint it: the assembly's product version, the SHA-256 of the assembly
/// itself and the SHA-256 of the data pack beside it. A record carries the same three values, so a
/// comparison can attribute a difference to a build rather than to a state, and a corpus cannot be
/// read as if it were generated on the build under test when it was not.
///
/// It is measured once per process: the data pack is gigabytes, the answer cannot change while one
/// process lives, and a per-observation hash would make every decision cost a disk read of the
/// install.
/// </summary>
public static class GameBuild
{
    private static readonly Lazy<GameBuildDto> Fingerprint = new(Measure, LazyThreadSafetyMode.ExecutionAndPublication);

    /// <summary>The build this process is running.</summary>
    public static GameBuildDto Current => Fingerprint.Value;

    /// <summary>
    /// The assembly the game code lives in, and the data pack beside its directory — the paths the
    /// simulator's worker hashes and the paths a modded process is loaded from.
    /// </summary>
    private static GameBuildDto Measure()
    {
        string assemblyPath = typeof(RunManager).Assembly.Location;
        string dataDirectory = Path.GetDirectoryName(assemblyPath)!;
        string pckPath = Path.Combine(Directory.GetParent(dataDirectory)!.FullName, "SlayTheSpire2.pck");

        return new GameBuildDto
        {
            Version = FileVersionInfo.GetVersionInfo(assemblyPath).ProductVersion ?? "unknown",
            AssemblySha256 = HashFile(assemblyPath),
            PckSha256 = HashFile(pckPath),
        };
    }

    /// <summary>One file's SHA-256, upper-case hex, streamed rather than read whole.</summary>
    private static string HashFile(string path)
    {
        using FileStream stream = new(path, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024);
        return Convert.ToHexString(SHA256.HashData(stream));
    }
}
