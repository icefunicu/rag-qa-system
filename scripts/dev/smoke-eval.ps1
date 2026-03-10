[CmdletBinding()]
param(
    [switch]$SkipUpload,
    [int]$RetryCount = 90,
    [int]$RetryIntervalSeconds = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\common.ps1"

try {
    $repoRoot = Get-RepoRoot
    Set-Location $repoRoot

    Write-Info "Repo root: $repoRoot"
    Assert-DockerReady
    Assert-EnvFile

    Write-Info "Waiting for core HTTP services before smoke eval..."
    Wait-CoreServices -RetryCount $RetryCount -RetryIntervalSeconds $RetryIntervalSeconds

    $args = @("scripts/dev/smoke_eval.py")
    if ($SkipUpload) {
        $args += "--skip-upload"
    }

    Write-Info "Running smoke eval..."
    Invoke-ExternalCommand -Command "python" -Arguments $args
    Write-Ok "Smoke eval completed"
}
catch {
    Write-Host "[FAIL] $($_.Exception.Message)"
    exit 1
}
