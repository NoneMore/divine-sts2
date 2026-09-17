$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repoRoot = Get-DivineRepositoryRoot
$host = Join-Path $repoRoot 'src\Sts2.NativeSim.Host'
$assembly = Get-DivineGameAssembly

# `dotnet run` builds implicitly, and a script that built through a different entry point would
# leave the Run half reading an assembly the Build half did not write; the host is built through
# the helper first and then run without building again.
Invoke-DivineDotnet build $host -c Release --nologo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Invoke-DivineDotnet run --project $host -c Release --no-build '--' $assembly 1000000
exit $LASTEXITCODE
