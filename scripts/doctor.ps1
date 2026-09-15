param(
    [switch]$Deep,
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

# `.env` is applied by common.ps1, so this wrapper is how a repository-local override
# (STS2_GAME_ROOT, GODOT) reaches the Python CLI without being exported by hand.
$python = @(
    (Join-Path (Get-DivineRepositoryRoot) '.venv\Scripts\python.exe'),
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $python) { throw 'No Python interpreter was found. Run scripts\bootstrap.ps1 first.' }

$arguments = @('-m', 'sts2_native_sim.cli', 'doctor')
if ($Deep) { $arguments += '--deep' }
if ($Json) { $arguments += '--json' }
& $python @arguments
exit $LASTEXITCODE
