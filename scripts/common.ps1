Set-StrictMode -Version Latest

function Get-DivineRepositoryRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-DivineToolsRoot {
    return (Join-Path (Get-DivineRepositoryRoot) '.tools')
}

# Local overrides live in a gitignored `.env`; `.env.example` is the template. Loading is
# fill-only: a variable that is already set always wins, so a real environment is never
# silently overridden by a file in the working tree.
$script:DivineDotEnvPathVariables = @(
    'DOTNET_CLI_HOME',
    'NUGET_PACKAGES',
    'UV_CACHE_DIR',
    'UV_PYTHON_INSTALL_DIR',
    'UV_TOOL_DIR',
    'UV_TOOL_BIN_DIR',
    'STS2_GAME_ROOT',
    'STS2_ASSEMBLY',
    'STS2_SANDBOX_ROOT',
    'GODOT'
)

function Import-DivineDotEnv {
    param([string]$Path = '')

    if (-not $Path) { $Path = Join-Path (Get-DivineRepositoryRoot) '.env' }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $separator = $trimmed.IndexOf('=')
        if ($separator -lt 1) { continue }
        $name = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()
        if ($value.Length -ge 2) {
            $first = $value.Substring(0, 1)
            if (($first -eq '"' -or $first -eq "'") -and $value.EndsWith($first)) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        if (-not $name) { continue }
        # `.env.example` names repository-relative locations; resolve them against the
        # repository so a copied `.env` does not depend on the caller's working directory.
        if (($name -in $script:DivineDotEnvPathVariables) -and $value -and -not [IO.Path]::IsPathRooted($value)) {
            $value = Join-Path (Get-DivineRepositoryRoot) $value
        }
        if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name))) {
            [Environment]::SetEnvironmentVariable($name, $value)
        }
    }
}

# The one `dotnet` entry point for this repository: it supplies the repository's SDK, and it
# explains the one failure MSBuild cannot explain itself. It leaves `$LASTEXITCODE` for the
# caller to check as before.
#
# A simple function on purpose. Declaring a parameter attribute would make this an advanced
# function, whose own common parameters then collide with dotnet's switches: `-p:Name=Value`
# is rejected as an ambiguous `-ProgressAction`/`-PipelineVariable`.
#
# PowerShell also rewrites a bare `-p:Name=Value` into two arguments and eats a bare `--`,
# so a caller passes those two quoted: `"-p:GameDataDir=$gameData"` and `'--'`.
function Invoke-DivineDotnet {
    $Arguments = @($args)
    if (-not $Arguments) { $Arguments = @() }
    $dotnet = Get-DivineDotnet

    # `--` separates the host's own arguments from the program's, so a switch appended after
    # it would be handed to the program instead.
    $separator = [Array]::IndexOf($Arguments, '--')
    if ($separator -ge 0) {
        $head = if ($separator -gt 0) { $Arguments[0..($separator - 1)] } else { @() }
        $tail = $Arguments[$separator..($Arguments.Count - 1)]
    } else {
        $head = $Arguments
        $tail = @()
    }

    # Outside an unconfined host a build that crosses a `ProjectReference` fails with
    # `0 个警告 / 0 个错误` and no error text anywhere: MSBuild's worker nodes and the Roslyn
    # compiler server reach each other over named pipes, which a file sandbox refuses. `Tee-Object`
    # keeps the build's output streaming to the console while the summary lines are captured, so the
    # failure that cannot explain itself gets an explanation.
    if ($Arguments.Count -gt 0 -and $Arguments[0] -in @('build', 'restore', 'msbuild')) {
        & $dotnet @head @tail | Tee-Object -Variable output
        $reported = @($output | Where-Object { $_ -match '(个错误|Error\(s\))' -and $_ -notmatch '^\s*0\s' })
        if ($LASTEXITCODE -ne 0 -and $reported.Count -eq 0 -and ($output | Where-Object { $_ -match '^\s*0\s*(个错误|Error\(s\))' })) {
            Write-Host @'
The build failed without reporting an error. MSBuild's worker nodes and the Roslyn compiler
server need named pipes, and a file sandbox refuses them: run this session without the file
sandbox (escalate to full access) and retry. See docs/agents/dev-environment.md.
'@
        }
        return
    }

    & $dotnet @head @tail
}

function Get-DivineDotnet {
    $bundled = Join-Path (Get-DivineToolsRoot) 'dotnet9\dotnet.exe'
    if (Test-Path -LiteralPath $bundled) { return $bundled }
    $command = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($command) {
        $sdks = & $command.Source --list-sdks 2>$null
        if ($LASTEXITCODE -eq 0 -and ($sdks | Where-Object { $_ -match '^9\.' })) { return $command.Source }
    }
    throw '.NET 9 SDK was not found. Install it or place it under .tools\dotnet9.'
}

function Get-DivineGameRoot([string]$Explicit = '') {
    $override = if ($Explicit) { $Explicit } else { $env:STS2_GAME_ROOT }
    if ($override) {
        $candidate = (Resolve-Path -LiteralPath $override -ErrorAction SilentlyContinue).Path
        if (-not $candidate) { throw "Configured STS2_GAME_ROOT does not exist: $override" }
        $exe = Join-Path $candidate 'SlayTheSpire2.exe'
        $pck = Join-Path $candidate 'SlayTheSpire2.pck'
        $dll = Join-Path $candidate 'data_sts2_windows_x86_64\sts2.dll'
        if (-not ((Test-Path -LiteralPath $exe) -and (Test-Path -LiteralPath $pck) -and (Test-Path -LiteralPath $dll))) {
            throw "Configured STS2_GAME_ROOT is not a complete game install: $candidate"
        }
        return $candidate
    }
    $candidates = [Collections.Generic.List[string]]::new()
    foreach ($programFiles in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if (-not $programFiles) { continue }
        $steam = Join-Path $programFiles 'Steam'
        $candidates.Add((Join-Path $steam 'steamapps\common\Slay the Spire 2'))
        $manifest = Join-Path $steam 'steamapps\libraryfolders.vdf'
        if (Test-Path -LiteralPath $manifest) {
            $text = Get-Content -Raw -LiteralPath $manifest
            foreach ($match in [regex]::Matches($text, '"path"\s+"([^"]+)"')) {
                $library = $match.Groups[1].Value -replace '\\\\', '\'
                $candidates.Add((Join-Path $library 'steamapps\common\Slay the Spire 2'))
            }
        }
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        $exe = Join-Path $candidate 'SlayTheSpire2.exe'
        $pck = Join-Path $candidate 'SlayTheSpire2.pck'
        $dll = Join-Path $candidate 'data_sts2_windows_x86_64\sts2.dll'
        if ((Test-Path -LiteralPath $exe) -and (Test-Path -LiteralPath $pck) -and (Test-Path -LiteralPath $dll)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'Slay the Spire 2 was not found. Set STS2_GAME_ROOT to its installed directory (or put it in .env). Steam libraries are read from %PROGRAMFILES%, %PROGRAMFILES(X86)% and STEAM_PATH only; the registry is not consulted.'
}

function Get-DivineGameAssembly([string]$Explicit = '') {
    if ($Explicit) { $candidate = $Explicit }
    elseif ($env:STS2_ASSEMBLY) { $candidate = $env:STS2_ASSEMBLY }
    else { $candidate = Join-Path (Get-DivineGameRoot) 'data_sts2_windows_x86_64\sts2.dll' }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "STS2 assembly not found: $candidate" }
    return (Resolve-Path -LiteralPath $candidate).Path
}

function Get-DivineGodot {
    if ($env:GODOT -and (Test-Path -LiteralPath $env:GODOT -PathType Leaf)) { return $env:GODOT }
    $root = Join-Path (Get-DivineToolsRoot) 'godot-4.5.1-mono'
    foreach ($name in @('Godot_v4.5.1-stable_mono_win64_console.exe', 'Godot_v4.5.1-stable_mono_win64.exe')) {
        $match = Get-ChildItem -LiteralPath $root -Recurse -File -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($match) { return $match.FullName }
    }
    throw 'Godot 4.5.1 .NET was not found. Run scripts\bootstrap.ps1 or set GODOT.'
}

Import-DivineDotEnv
