$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-DivineRepositoryRoot

Invoke-DivineUv run --frozen python -m compileall -q (Join-Path $root 'python')
if ($LASTEXITCODE -ne 0) { throw 'Python compilation failed.' }

Invoke-DivineDotnet build (Join-Path $root 'src\Sts2.NativeSim.Protocol\Sts2.NativeSim.Protocol.csproj') -c Release --nologo
if ($LASTEXITCODE -ne 0) { throw 'Protocol build failed.' }
Invoke-DivineDotnet build (Join-Path $root 'src\Sts2.NativeSim.Core\Sts2.NativeSim.Core.csproj') -c Release --nologo
if ($LASTEXITCODE -ne 0) { throw 'Core build failed.' }

# Two scans with different scopes (ADR-0004). A machine-specific path is forbidden in the
# tree, but documents describing the rule may quote it. A leaked credential is a leak in prose too.
$pathPattern = 'C:\\Users\\|F:\\SteamLibrary'
$machinePaths = git -C $root grep -n -E $pathPattern -- . ':(exclude)*.md'
if ($LASTEXITCODE -eq 0) { throw "Machine-specific path found in a tracked file:`n$machinePaths" }
if ($LASTEXITCODE -gt 1) { throw 'Machine-path scan failed.' }

$tokenPattern = 'ghp_[A-Za-z0-9_]+'
$tokens = git -C $root grep -n -E $tokenPattern -- .
if ($LASTEXITCODE -eq 0) { throw "Secret token found in a tracked file:`n$tokens" }
if ($LASTEXITCODE -gt 1) { throw 'Secret-token scan failed.' }

$trackedBinaries = git -C $root ls-files | Where-Object {
    [IO.Path]::GetExtension($_) -in @('.dll','.exe','.pck','.pt','.pth','.ckpt')
}
if ($trackedBinaries) { throw "Forbidden distributable binaries found in tracked files:`n$($trackedBinaries -join "`n")" }

Write-Host 'Public-tree checks passed.'
exit 0
