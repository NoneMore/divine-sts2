param(
    [ValidateSet('Debug','Release')][string]$Configuration = 'Release',
    # Adds -p:NuGetAudit=false. Explicit on purpose: it weakens the vulnerability audit, so a
    # host that cannot reach nuget.org asks for it rather than getting it by detection.
    [switch]$DisableNuGetAudit
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
$buildArguments = @()
if ($DisableNuGetAudit) { $buildArguments += '-p:NuGetAudit=false' }

# Build the pure .NET 9 persistent host
Invoke-DivineDotnet build (Join-Path $PSScriptRoot '..\src\Sts2.NativeSim.Host\Sts2.NativeSim.Host.csproj') -c $Configuration "-p:GameDataDir=$gameData" @buildArguments
if ($LASTEXITCODE -ne 0) { throw "Persistent pure .NET server build failed with exit code $LASTEXITCODE" }

# Optionally build GodotHost if Godot is configured
if (Test-Path (Join-Path $PSScriptRoot '..\src\Sts2.NativeSim.GodotHost\Sts2.NativeSim.GodotHost.csproj')) {
    try {
        $godot = Get-DivineGodot
        if ($godot) {
            Invoke-DivineDotnet build (Join-Path $PSScriptRoot '..\src\Sts2.NativeSim.GodotHost\Sts2.NativeSim.GodotHost.csproj') -c $Configuration "-p:GameDataDir=$gameData" @buildArguments
        }
    } catch {
        # Godot is optional for the pure .NET 9 runner
    }
}
