[CmdletBinding()]
param(
    [string]$OutputDir = ".\logs\export",
    [int]$Tail = 500,
    [string[]]$Service
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dev-common.ps1")

function Split-ServiceSelection {
    param(
        [string[]]$RequestedServices
    )

    if (-not $RequestedServices -or $RequestedServices.Count -eq 0) {
        return [PSCustomObject]@{
            DockerServices  = Get-ComposeServices
            IncludeFrontend = $true
        }
    }

    $dockerServices = New-Object System.Collections.Generic.List[string]
    $includeFrontend = $false

    foreach ($item in $RequestedServices) {
        $segments = @($item -split ",")
        foreach ($segment in $segments) {
            $name = $segment.Trim()
            if (-not $name) {
                continue
            }

            if ($name -eq "frontend") {
                $includeFrontend = $true
                continue
            }

            $dockerServices.Add($name)
        }
    }

    Assert-ComposeServicesExist -ServiceNames @($dockerServices)

    return [PSCustomObject]@{
        DockerServices  = @($dockerServices | Select-Object -Unique)
        IncludeFrontend = $includeFrontend
    }
}

function Get-ComposeLogsText {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][int]$LineCount
    )

    $output = & docker compose logs --no-color --timestamps --tail $LineCount $ServiceName 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine

    return [PSCustomObject]@{
        ExitCode = $exitCode
        Text     = $text.TrimEnd()
    }
}

function Normalize-LogLine {
    param(
        [AllowEmptyString()][string]$Line
    )

    $cleaned = [regex]::Replace($Line, "$([char]27)\[[0-?]*[ -/]*[@-~]", "").TrimEnd()
    $cleaned = $cleaned.Replace("閴?", ">")
    if ($cleaned -match '^[^A-Za-z/\[]*(Local:|Network:|press\s)') {
        $cleaned = [regex]::Replace($cleaned, '^[^A-Za-z/\[]*(Local:|Network:|press\s)', '> $1')
    }

    return $cleaned
}

function Add-NormalizedLogLines {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [string[]]$Lines,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.List[string]]$CombinedLines,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.List[string]]$ErrorLines,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.List[string]]$WarningLines
    )

    foreach ($line in $Lines) {
        $normalizedLine = Normalize-LogLine -Line $line
        if (-not $normalizedLine) {
            continue
        }

        $withSource = "$Source | $normalizedLine"
        $CombinedLines.Add($withSource)

        if ($normalizedLine -match "\b(ERROR|FATAL|CRITICAL)\b") {
            $ErrorLines.Add($withSource)
        }
        elseif ($normalizedLine -match "\bWARN(ING)?\b") {
            $WarningLines.Add($withSource)
        }
    }
}

$repoRoot = Get-RepoRoot
Set-Location $repoRoot

if ($Tail -le 0) {
    throw "Tail must be greater than 0."
}

$selection = Split-ServiceSelection -RequestedServices $Service
$frontendLogFile = Get-FrontendLogFile
$dockerReady = Test-DockerReady

if (-not $dockerReady -and -not (Test-Path $frontendLogFile)) {
    throw "Docker is unavailable and no managed frontend log file exists."
}

$outputRoot = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir
}
else {
    Join-Path $repoRoot $OutputDir
}

$allDir = Join-Path $outputRoot "ALL"
$errorDir = Join-Path $outputRoot "ERROR"
$warningDir = Join-Path $outputRoot "WARNING"

foreach ($dir in @($outputRoot, $allDir, $errorDir, $warningDir)) {
    Ensure-Directory -Path $dir
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$allLogs = @{}
$combinedLines = New-Object System.Collections.Generic.List[string]
$errorLines = New-Object System.Collections.Generic.List[string]
$warningLines = New-Object System.Collections.Generic.List[string]
$collectionErrors = New-Object System.Collections.Generic.List[string]

Write-Info "Output directory: $outputRoot"

if ($dockerReady) {
    $dockerServices = @($selection.DockerServices)
    if ($dockerServices.Count -gt 0) {
        Write-Info "Collecting compose logs for: $($dockerServices -join ', ')"
    }

    foreach ($serviceName in $dockerServices) {
        $result = Get-ComposeLogsText -ServiceName $serviceName -LineCount $Tail
        if ($result.ExitCode -ne 0) {
            $collectionErrors.Add("$serviceName | $($result.Text)")
            Write-Warn "Failed to collect $serviceName"
            continue
        }

        $allLogs[$serviceName] = $result.Text
        Add-NormalizedLogLines -Source $serviceName -Lines ($result.Text -split "`r?`n") -CombinedLines $combinedLines -ErrorLines $errorLines -WarningLines $warningLines
    }
}
else {
    Write-Warn "Docker is unavailable. Only frontend log snapshot will be exported."
}

if ($selection.IncludeFrontend) {
    if (Test-Path $frontendLogFile) {
        $frontendLines = @(Get-Content -Path $frontendLogFile -Tail $Tail -ErrorAction SilentlyContinue)
        $frontendText = ($frontendLines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        $allLogs["frontend"] = $frontendText
        Add-NormalizedLogLines -Source "frontend" -Lines $frontendLines -CombinedLines $combinedLines -ErrorLines $errorLines -WarningLines $warningLines
    }
    else {
        $collectionErrors.Add("frontend | managed frontend log file not found")
    }
}

if ($allLogs.Count -eq 0) {
    throw "No logs were collected."
}

foreach ($serviceName in ($allLogs.Keys | Sort-Object)) {
    $targetFile = Join-Path $allDir "$serviceName.log"
    Write-Utf8File -Path $targetFile -Lines @($allLogs[$serviceName] -split "`r?`n")
    Write-Ok $targetFile
}

$combinedFile = Join-Path $outputRoot "combined_$timestamp.log"
Write-Utf8File -Path $combinedFile -Lines $combinedLines
Write-Ok $combinedFile

if ($errorLines.Count -gt 0) {
    $errorFile = Join-Path $errorDir "errors_$timestamp.log"
    Write-Utf8File -Path $errorFile -Lines $errorLines
    Write-Ok $errorFile
}

if ($warningLines.Count -gt 0) {
    $warningFile = Join-Path $warningDir "warnings_$timestamp.log"
    Write-Utf8File -Path $warningFile -Lines $warningLines
    Write-Ok $warningFile
}

$summary = @()
$summary += "RAG QA System log export"
$summary += "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$summary += "Tail: $Tail"
$summary += ""
$summary += "Collected services:"
$summary += ($allLogs.Keys | Sort-Object | ForEach-Object { "- $_" })
$summary += ""
$summary += "Combined log:"
$summary += "- $combinedFile"
$summary += ""
$summary += "Error lines: $($errorLines.Count)"
$summary += "Warning lines: $($warningLines.Count)"
$summary += "Collection failures: $($collectionErrors.Count)"

if ($collectionErrors.Count -gt 0) {
    $summary += ""
    $summary += "Collection failures:"
    $summary += ($collectionErrors | ForEach-Object { "- $_" })
}

$summaryFile = Join-Path $outputRoot "summary_$timestamp.txt"
Write-Utf8File -Path $summaryFile -Lines $summary
Write-Ok $summaryFile
