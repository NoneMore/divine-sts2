param(
    [switch]$Train,
    [string]$TorchIndexUrl = '',
    [switch]$WithGodot
)

# Compatibility entry point. The canonical developer interface is ../dev.ps1.
$arguments = @('setup')
if ($Train) { $arguments += '-Train' }
if ($TorchIndexUrl) { $arguments += @('-TorchIndexUrl', $TorchIndexUrl) }

& (Join-Path $PSScriptRoot '..\dev.ps1') @arguments
exit $LASTEXITCODE
