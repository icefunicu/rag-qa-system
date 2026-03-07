#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [switch]$SkipEncodingCheck,
    [switch]$SkipBackendCompile,
    [switch]$SkipFrontendBuild,
    [switch]$SkipDockerConfig,
    [switch]$IncludeDockerBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "..\dev\common.ps1")

$repoRoot = Get-RepoRoot
$python = Get-PythonCommandSpec
$failures = New-Object System.Collections.Generic.List[string]
$totalChecks = 0

function Invoke-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $script:totalChecks++
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "[$script:totalChecks] $Name"
    Write-Host ("=" * 60)

    try {
        & $Action
        Write-Ok "$Name passed"
    }
    catch {
        Write-Warn "$Name failed: $($_.Exception.Message)"
        $script:failures.Add($Name)
    }
}

function Invoke-RepoTool {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $repoRoot
    )

    Invoke-ExternalCommand -Command $Command -Arguments $Arguments -WorkingDirectory $WorkingDirectory
}

if (-not $SkipEncodingCheck) {
    Invoke-Check "Encoding Check" {
        $args = @($python.BaseArguments) + @("scripts/quality/check-encoding.py")
        Invoke-RepoTool -Command $python.Command -Arguments $args
    }
}

if (-not $SkipBackendCompile) {
    Invoke-Check "Python Backend Compile" {
        $args = @($python.BaseArguments) + @(
            "-m",
            "compileall",
            "packages/shared/python",
            "apps/backend/gateway",
            "apps/backend/novel-service",
            "apps/backend/kb-service"
        )
        Invoke-RepoTool -Command $python.Command -Arguments $args
    }
}

if (-not $SkipFrontendBuild) {
    Invoke-Check "Frontend Build" {
        Invoke-RepoTool -Command "npm" -Arguments @("run", "build") -WorkingDirectory (Resolve-RepoPath -RelativePath "apps\web")
    }
}

if (-not $SkipDockerConfig) {
    Invoke-Check "Docker Compose Config" {
        Invoke-DockerCompose -Arguments @("config", "--quiet")
    }
}

if ($IncludeDockerBuild) {
    Invoke-Check "Docker Build" {
        Invoke-DockerCompose -Arguments @("build", "--pull")
    }
}

Write-Host ""
Write-Host ("=" * 60)
Write-Host "CI Check Summary"
Write-Host ("=" * 60)
Write-Host "Total checks: $totalChecks"

if ($failures.Count -eq 0) {
    Write-Ok "All checks passed"
    exit 0
}

Write-Warn "$($failures.Count) checks failed"
foreach ($failure in $failures) {
    Write-Host "  - $failure"
}
exit 1
