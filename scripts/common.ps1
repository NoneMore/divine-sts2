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

# A probe that creates and removes its own scratch directory: hosts that allow the
# location are left exactly as they were, hosts that refuse it are adapted to.
function Test-DivinePathWritable {
    param([string]$Path)

    if (-not $Path) { return $false }
    $probe = Join-Path $Path ('.divine-write-probe-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    $created = $false
    try {
        [IO.Directory]::CreateDirectory($probe) | Out-Null
        $created = $true
    } catch {
        $created = $false
    }
    if ($created) { Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction SilentlyContinue }
    return $created
}

# `dotnet` writes first-run state under the user profile. A host that refuses that
# location (a file sandbox, a read-only profile) gets repository-local state instead.
function Initialize-DivineDotnetEnvironment {
    if (-not $env:DOTNET_CLI_HOME -and -not (Test-DivinePathWritable -Path $env:USERPROFILE)) {
        $tools = Get-DivineToolsRoot
        $env:DOTNET_CLI_HOME = Join-Path $tools 'dotnet-home'
        if (-not $env:NUGET_PACKAGES) { $env:NUGET_PACKAGES = Join-Path $tools 'nuget-packages' }
        Write-Host "The user profile is not writable; keeping SDK and package state under $tools."
    }
    foreach ($name in @('DOTNET_CLI_HOME', 'NUGET_PACKAGES')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value -and -not (Test-Path -LiteralPath $value)) {
            New-Item -ItemType Directory -Path $value -Force | Out-Null
        }
    }
}

# An SDK whose workload-locator SDK directories are missing makes any project that
# references another project fail with MSB4276, which a single-node build absorbs.
$script:DivineWorkloadLocatorMissing = $null

function Test-DivineWorkloadLocatorMissing {
    param([Parameter(Mandatory)][string]$Dotnet)

    if ($null -ne $script:DivineWorkloadLocatorMissing) { return $script:DivineWorkloadLocatorMissing }
    $missing = $false
    try {
        $listed = & $Dotnet --list-sdks 2>$null
        if ($LASTEXITCODE -eq 0 -and $listed) {
            $resolved = $false
            foreach ($line in $listed) {
                $match = [regex]::Match($line, '\[(.+)\]\s*$')
                if (-not $match.Success) { continue }
                $locator = Join-Path $match.Groups[1].Value.Trim() 'Sdks\Microsoft.NET.SDK.WorkloadAutoImportPropsLocator\Sdk'
                if (Test-Path -LiteralPath $locator) { $resolved = $true; break }
            }
            $missing = -not $resolved
        }
    } catch {
        $missing = $false
    }
    $script:DivineWorkloadLocatorMissing = $missing
    return $missing
}

# The one `dotnet` entry point for this repository: it adapts to the host where the
# host needs it, and leaves `$LASTEXITCODE` for the caller to check as before.
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
    Initialize-DivineDotnetEnvironment
    $dotnet = Get-DivineDotnet

    $extra = @()
    # Only these verbs reach MSBuild with the flag. `run` builds implicitly through a path
    # that ignores `-m:1` and still fails with MSB4276 on such an SDK, which is why the
    # scripts build first and then run with `--no-build`.
    if ($Arguments.Count -gt 0 -and $Arguments[0] -in @('build', 'restore', 'msbuild')) {
        if (Test-DivineWorkloadLocatorMissing -Dotnet $dotnet) {
            $extra += '-m:1'
            Write-Host 'The .NET SDK cannot resolve its workload-locator directories; building single-node (-m:1).'
        }
    }

    # `--` separates the host's own arguments from the program's, so a build switch
    # appended after it would be handed to the program instead.
    $separator = [Array]::IndexOf($Arguments, '--')
    if ($separator -ge 0) {
        $head = if ($separator -gt 0) { $Arguments[0..($separator - 1)] } else { @() }
        $tail = $Arguments[$separator..($Arguments.Count - 1)]
        & $dotnet @head @extra @tail
    } else {
        & $dotnet @Arguments @extra
    }
}

# Downloads through the first transport that works: `curl` (resumable), then
# `Invoke-WebRequest`, then Python `urllib`, which honours HTTP_PROXY/HTTPS_PROXY on
# hosts whose proxy refuses schannel credentials.
function Save-DivineDownload {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$OutFile,
        [switch]$Resume
    )

    $partial = "$OutFile.part"
    $parent = Split-Path -Parent $OutFile
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $failures = [Collections.Generic.List[string]]::new()

    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        $curlArguments = @('-L', '--fail', '--retry', '3')
        if ($Resume -and (Test-Path -LiteralPath $partial)) { $curlArguments += @('-C', '-') }
        $curlArguments += @('-o', $partial, $Uri)
        & curl.exe @curlArguments
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $partial)) {
            Move-Item -LiteralPath $partial -Destination $OutFile -Force
            return
        }
        $failures.Add("curl.exe exited $LASTEXITCODE")
    } else {
        $failures.Add('curl.exe is not on PATH')
    }

    # No resume here, so a leftover partial would be appended to rather than replaced.
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $OutFile -ErrorAction Stop
        if (Test-Path -LiteralPath $OutFile) { return }
        $failures.Add('Invoke-WebRequest wrote no file')
    } catch {
        $failures.Add("Invoke-WebRequest: $($_.Exception.Message)")
    }

    $python = @(
        (Join-Path (Get-DivineRepositoryRoot) '.venv\Scripts\python.exe'),
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
    if ($python) {
        $downloader = @'
import shutil
import sys
import urllib.request

url, destination = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(url) as response, open(destination, "wb") as out:
    shutil.copyfileobj(response, out, 1024 * 256)
'@
        $downloader | & $python - $Uri $partial
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $partial)) {
            Move-Item -LiteralPath $partial -Destination $OutFile -Force
            return
        }
        $failures.Add("Python urllib download exited $LASTEXITCODE")
    } else {
        $failures.Add('no Python interpreter was found')
    }

    $proxies = @('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY') | ForEach-Object {
        $value = [Environment]::GetEnvironmentVariable($_)
        if ($value) { "$_=$value" } else { "$_=(unset)" }
    }
    throw "Download failed: $Uri`nTried: $($failures -join '; ')`nProxy environment: $($proxies -join ', ')"
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
