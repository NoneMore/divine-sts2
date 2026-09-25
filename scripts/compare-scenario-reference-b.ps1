param(
    [Parameter(Mandatory)][string]$RunId,
    [int]$Pairs = 3
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$root = Get-DivineRepositoryRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$out = Join-Path $root 'artifacts\scenario-performance'
$seeds = foreach ($seed in 1..128) { '--seed'; [string]$seed }

if ($Pairs -lt 1 -or $RunId -notmatch '^[A-Za-z0-9_-]+$') {
    throw 'Pairs must be positive and RunId must contain only letters, digits, hyphens or underscores.'
}
New-Item -ItemType Directory -Force -Path $out | Out-Null
$reportPath = Join-Path $out "paired-$RunId.json"
if (Test-Path -LiteralPath $reportPath) { throw "Report already exists: $reportPath" }

for ($pair = 1; $pair -le $Pairs; $pair++) {
    $cliRoot = Join-Path $out "paired-$RunId-p$pair-cli"
    $benchmarkRoot = Join-Path $out "corpus-reference-B-8-$RunId-p$pair-r1"
    $benchmarkResult = Join-Path $out "results-$RunId-p$pair.json"
    foreach ($path in @($cliRoot, $benchmarkRoot, $benchmarkResult)) {
        if (Test-Path -LiteralPath $path) { throw "Fresh output required: $path" }
    }
}

$measurements = @()
$byteIdenticalPairs = @()
for ($pair = 1; $pair -le $Pairs; $pair++) {
    $order = if ($pair % 2) { @('cli', 'benchmark') } else { @('benchmark', 'cli') }
    $cliRoot = Join-Path $out "paired-$RunId-p$pair-cli"
    $benchmarkRoot = Join-Path $out "corpus-reference-B-8-$RunId-p$pair-r1"
    foreach ($path in $order) {
        $corpusRoot = if ($path -eq 'cli') { $cliRoot } else { $benchmarkRoot }
        $arguments = if ($path -eq 'cli') {
            @('-m', 'sts2_native_sim.cli', 'scenario', '--character', 'IRONCLAD', '--character', 'DEFECT',
                '--ascension', '0', '--ascension', '2') + $seeds +
                @('--workers', '8', '--compression', '3', '--output-dir', $corpusRoot)
        } else {
            @('python/tools/benchmark_scenario_generation.py', "$RunId-p$pair", '--reference', 'B')
        }
        $log = Join-Path $out "paired-$RunId-p$pair-$path.log"
        $startedUtc = (Get-Date).ToUniversalTime().ToString('o')
        $watch = [Diagnostics.Stopwatch]::StartNew()
        & $python @arguments *> $log
        $exitCode = $LASTEXITCODE
        $watch.Stop()
        if ($exitCode -ne 0) { throw "$path failed in pair $pair; see $log" }
        $summary = Get-Content -LiteralPath (Join-Path $corpusRoot 'summary.json') -Raw | ConvertFrom-Json
        if ($summary.elements -ne 512 -or $summary.workers -ne 8 -or $summary.compression -ne 3 -or
            $summary.request.characters.Count -ne 2 -or $summary.request.ascensions.Count -ne 2 -or
            $summary.request.seeds.Count -ne 128 -or -not $summary.complete) {
            throw "Unexpected reference B summary in pair $pair ($path)"
        }
        $internalSeconds = $null
        if ($path -eq 'benchmark') {
            $benchmarkResult = Join-Path $out "results-$RunId-p$pair.json"
            $internalSeconds = (Get-Content -LiteralPath $benchmarkResult -Raw | ConvertFrom-Json).corpora[0].wall_seconds
        }
        $measurement = [pscustomobject]@{
            pair = $pair
            order = [Array]::IndexOf($order, $path) + 1
            path = $path
            started_utc = $startedUtc
            external_wall_seconds = $watch.Elapsed.TotalSeconds
            benchmark_internal_seconds = $internalSeconds
            elements = $summary.elements
            rows = $summary.total
            succeeded = $summary.succeeded
            failed = $summary.failed
            worker_replacements = $summary.worker_replacements
        }
        $measurements += $measurement
        Write-Host ("pair {0} / {1}: {2:N3} s, {3} rows, {4} replacements" -f
            $pair, $path, $measurement.external_wall_seconds, $measurement.rows, $measurement.worker_replacements)
    }
    $cliHashes = @(Get-ChildItem -LiteralPath $cliRoot -File | Sort-Object Name |
        ForEach-Object { "{0}:{1}" -f $_.Name, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash })
    $benchmarkHashes = @(Get-ChildItem -LiteralPath $benchmarkRoot -File | Sort-Object Name |
        ForEach-Object { "{0}:{1}" -f $_.Name, (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash })
    $sameBytes = (@(Compare-Object $cliHashes $benchmarkHashes).Count -eq 0)
    $byteIdenticalPairs += $sameBytes
    if (-not $sameBytes) { throw "Corpus bytes differ in pair $pair" }
}

[pscustomobject]@{
    run_id = $RunId
    head = (git -C $root rev-parse HEAD)
    measurements = $measurements
    byte_identical_pairs = $byteIdenticalPairs
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding utf8
Write-Host "Paired report: $reportPath"
