param(
    [ValidateSet('Debug','Release')][string]$Configuration = 'Release',
    # The Godot worker host is opt-in. The pure .NET host is what this script is for, and the
    # worker scripts (test-godot-determinism.ps1 and its siblings) build their own GodotHost in
    # Debug, so building one here by default produced an artifact nothing consumed — and swallowed
    # its own failure while doing it.
    [switch]$WithGodot,
    [ValidateSet('Debug','Release')][string]$GodotConfiguration = 'Debug'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$dotnet = Get-DivineDotnet
$dotnetRoot = Split-Path -Parent $dotnet
$env:DOTNET_ROOT = $dotnetRoot
$env:DOTNET_ROOT_X64 = $dotnetRoot
$env:PATH = "$dotnetRoot;$env:PATH"
$gameRoot = Get-DivineGameRoot
$gameData = Join-Path $gameRoot 'data_sts2_windows_x86_64'

# Build the pure .NET 9 persistent host
Invoke-DivineDotnet build (Join-Path $PSScriptRoot '..\src\Sts2.NativeSim.Host\Sts2.NativeSim.Host.csproj') -c $Configuration "-p:GameDataDir=$gameData"
if ($LASTEXITCODE -ne 0) { throw "Persistent pure .NET server build failed with exit code $LASTEXITCODE" }

if ($WithGodot) {
    $null = Get-DivineGodot
    Invoke-DivineDotnet build (Join-Path $PSScriptRoot '..\src\Sts2.NativeSim.GodotHost\Sts2.NativeSim.GodotHost.csproj') -c $GodotConfiguration "-p:GameDataDir=$gameData"
    if ($LASTEXITCODE -ne 0) { throw "Godot host build failed with exit code $LASTEXITCODE" }
}
