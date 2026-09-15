$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$toolRoot = Get-DivineToolsRoot
$destination = Join-Path $toolRoot 'dotnet9'
$installer = Join-Path $toolRoot 'dotnet-install.ps1'

New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $installer)) {
    Save-DivineDownload -Uri 'https://dot.net/v1/dotnet-install.ps1' -OutFile $installer
}
if (-not (Test-Path -LiteralPath (Join-Path $destination 'dotnet.exe'))) {
    # dotnet-install.ps1 downloads the SDK itself and takes the proxy as a parameter, so a
    # host whose proxy refuses schannel credentials is told about it rather than left guessing.
    $installerArguments = @{ Channel = '9.0'; InstallDir = $destination; NoPath = $true }
    $proxy = if ($env:HTTPS_PROXY) { $env:HTTPS_PROXY } elseif ($env:HTTP_PROXY) { $env:HTTP_PROXY } else { '' }
    if ($proxy) {
        $installerArguments.ProxyAddress = $proxy
        $installerArguments.ProxyUseDefaultCredentials = $true
    }
    & $installer @installerArguments
    $installerExit = 0
    if (Test-Path variable:LASTEXITCODE) { $installerExit = [int]$LASTEXITCODE }
    if ($installerExit -ne 0) { throw ".NET SDK installation failed with exit code $installerExit" }
    if (-not (Test-Path -LiteralPath (Join-Path $destination 'dotnet.exe'))) {
        throw ".NET SDK installation reported success, but dotnet.exe was not found under $destination."
    }
}
Write-Output (Join-Path $destination 'dotnet.exe')
