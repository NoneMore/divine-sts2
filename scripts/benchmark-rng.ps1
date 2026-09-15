$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repoRoot = Get-DivineRepositoryRoot
$host = Join-Path $repoRoot 'src\Sts2.NativeSim.Host'
$assembly = Get-DivineGameAssembly

# `dotnet run` builds implicitly, and on an SDK whose workload-locator directories are
# missing that build fails with MSB4276 no matter what the runner is told, so the host is
# built through the helper first and then run without building again.
Invoke-DivineDotnet build $host -c Release --nologo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Invoke-DivineDotnet run --project $host -c Release --no-build '--' $assembly 1000000
exit $LASTEXITCODE
