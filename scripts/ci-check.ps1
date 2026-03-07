#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [switch]$SkipEncodingCheck,
    [switch]$SkipGoFormatCheck,
    [switch]$SkipFrontendBuild,
    [switch]$SkipDockerConfig,
    [switch]$IncludeDockerBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dev-common.ps1")

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
        $args = @($python.BaseArguments) + @("scripts/check_encoding.py")
        Invoke-RepoTool -Command $python.Command -Arguments $args
    }
}

if (-not $SkipGoFormatCheck) {
    Invoke-Check "Go Format Check" {
        $goApiDir = Resolve-RepoPath -RelativePath "services\go-api"
        $files = @(
            Get-ChildItem -Path $goApiDir -Recurse -Filter "*.go" -File |
                ForEach-Object { $_.FullName }
        )

        if ($files.Count -eq 0) {
            return
        }

        $gofmtArgs = @("-l") + $files
        $output = Invoke-ExternalCapture -Command "gofmt" -Arguments $gofmtArgs -WorkingDirectory $repoRoot
        if ($output.Trim()) {
            throw "Unformatted Go files:`n$output"
        }
    }
}

Invoke-Check "Go API Tests" {
    Invoke-RepoTool -Command "go" -Arguments @("test", "./...") -WorkingDirectory (Resolve-RepoPath -RelativePath "services\go-api")
}

Invoke-Check "Python RAG Service Tests" {
    $args = @($python.BaseArguments) + @("-m", "pytest", "-q")
    Invoke-RepoTool -Command $python.Command -Arguments $args -WorkingDirectory (Resolve-RepoPath -RelativePath "services\py-rag-service")
}

Invoke-Check "Python Worker Tests" {
    $args = @($python.BaseArguments) + @("-m", "pytest", "-q")
    Invoke-RepoTool -Command $python.Command -Arguments $args -WorkingDirectory (Resolve-RepoPath -RelativePath "services\py-worker")
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
