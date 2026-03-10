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

    Write-Info "Building initialization image..."
    Invoke-DockerCompose -Arguments @("--profile", "init", "build", "stack-init")

    Write-Info "Starting required infrastructure services..."
    Invoke-DockerCompose -Arguments @("up", "-d", "--remove-orphans", "postgres", "minio", "qdrant")

    Write-Info "Running explicit stack initialization..."
    Invoke-DockerCompose -Arguments @("--profile", "init", "run", "--rm", "stack-init")
    Write-Ok "Stack initialization completed"
}
catch {
    Write-Host "[FAIL] $($_.Exception.Message)"
    exit 1
}
