using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;

namespace Sts2.NativeSim.Core;

internal readonly record struct NativePckFingerprintResult(string Sha256, double Seconds, long BytesHashed, string Source);

internal static class NativePckFingerprint
{
    private const string HintEnvironmentVariable = "STS2_NATIVE_PCK_FINGERPRINT";

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint Attributes;
        public FILETIME CreationTime;
        public FILETIME LastAccessTime;
        public FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint SizeHigh;
        public uint SizeLow;
        public uint LinkCount;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out ByHandleFileInformation information);

    private static ulong FileId(string path)
    {
        using SafeFileHandle handle = File.OpenHandle(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        if (!GetFileInformationByHandle(handle, out ByHandleFileInformation information))
            throw new IOException($"Cannot read PCK file identity: {Marshal.GetLastWin32Error()}");
        return ((ulong)information.FileIndexHigh << 32) | information.FileIndexLow;
    }

    public static NativePckFingerprintResult Read(string path)
    {
        path = Path.GetFullPath(path);
        string? hint = System.Environment.GetEnvironmentVariable(HintEnvironmentVariable);
        if (OperatingSystem.IsWindows() && !string.IsNullOrEmpty(hint))
        {
            try
            {
                using JsonDocument document = JsonDocument.Parse(hint);
                JsonElement row = document.RootElement;
                string hintedPath = row.GetProperty("path").GetString()!;
                string digest = row.GetProperty("sha256").GetString()!;
                ulong fileId = row.GetProperty("file_id").GetUInt64();
                long size = row.GetProperty("size").GetInt64();
                long modified = row.GetProperty("mtime_ticks").GetInt64();
                long created = row.GetProperty("ctime_ticks").GetInt64();
                FileInfo file = new(path);
                if (Path.GetFullPath(hintedPath).Equals(path, StringComparison.OrdinalIgnoreCase)
                    && digest.Length == 64 && Convert.FromHexString(digest).Length == 32
                    && FileId(path) == fileId
                    && file.Length == size
                    && file.LastWriteTimeUtc.Ticks == modified
                    && file.CreationTimeUtc.Ticks == created)
                    return new(digest.ToUpperInvariant(), 0, 0, "pool");
            }
            catch (Exception error) when (error is JsonException or KeyNotFoundException or InvalidOperationException
                or ArgumentException or FormatException or IOException or UnauthorizedAccessException)
            {
                // A stale or malformed hint cannot replace an independently measured digest.
            }
        }

        Stopwatch timer = Stopwatch.StartNew();
        string measured = ReflectionTools.HashFile(path);
        timer.Stop();
        return new(measured, timer.Elapsed.TotalSeconds, new FileInfo(path).Length, "worker");
    }
}
