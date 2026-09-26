$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$requiredVersion = Get-DivineExpectedDotnetVersion
try {
    $existing = Get-DivineDotnet
    if ($existing) {
        Write-Output $existing
        return
    }
} catch {
    # No compatible system or fallback SDK yet; install the checkout-local fallback below.
}

$toolRoot = Get-DivineToolsRoot
$destination = Join-Path $toolRoot 'dotnet9'
$installer = Join-Path $toolRoot 'dotnet-install.ps1'
$installed = Join-Path $destination 'dotnet.exe'

New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $installer)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installer
}

if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Recurse -Force
}
& $installer -Version $requiredVersion -InstallDir $destination -NoPath
$installerExit = if (Test-Path variable:LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
if ($installerExit -ne 0) {
    throw ".NET SDK $requiredVersion installation failed with exit code $installerExit"
}

$sdks = & $installed --list-sdks 2>$null
$escaped = [regex]::Escape($requiredVersion)
if ($LASTEXITCODE -ne 0 -or -not ($sdks | Where-Object { $_ -match "^$escaped\s" })) {
    throw ".NET SDK installation is inconsistent: expected $requiredVersion under $destination."
}

Write-Output $installed
