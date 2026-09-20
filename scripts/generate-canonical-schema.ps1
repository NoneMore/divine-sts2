param(
    [string]$OutputPath = (Join-Path $PSScriptRoot "..\schemas\canonical-state.schema.json")
)

. (Join-Path $PSScriptRoot "common.ps1")

Invoke-DivineDotnet run `
    --project (Join-Path $PSScriptRoot "..\tools\Sts2.NativeSim.SchemaExporter\Sts2.NativeSim.SchemaExporter.csproj") `
    --no-launch-profile `
    -- $OutputPath
