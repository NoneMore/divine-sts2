param(
    [switch]$Deep,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$arguments = @('run', '--frozen', 'python', '-m', 'sts2_native_sim.cli', 'doctor')
if ($Deep) { $arguments += '--deep' }
if ($Json) { $arguments += '--json' }

Invoke-DivineUv @arguments
exit $LASTEXITCODE
