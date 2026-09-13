using System.Diagnostics;
using System.Security.Cryptography;

namespace Sts2.NativeSim.FullAppBridge;

/// <summary>
/// The exact build identity of the shipped application this bridge runs inside.
///
/// It is read from the loaded assembly and the PCK that ships beside the executable, never from
/// configuration, so a differential report pins the build it actually observed. The PCK hash is a
/// one-off 1.8 GB read, so it is primed in the background at startup and the first observation that
/// needs it waits for it rather than reporting an empty fingerprint.
/// </summary>
internal static class FullAppBuildIdentity
{
    private static readonly Lazy<GameBuildDto> LazyValue = new(Compute, LazyThreadSafetyMode.ExecutionAndPublication);

    public static GameBuildDto Value => LazyValue.Value;

    /// <summary>Start hashing in the background so the first decision boundary rarely blocks.</summary>
    public static void Prime()
    {
        _ = Task.Run(() =>
        {
            try
            {
                _ = LazyValue.Value;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[FullAppBridge] build identity failed: {ex.Message}");
            }
        });
    }

    private static GameBuildDto Compute()
    {
        string assemblyPath = typeof(MegaCrit.Sts2.Core.Nodes.NGame).Assembly.Location;
        string? exePath = Environment.ProcessPath;
        string exeDir = exePath is not null && Path.GetDirectoryName(exePath) is { Length: > 0 } directory
            ? directory
            : AppContext.BaseDirectory;
        string pckPath = Path.Combine(exeDir, "SlayTheSpire2.pck");
        return new GameBuildDto
        {
            Version = FileVersionInfo.GetVersionInfo(assemblyPath).ProductVersion ?? "unknown",
            AssemblySha256 = HashFile(assemblyPath),
            PckSha256 = File.Exists(pckPath) ? HashFile(pckPath) : "",
        };
    }

    private static string HashFile(string path)
    {
        using FileStream stream = File.OpenRead(path);
        using SHA256 sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(stream));
    }
}
