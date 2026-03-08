[CmdletBinding()]
param(
    [switch]$RemoveVolumes,
    [switch]$RemoveImages,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\common.ps1"

$repoRoot = Get-RepoRoot
Set-Location $repoRoot

Write-Info "Repo root: $repoRoot"

$managedFrontendPid = Get-ManagedFrontendPid
$dockerReady = Test-DockerReady
$composeArgs = @("down", "--remove-orphans")

if ($RemoveVolumes) {
    $composeArgs += "--volumes"
}

if ($RemoveImages) {
    $composeArgs += @("--rmi", "all")
}

if (-not $Force) {
    $actions = New-Object System.Collections.Generic.List[string]
    $actions.Add("stop compose services")
    if ($null -ne $managedFrontendPid) {
        $actions.Add("stop managed frontend PID $managedFrontendPid")
    }
    if ($RemoveVolumes) {
        $actions.Add("remove named volumes")
    }
    if ($RemoveImages) {
        $actions.Add("remove built images")
    }
    if (-not $dockerReady) {
        $actions.Add("skip docker compose down because Docker is unavailable")
    }

    $confirmation = Read-Host -Prompt ("This will " + ($actions -join ", ") + ". Continue? (y/N)")
    if ($confirmation -notin @("y", "Y")) {
        Write-Host "[CANCEL] No changes made."
        exit 0
    }
}

if ($null -ne $managedFrontendPid) {
    Stop-ManagedFrontend | Out-Null
}
else {
    Write-Info "No managed frontend process found."
}

if ($dockerReady) {
    Write-Info "Stopping Docker services..."
    Invoke-DockerCompose -Arguments $composeArgs
}
else {
    Write-Warn "Docker daemon is not available. Skipped docker compose down."
}

Write-Host ""
Write-Host "[DONE] Project stopped."
if ($RemoveVolumes) {
    Write-Warn "Named volumes were removed."
}
if ($RemoveImages) {
    Write-Warn "Images were removed."
}
Write-Host ""
Write-Host "Start again with: .\scripts\dev\up.ps1"
