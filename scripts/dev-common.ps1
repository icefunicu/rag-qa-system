Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:DevStateDir = Join-Path $script:RepoRoot "logs\dev"
$script:FrontendPidFile = Join-Path $script:DevStateDir "frontend.pid"
$script:FrontendLogFile = Join-Path $script:DevStateDir "frontend.log"
$script:ComposeServicesCache = $null
$script:EnvSettingsCache = $null

function Write-Info {
    param(
        [Parameter(Mandatory = $true)][string]$Message
    )

    Write-Host "[INFO] $Message"
}

function Write-Ok {
    param(
        [Parameter(Mandatory = $true)][string]$Message
    )

    Write-Host "[OK] $Message"
}

function Write-Warn {
    param(
        [Parameter(Mandatory = $true)][string]$Message
    )

    Write-Host "[WARN] $Message"
}

function Get-RepoRoot {
    return $script:RepoRoot
}

function Resolve-RepoPath {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    return Join-Path $script:RepoRoot $RelativePath
}

function Get-DevStateDir {
    return $script:DevStateDir
}

function Get-FrontendPidFile {
    return $script:FrontendPidFile
}

function Get-FrontendLogFile {
    return $script:FrontendLogFile
}

function Ensure-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Ensure-DevStateDir {
    Ensure-Directory -Path $script:DevStateDir
}

function Test-CommandInstalled {
    param(
        [Parameter(Mandatory = $true)][string]$Name
    )

    return ($null -ne (Get-Command $Name -ErrorAction SilentlyContinue))
}

function Assert-CommandInstalled {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$InstallHint = ""
    )

    if (Test-CommandInstalled -Name $Name) {
        return
    }

    if ($InstallHint) {
        throw "$Name not found. $InstallHint"
    }

    throw "$Name not found."
}

function Get-PythonCommandSpec {
    if (Test-CommandInstalled -Name "python") {
        return [PSCustomObject]@{
            Command       = "python"
            BaseArguments = @()
        }
    }

    if (Test-CommandInstalled -Name "py") {
        return [PSCustomObject]@{
            Command       = "py"
            BaseArguments = @("-3")
        }
    }

    throw "Python runtime not found. Install Python first."
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $script:RepoRoot
    )

    $items = @($Arguments)
    Push-Location $WorkingDirectory
    try {
        & $Command @items
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($exitCode -ne 0) {
        $rendered = if ($items.Count -gt 0) { " $($items -join ' ')" } else { "" }
        throw ("Command failed with exit code {0}: {1}{2}" -f $exitCode, $Command, $rendered)
    }
}

function Invoke-ExternalCapture {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $script:RepoRoot
    )

    $items = @($Arguments)
    Push-Location $WorkingDirectory
    try {
        $output = & $Command @items 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    $text = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    if ($exitCode -ne 0) {
        if ($text.Trim()) {
            throw $text.Trim()
        }

        $rendered = if ($items.Count -gt 0) { " $($items -join ' ')" } else { "" }
        throw ("Command failed with exit code {0}: {1}{2}" -f $exitCode, $Command, $rendered)
    }

    return $text.TrimEnd()
}

function Test-DockerReady {
    if (-not (Test-CommandInstalled -Name "docker")) {
        return $false
    }

    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Assert-DockerReady {
    Assert-CommandInstalled -Name "docker" -InstallHint "Install Docker Desktop first."
    if (-not (Test-DockerReady)) {
        throw "Docker daemon is not running. Start Docker Desktop first."
    }
}

function Assert-EnvFile {
    $envFile = Resolve-RepoPath -RelativePath ".env"
    if (Test-Path $envFile) {
        return
    }

    throw ".env file not found. Copy .env.example to .env and fill in the required values first."
}

function Normalize-EnvValue {
    param(
        [string]$Value
    )

    $candidate = $Value.Trim()
    if ($candidate.Length -ge 2) {
        $quote = $candidate[0]
        if (($quote -eq '"' -or $quote -eq "'") -and $candidate[$candidate.Length - 1] -eq $quote) {
            return $candidate.Substring(1, $candidate.Length - 2)
        }
    }

    return $candidate
}

function Get-EnvSettings {
    if ($null -ne $script:EnvSettingsCache) {
        return $script:EnvSettingsCache
    }

    Assert-EnvFile
    $envFile = Resolve-RepoPath -RelativePath ".env"
    $settings = @{}

    foreach ($line in Get-Content -Path $envFile) {
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $key = $matches[1]
            $value = Normalize-EnvValue -Value $matches[2]
            $settings[$key] = $value
        }
    }

    $script:EnvSettingsCache = $settings
    return $script:EnvSettingsCache
}

function Convert-OllamaBaseUrlToHostUrl {
    param(
        [string]$BaseUrl
    )

    $candidate = $BaseUrl.Trim()
    if (-not $candidate) {
        $candidate = "http://127.0.0.1:11434/v1"
    }

    $candidate = $candidate.TrimEnd("/")
    $candidate = $candidate -replace "host\.docker\.internal", "127.0.0.1"
    if ($candidate -notmatch "/v1$") {
        $candidate = "$candidate/v1"
    }

    return $candidate
}

function Assert-LocalOllamaReady {
    $settings = Get-EnvSettings
    $targets = @()
    $embeddingProvider = if ($settings.ContainsKey("EMBEDDING_PROVIDER")) { $settings["EMBEDDING_PROVIDER"] } else { "" }
    $embeddingModel = if ($settings.ContainsKey("EMBEDDING_MODEL")) { $settings["EMBEDDING_MODEL"] } else { "" }
    $chatProvider = if ($settings.ContainsKey("CHAT_PROVIDER")) { $settings["CHAT_PROVIDER"] } else { "" }
    $chatModel = if ($settings.ContainsKey("CHAT_MODEL")) { $settings["CHAT_MODEL"] } else { "" }
    $ollamaBaseUrl = if ($settings.ContainsKey("OLLAMA_BASE_URL")) { $settings["OLLAMA_BASE_URL"] } else { "" }

    if ($embeddingProvider.ToLowerInvariant() -eq "ollama" -and $embeddingModel.Trim()) {
        $targets += [PSCustomObject]@{
            Role  = "embedding"
            Model = $embeddingModel.Trim()
        }
    }

    if ($chatProvider.ToLowerInvariant() -eq "ollama" -and $chatModel.Trim()) {
        $targets += [PSCustomObject]@{
            Role  = "chat"
            Model = $chatModel.Trim()
        }
    }

    if ($targets.Count -eq 0) {
        return
    }

    $baseUrl = Convert-OllamaBaseUrlToHostUrl -BaseUrl $ollamaBaseUrl
    try {
        $uri = [Uri]$baseUrl
    }
    catch {
        throw "OLLAMA_BASE_URL is invalid: $baseUrl"
    }

    if ($uri.Host -notin @("127.0.0.1", "localhost")) {
        Write-Warn "Skip Ollama preflight for non-local host: $($uri.Host)"
        return
    }

    $tagsUrl = if ($baseUrl -match "/v1$") {
        $baseUrl -replace "/v1$", "/api/tags"
    }
    else {
        "$baseUrl/api/tags"
    }

    try {
        $response = Invoke-RestMethod -Method Get -Uri $tagsUrl -TimeoutSec 5
    }
    catch {
        throw "Local Ollama is not reachable at $tagsUrl. Start Ollama first, then retry."
    }

    $availableModels = @($response.models | ForEach-Object { $_.name })
    foreach ($target in $targets) {
        if ($target.Model -notin $availableModels) {
            throw "Ollama model missing for $($target.Role): $($target.Model). Available models: $($availableModels -join ', ')"
        }

        Write-Ok "Ollama $($target.Role) model ready: $($target.Model)"
    }
}

function Invoke-DockerCompose {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $composeArgs = @("compose") + @($Arguments)
    Invoke-ExternalCommand -Command "docker" -Arguments $composeArgs -WorkingDirectory $script:RepoRoot
}

function Invoke-DockerComposeCapture {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $composeArgs = @("compose") + @($Arguments)
    return Invoke-ExternalCapture -Command "docker" -Arguments $composeArgs -WorkingDirectory $script:RepoRoot
}

function Get-ComposeServices {
    if ($null -ne $script:ComposeServicesCache) {
        return $script:ComposeServicesCache
    }

    $raw = Invoke-DockerComposeCapture -Arguments @("config", "--services")
    $services = @(
        $raw -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )

    if ($services.Count -eq 0) {
        throw "No compose services found."
    }

    $script:ComposeServicesCache = $services
    return ,$script:ComposeServicesCache
}

function Assert-ComposeServicesExist {
    param(
        [Parameter(Mandatory = $true)][string[]]$ServiceNames
    )

    $available = Get-ComposeServices
    $missing = @(
        $ServiceNames |
            Where-Object { $_ -and $_ -ne "frontend" } |
            Where-Object { $_ -notin $available }
    )

    if ($missing.Count -gt 0) {
        throw "Unknown compose service(s): $($missing -join ', ')"
    }
}

function Get-ComposeServiceContainerIds {
    param(
        [Parameter(Mandatory = $true)][string]$ServiceName
    )

    $raw = Invoke-DockerComposeCapture -Arguments @("ps", "-aq", $ServiceName)
    if (-not $raw.Trim()) {
        return ,@()
    }

    return ,@(
        $raw -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )
}

function Reset-ComposeOneShotServices {
    param(
        [string[]]$ServiceNames = @("db-migrate", "minio-init")
    )

    $available = Get-ComposeServices
    foreach ($serviceName in $ServiceNames) {
        if ($serviceName -notin $available) {
            continue
        }

        $containerIds = Get-ComposeServiceContainerIds -ServiceName $serviceName
        if ($containerIds.Count -eq 0) {
            continue
        }

        Write-Info "Resetting one-shot service: $serviceName"
        Invoke-DockerCompose -Arguments @("rm", "-f", "-s", $serviceName)
    }
}

function Test-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Url
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    }
    catch {
        return $false
    }
}

function Wait-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$RetryCount = 60,
        [int]$RetryIntervalSeconds = 2
    )

    for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
        if (Test-HttpOk -Url $Url) {
            Write-Ok "$Name ready: $Url"
            return
        }

        Start-Sleep -Seconds $RetryIntervalSeconds
    }

    throw "[FAIL] $Name readiness timeout: $Url"
}

function Wait-CoreServices {
    param(
        [int]$RetryCount = 60,
        [int]$RetryIntervalSeconds = 2
    )

    $targets = @(
        [PSCustomObject]@{
            Name = "go-api"
            Url  = "http://localhost:8080/healthz?depth=basic"
        },
        [PSCustomObject]@{
            Name = "py-rag-service"
            Url  = "http://localhost:8000/healthz?depth=basic"
        }
    )

    foreach ($target in $targets) {
        Wait-HttpOk -Url $target.Url -Name $target.Name -RetryCount $RetryCount -RetryIntervalSeconds $RetryIntervalSeconds
    }
}

function Test-FrontendDependenciesCurrent {
    $frontendDir = Resolve-RepoPath -RelativePath "apps\web"
    $nodeModules = Join-Path $frontendDir "node_modules"

    if (-not (Test-Path $nodeModules)) {
        return $false
    }

    return $true
}

function Get-FrontendDependencyDriftMessage {
    $frontendDir = Resolve-RepoPath -RelativePath "apps\web"
    $lockFile = Join-Path $frontendDir "package-lock.json"
    $nodeModules = Join-Path $frontendDir "node_modules"
    $installedLockFile = Join-Path $nodeModules ".package-lock.json"

    if (-not (Test-Path $lockFile) -or -not (Test-Path $installedLockFile)) {
        return $null
    }

    $sourceHash = (Get-FileHash -Path $lockFile -Algorithm SHA256).Hash
    $installedHash = (Get-FileHash -Path $installedLockFile -Algorithm SHA256).Hash
    if ($sourceHash -eq $installedHash) {
        return $null
    }

    return "Frontend dependencies may be stale because package-lock.json has changed since the last install. If frontend startup fails, run npm ci in apps/web."
}

function Ensure-FrontendDependencies {
    $frontendDir = Resolve-RepoPath -RelativePath "apps\web"
    $packageJson = Join-Path $frontendDir "package.json"
    $lockFile = Join-Path $frontendDir "package-lock.json"

    if (-not (Test-Path $packageJson)) {
        throw "apps/web/package.json not found."
    }

    if (Test-FrontendDependenciesCurrent) {
        $driftMessage = Get-FrontendDependencyDriftMessage
        if ($driftMessage) {
            Write-Warn $driftMessage
        }
        return
    }

    Assert-CommandInstalled -Name "npm" -InstallHint "Install Node.js first."

    Write-Info "Installing frontend dependencies..."
    Push-Location $frontendDir
    try {
        if (Test-Path $lockFile) {
            & npm ci
        }
        else {
            & npm install
        }

        if ($LASTEXITCODE -ne 0) {
            throw "npm dependency install failed."
        }
    }
    finally {
        Pop-Location
    }
}

function Get-ManagedFrontendPid {
    Ensure-DevStateDir

    if (-not (Test-Path $script:FrontendPidFile)) {
        return $null
    }

    $raw = Get-Content -Path $script:FrontendPidFile -TotalCount 1 -ErrorAction SilentlyContinue
    if ($null -eq $raw) {
        Remove-Item -Path $script:FrontendPidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    $raw = $raw.Trim()
    if (-not $raw) {
        Remove-Item -Path $script:FrontendPidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    $parsedPid = 0
    if (-not [int]::TryParse($raw, [ref]$parsedPid)) {
        Remove-Item -Path $script:FrontendPidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    $proc = Get-Process -Id $parsedPid -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Remove-Item -Path $script:FrontendPidFile -Force -ErrorAction SilentlyContinue
        return $null
    }

    return $parsedPid
}

function Stop-ManagedFrontend {
    $frontendProcessId = Get-ManagedFrontendPid
    if ($null -eq $frontendProcessId) {
        return $false
    }

    & taskkill /PID $frontendProcessId /T /F *> $null
    $exitCode = $LASTEXITCODE
    Remove-Item -Path $script:FrontendPidFile -Force -ErrorAction SilentlyContinue

    if ($exitCode -ne 0) {
        Write-Warn "Failed to stop frontend process tree. PID=$frontendProcessId"
        return $false
    }

    Write-Info "Frontend process stopped. PID=$frontendProcessId"
    return $true
}

function Get-ManagedPowerShellCommand {
    if (Test-CommandInstalled -Name "pwsh") {
        return "pwsh"
    }

    return "powershell"
}

function Start-ManagedFrontend {
    param(
        [int]$Port = 5173,
        [switch]$WaitUntilReady,
        [int]$RetryCount = 60,
        [int]$RetryIntervalSeconds = 2
    )

    $frontendDir = Resolve-RepoPath -RelativePath "apps\web"
    $frontendUrl = "http://localhost:$Port"
    $existingPid = Get-ManagedFrontendPid

    if ($null -ne $existingPid -and (Test-HttpOk -Url $frontendUrl)) {
        Write-Info "Frontend already running. PID=$existingPid URL=$frontendUrl"
        return [PSCustomObject]@{
            Url     = $frontendUrl
            Pid     = $existingPid
            Managed = $true
        }
    }

    if ($null -ne $existingPid) {
        Write-Warn "Removing stale frontend process. PID=$existingPid"
        Stop-ManagedFrontend | Out-Null
    }

    if (Test-HttpOk -Url $frontendUrl) {
        Write-Info "Frontend already running outside managed script: $frontendUrl"
        return [PSCustomObject]@{
            Url     = $frontendUrl
            Pid     = $null
            Managed = $false
        }
    }

    Ensure-FrontendDependencies
    Ensure-DevStateDir
    $dependencyDriftMessage = Get-FrontendDependencyDriftMessage

    $runnerScript = Resolve-RepoPath -RelativePath "scripts\frontend-runner.ps1"
    $runnerShell = Get-ManagedPowerShellCommand
    $runnerArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $runnerScript,
        "-RepoRoot",
        $script:RepoRoot,
        "-Port",
        "$Port",
        "-LogFile",
        $script:FrontendLogFile
    )

    $proc = Start-Process -FilePath $runnerShell -ArgumentList $runnerArgs -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 1

    $frontendRetryCount = if ($WaitUntilReady) { $RetryCount } else { [Math]::Min([Math]::Max($RetryCount, 10), 10) }
    try {
        Wait-HttpOk -Url $frontendUrl -Name "frontend" -RetryCount $frontendRetryCount -RetryIntervalSeconds $RetryIntervalSeconds
    }
    catch {
        $details = ""
        if (Test-Path $script:FrontendLogFile) {
            $details = (Get-Content -Path $script:FrontendLogFile -Tail 20 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        }
        if ($dependencyDriftMessage) {
            if ($details) {
                $details = "$details`n$dependencyDriftMessage"
            }
            else {
                $details = $dependencyDriftMessage
            }
        }

        if ($null -eq (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
            if ($details) {
                throw "Frontend process exited early.`n$details"
            }

            throw "Frontend process exited early."
        }

        & taskkill /PID $proc.Id /T /F *> $null
        if ($details) {
            throw "Frontend readiness timeout.`n$details"
        }

        throw
    }

    $runningProc = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if ($null -eq $runningProc) {
        throw "Frontend runner exited unexpectedly after readiness check."
    }

    [System.IO.File]::WriteAllText($script:FrontendPidFile, "$($proc.Id)", (New-Object System.Text.UTF8Encoding($false)))
    Write-Info "Frontend process started. PID=$($proc.Id) URL=$frontendUrl"

    if ($WaitUntilReady) {
        return [PSCustomObject]@{
            Url     = $frontendUrl
            Pid     = $proc.Id
            Managed = $true
        }
    }

    return [PSCustomObject]@{
        Url     = $frontendUrl
        Pid     = $proc.Id
        Managed = $true
    }
}

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowNull()][AllowEmptyCollection()][object[]]$Lines
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        Ensure-Directory -Path $parent
    }

    $text = if ($null -eq $Lines -or $Lines.Count -eq 0) {
        ""
    }
    else {
        [string]::Join([Environment]::NewLine, [string[]]$Lines)
    }

    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

function Write-ProjectSummary {
    param(
        [int]$FrontendPort = 5173,
        [switch]$FrontendSkipped,
        [object]$FrontendInfo = $null
    )

    Write-Host ""
    Write-Host "[DONE] Project is ready."
    Write-Host "API Gateway:   http://localhost:8080"
    Write-Host "RAG Service:   http://localhost:8000"
    Write-Host "MinIO API:     http://localhost:19000"
    Write-Host "MinIO Console: http://localhost:19001"

    if (-not $FrontendSkipped) {
        if ($null -ne $FrontendInfo) {
            Write-Host "Frontend Dev:  $($FrontendInfo.Url)"
            if ($FrontendInfo.Managed) {
                Write-Host "Frontend Log:  $script:FrontendLogFile"
            }
            else {
                Write-Host "Frontend Log:  external process (not managed)"
            }
        }
        else {
            Write-Host "Frontend Dev:  http://localhost:$FrontendPort"
        }
    }

    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  Start:       .\scripts\dev-up.ps1"
    Write-Host "  Stop:        .\scripts\dev-down.ps1"
    Write-Host "  CI:          .\scripts\ci-check.ps1"
    Write-Host "  Live logs:   .\logs.bat -f"
    Write-Host "  Export logs: .\scripts\aggregate-logs.ps1"
    Write-Host ""
}
