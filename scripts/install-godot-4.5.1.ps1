$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

try {
    $existing = Get-DivineGodot
    if ($existing) {
        Write-Output $existing
        return
    }
} catch {
    # No compatible system or fallback Godot yet; install the checkout-local fallback below.
}

$toolRoot = Get-DivineToolsRoot
$archive = Join-Path $toolRoot 'Godot_v4.5.1-stable_mono_win64.zip'
$destination = Join-Path $toolRoot 'godot-4.5.1-mono'
$staging = "$destination.staging"
$download = 'https://github.com/godotengine/godot/releases/download/4.5.1-stable/Godot_v4.5.1-stable_mono_win64.zip'

New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -UseBasicParsing -Uri $download -OutFile $archive
}

$godot = Get-ChildItem -LiteralPath $destination -Recurse -File -Filter 'Godot_v4.5.1-stable_mono_win64.exe' -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $godot) {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $staging
        $stagedGodot = Get-ChildItem -LiteralPath $staging -Recurse -File -Filter 'Godot_v4.5.1-stable_mono_win64.exe' |
            Select-Object -First 1 -ExpandProperty FullName
        if (-not $stagedGodot) { throw 'The archive did not contain the expected Godot executable.' }
        if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
        Move-Item -LiteralPath $staging -Destination $destination
    } catch {
        if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
        $quarantined = "$archive.invalid"
        Move-Item -LiteralPath $archive -Destination $quarantined -Force -ErrorAction SilentlyContinue
        throw "Godot archive extraction failed: $($_.Exception.Message). The invalid archive was quarantined at $quarantined; rerun to download a fresh copy."
    }
}

$godot = Get-ChildItem -LiteralPath $destination -Recurse -File -Filter 'Godot_v4.5.1-stable_mono_win64.exe' |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $godot) {
    throw 'The Godot fallback was installed, but its executable could not be found.'
}
Write-Output $godot
