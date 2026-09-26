Set-StrictMode -Version Latest

function Get-DivineRepositoryRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-DivineToolsRoot {
    return (Join-Path (Get-DivineRepositoryRoot) '.tools')
}

function Get-DivineUv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw 'uv was not found on PATH. Install uv, then run `pwsh ./dev.ps1 setup`.'
}

function Invoke-DivineUv {
    $uv = Get-DivineUv
    & $uv @args
}

function Get-DivineExpectedDotnetVersion {
    $globalJson = Join-Path (Get-DivineRepositoryRoot) 'global.json'
    $configuration = Get-Content -Raw -LiteralPath $globalJson | ConvertFrom-Json
    return [string]$configuration.sdk.version
}

$script:DivinePathDiscoveryCache = @{}

function Invoke-DivinePathDiscovery {
    param(
        [Parameter(Mandatory = $true)][string]$Function,
        [string]$Explicit = ''
    )

    $cacheKey = "$Function`n$Explicit"
    if ($script:DivinePathDiscoveryCache.ContainsKey($cacheKey)) {
        return $script:DivinePathDiscoveryCache[$cacheKey]
    }

    $uv = Get-DivineUv
    $code = "from sts2_native_sim.paths import $Function; import sys; print($Function(sys.argv[1] if len(sys.argv) > 1 else None))"
    $arguments = @('run', '--frozen', 'python', '-c', $code)
    if ($Explicit) { $arguments += $Explicit }
    $output = & $uv @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Function failed. Run `pwsh ./dev.ps1 doctor` for environment diagnostics."
    }
    $resolved = ($output | Select-Object -Last 1)
    $script:DivinePathDiscoveryCache[$cacheKey] = $resolved
    return $resolved
}

function Get-DivineDotnet {
    return Invoke-DivinePathDiscovery -Function 'find_dotnet'
}

function Invoke-DivineDotnet {
    $dotnet = Get-DivineDotnet
    & $dotnet @args
}

function Get-DivineGameRoot([string]$Explicit = '') {
    return Invoke-DivinePathDiscovery -Function 'find_game_root' -Explicit $Explicit
}

function Get-DivineGameAssembly([string]$Explicit = '') {
    return Invoke-DivinePathDiscovery -Function 'find_game_assembly' -Explicit $Explicit
}

function Get-DivineGodot {
    return Invoke-DivinePathDiscovery -Function 'find_godot'
}
