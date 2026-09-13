<#
.SYNOPSIS
    Run the E5 golden differential against the shipped application.

.DESCRIPTION
    `docs/first-combat-scene-generation-plan.md` E5 requires two manifests on the pinned build:

    * targeted — thirteen fixtures (the seven high-risk Neow blessings, A10, and one more run start per
      character); each compares a bounded sample of its enumerated first-combat roots, following the
      recorded branch to the root and then out to the unified first-combat endpoint (player death, or
      the cleared encounter before room rewards).
    * breadth — a frozen manifest of 100 distinct seeds, one (character, ascension) cell per seed. Every
      entry drives the shared deterministic decision policy to the first-combat root and compares there,
      with `combat.turn == 1 && combat.phase == Play` proven on both environments; the first ten entries
      (one per cell) continue to the unified endpoint.

    Both modes take the same decision on both environments (the recorded trace where one is supplied,
    otherwise the smallest semantic action key with coordinator wrappers excluded), so in combat they
    execute `end_turn` whenever it is legal. Each report record states where the entry settled (`stop`)
    and which action kinds it actually took (`decision_kinds`), and the aggregate reports
    `stops`/`compared_roots`/`decision_kind_counts`, so a report never implies more coverage than the run
    exercised.

    Every entry runs its own sandboxed `SlayTheSpire2.exe --headless` process. That is a conservative
    measurement choice rather than a game constraint: this bridge starts the shipped autoplay driver once
    and that driver exits the process when its run ends, while the game itself can tear a run down and
    start another in the same process (see docs/e5-differential-run-cost-and-process-reuse-report.md).
    Reports land under artifacts/ (git-ignored) and every non-match keeps its raw seed, branch, action ids
    and the exact diverging field.

    Both modes exit non-zero when any entry is not a match, so this script fails closed.

.PARAMETER Workers
    Concurrent shipped-application processes. Each worker also holds one Godot fast-path host, so the
    memory cost is roughly two processes per worker. Two is the tested default; three caused connection
    resets on a 16 GB machine.

.PARAMETER OutDirectory
    Where the two reports are written. Defaults to artifacts/e5-differential.

.PARAMETER Mode
    targeted, breadth, or both (default both).

.PARAMETER SkipBuild
    Skip rebuilding the bridge. The reports pin the shipped game build, not the bridge assembly, so
    rebuild whenever bridge code changed and mention it with the results.

.PARAMETER BreadthLimit
    How many frozen breadth entries to compare (default 100 = the whole frozen manifest).

.PARAMETER RootsPerFixture
    How many sampled roots each targeted fixture compares (default 3).

.PARAMETER OnlyLabel
    Compare only these targeted fixture labels (repeatable); useful to re-verify one fixture cheaply.

.EXAMPLE
    pwsh scripts/run-e5-differential.ps1

.EXAMPLE
    pwsh scripts/run-e5-differential.ps1 -Mode targeted -OnlyLabel NEOWS_BONES -RootsPerFixture 2
#>
param(
    [int]$Workers = 2,
    [string]$OutDirectory = 'artifacts/e5-differential',
    [ValidateSet('targeted', 'breadth', 'both')]
    [string]$Mode = 'both',
    [int]$RootsPerFixture = 3,
    [int]$BreadthLimit = 100,
    [string[]]$OnlyLabel = @(),
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$repositoryRoot = Get-DivineRepositoryRoot
$python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The repository virtual environment is missing ($python). Run scripts\bootstrap.ps1 from an activated environment first."
}

if (-not $SkipBuild) {
    $dotnet = Get-DivineDotnet
    $dotnetRoot = Split-Path -Parent $dotnet
    $env:DOTNET_ROOT = $dotnetRoot
    $env:DOTNET_ROOT_X64 = $dotnetRoot
    $env:PATH = "$dotnetRoot;$env:PATH"
    $gameData = Join-Path (Get-DivineGameRoot) 'data_sts2_windows_x86_64'
    $project = Join-Path $repositoryRoot 'src\Sts2.NativeSim.FullAppBridge\Sts2.NativeSim.FullAppBridge.csproj'
    & $dotnet build $project -c Release -p:GameDataDir=$gameData | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "FullApp bridge build failed with exit code $LASTEXITCODE"
    }
}

$outRoot = Join-Path $repositoryRoot $OutDirectory
New-Item -ItemType Directory -Force -Path $outRoot | Out-Null

$runner = Join-Path $repositoryRoot 'python\first_combat_differential_acceptance.py'
$exitCode = 0

if ($Mode -in @('targeted', 'both')) {
    $targetedArgs = @(
        $runner, '--mode', 'targeted',
        '--roots-per-fixture', $RootsPerFixture,
        '--workers', $Workers,
        '--trajectory',
        '--out', (Join-Path $outRoot 'targeted.json')
    )
    foreach ($label in $OnlyLabel) { $targetedArgs += @('--only-label', $label) }
    Write-Host "== targeted manifest (workers=$Workers, roots-per-fixture=$RootsPerFixture)" -ForegroundColor Cyan
    & $python @targetedArgs | Out-Host
    if ($LASTEXITCODE -ne 0) { $exitCode = $LASTEXITCODE }
}

if ($Mode -in @('breadth', 'both')) {
    Write-Host "== breadth manifest (workers=$Workers, limit=$BreadthLimit)" -ForegroundColor Cyan
    & $python $runner --mode breadth --breadth-limit $BreadthLimit --workers $Workers --out (Join-Path $outRoot 'breadth.json') | Out-Host
    if ($LASTEXITCODE -ne 0) { $exitCode = $LASTEXITCODE }
}

Write-Host "reports under $outRoot" -ForegroundColor Cyan
exit $exitCode
