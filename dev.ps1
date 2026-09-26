param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'sync', 'build', 'test', 'check', 'doctor')]
    [string]$Command = 'check',
    [switch]$Train,
    [string]$TorchIndexUrl = '',
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts\common.ps1')

$root = Get-DivineRepositoryRoot

function Sync-DivinePython {
    $arguments = @('sync', '--frozen', '--extra', 'dev')
    if ($Train) {
        $arguments += @('--extra', 'train')
    }
    Invoke-DivineUv @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }

    if ($Train -and $TorchIndexUrl) {
        $python = Join-Path $root '.venv\Scripts\python.exe'
        Invoke-DivineUv pip install --python $python 'torch>=2.6' --index-url $TorchIndexUrl --extra-index-url 'https://pypi.org/simple'
        if ($LASTEXITCODE -ne 0) {
            throw "CUDA Torch installation failed with exit code $LASTEXITCODE"
        }
    }
}

switch ($Command) {
    'sync' {
        Sync-DivinePython
    }

    'setup' {
        Sync-DivinePython
        & (Join-Path $root 'scripts\install-dotnet-9.ps1') | Out-Host
        & (Join-Path $root 'scripts\install-godot-4.5.1.ps1') | Out-Host
        & (Join-Path $root 'scripts\build-persistent-server.ps1') -Configuration Release -WithGodot -GodotConfiguration Debug
        if ($LASTEXITCODE -ne 0) { throw 'Native host build failed.' }
        & (Join-Path $root 'scripts\doctor.ps1') -Deep
        if ($LASTEXITCODE -ne 0) { throw 'Deep doctor failed. Resolve the reported checks before using the native worker.' }
    }

    'build' {
        & (Join-Path $root 'scripts\build-persistent-server.ps1') -Configuration Release -WithGodot -GodotConfiguration Debug
        if ($LASTEXITCODE -ne 0) { throw 'Native host build failed.' }
    }

    'test' {
        Invoke-DivineUv run --frozen python -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
    }

    'check' {
        Invoke-DivineUv run --frozen python -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
        & (Join-Path $root 'scripts\test-public-tree.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Public-tree checks failed.' }
    }

    'doctor' {
        $doctorArguments = @{}
        if ($Json) { $doctorArguments['Json'] = $true }
        & (Join-Path $root 'scripts\doctor.ps1') -Deep @doctorArguments
        exit $LASTEXITCODE
    }
}
