[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$LogFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$frontendDir = Join-Path $RepoRoot "apps\web"
if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
    throw "apps/web/package.json not found."
}

$logDir = Split-Path -Parent $LogFile
if ($logDir -and -not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$env:NO_COLOR = "1"
$env:FORCE_COLOR = "0"

Push-Location $frontendDir
try {
    $command = "chcp 65001>nul && set NO_COLOR=1 && set FORCE_COLOR=0 && npm run dev -- --host 0.0.0.0 --port $Port --clearScreen false >> `"$LogFile`" 2>&1"
    & cmd.exe /d /c $command
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
