[CmdletBinding()]
param(
    [switch]$NoBuild,
    [switch]$SkipPull,
    [switch]$SkipFrontend,
    [switch]$SkipHealthCheck,
    [switch]$AttachLogs,
    [int]$FrontendPort = 5173,
    [int]$RetryCount = 60,
    [int]$RetryIntervalSeconds = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

try {
    $repoRoot = Get-RepoRoot
    Set-Location $repoRoot

    Write-Info "Repo root: $repoRoot"
    Assert-DockerReady
    Assert-EnvFile
    Assert-LocalOllamaReady

    $services = Get-ComposeServices
    Write-Info "Compose services: $($services -join ', ')"

    if ($SkipPull) {
        Write-Info "Skipping remote image pull."
    }
    else {
        Write-Info "Pulling latest prebuilt images..."
        Invoke-DockerCompose -Arguments @("pull", "--ignore-buildable", "--include-deps", "--policy", "always")
    }

    if ($NoBuild) {
        Write-Info "Skipping local image build."
    }
    else {
        Write-Info "Building local images with the latest base layers..."
        Invoke-DockerCompose -Arguments @("build", "--pull")
    }

    Write-Info "Starting Docker services..."
    Invoke-DockerCompose -Arguments @("up", "-d", "--remove-orphans")

    if ($SkipHealthCheck) {
        Write-Info "Health checks skipped."
    }
    else {
        Write-Info "Waiting for core HTTP services..."
        Wait-CoreServices -RetryCount $RetryCount -RetryIntervalSeconds $RetryIntervalSeconds
    }

    $frontendInfo = $null
    if ($SkipFrontend) {
        Write-Info "Frontend startup skipped."
    }
    else {
        $frontendInfo = Start-ManagedFrontend -Port $FrontendPort -WaitUntilReady:(-not $SkipHealthCheck) -RetryCount $RetryCount -RetryIntervalSeconds $RetryIntervalSeconds
    }

    Write-Host ""
    Write-Info "Active containers:"
    Invoke-DockerCompose -Arguments @("ps")

    Write-ProjectSummary -FrontendPort $FrontendPort -FrontendSkipped:$SkipFrontend -FrontendInfo $frontendInfo

    if ($AttachLogs) {
        $logsScript = Join-Path $repoRoot "logs.bat"
        Write-Info "Attaching real-time logs. Press Ctrl+C to stop log streaming."
        & $logsScript -f
        if ($LASTEXITCODE -notin @(0, 130)) {
            throw "Real-time log viewer exited with code $LASTEXITCODE."
        }
    }
}
catch {
    Write-Host "[FAIL] $($_.Exception.Message)"
    exit 1
}
