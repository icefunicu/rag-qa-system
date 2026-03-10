[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\common.ps1"

try {
    $repoRoot = Get-RepoRoot
    Set-Location $repoRoot

    Write-Info "Repo root: $repoRoot"
    Assert-DockerReady
    Assert-EnvFile

    Write-Info "Checking text encodings..."
    Invoke-ExternalCommand -Command "python" -Arguments @("scripts/quality/check-encoding.py")

    Write-Info "Building frontend..."
    Invoke-ExternalCommand -Command "npm" -Arguments @("run", "build") -WorkingDirectory (Join-Path $repoRoot "apps/web")

    Write-Info "Compiling Python services..."
    Invoke-ExternalCommand -Command "python" -Arguments @("-m", "compileall", "packages/python", "apps/services/api-gateway", "apps/services/knowledge-base")

    Write-Info "Running backend test suite..."
    Invoke-ExternalCommand -Command "python" -Arguments @("-m", "pytest", "tests", "-q")

    Write-Info "Validating compose config..."
    Invoke-ExternalCommand -Command "docker" -Arguments @("compose", "config", "--quiet")

    Write-Ok "Preflight checks completed"
}
catch {
    Write-Host "[FAIL] $($_.Exception.Message)"
    exit 1
}
