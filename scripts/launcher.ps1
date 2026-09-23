[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectRoot,

    # `launcher.cmd /configure-ai` passes this switch to rotate a leaked,
    # revoked or otherwise invalid protected key without editing any files.
    [switch]$ConfigureAi,

    # `launcher.cmd /disable-ai` removes only this app's DPAPI secret after a
    # confirmation and starts the labelled no-AI mode.
    [switch]$DisableAi,

    # Prepare dependencies, start/check/stop the server without browser or AI calls.
    [switch]$SmokeTest
)

# This script intentionally supports Windows PowerShell 5.1 as well as newer
# PowerShell versions. It changes neither PATH, firewall settings nor the
# device execution policy.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$script:LogPath = $null

function Write-LauncherLog {
    param([Parameter(Mandatory = $true)][string]$Message)

    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    Write-Host $line
    if ($script:LogPath) {
        Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
    }
}

function Get-StringSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-ApplicationReady {
    param([Parameter(Mandatory = $true)][int]$Port)
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($health.application -ne "career-quest" -or $health.status -ne "ok") {
        throw "The local port does not belong to Career Quest."
    }
    $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/ready" -TimeoutSec 2
    if ($ready.ready -ne $true) {
        throw "Career Quest is not ready."
    }
    return $ready
}

function Test-Ready {
    param([Parameter(Mandatory = $true)][int]$Port)
    try {
        $null = Get-ApplicationReady -Port $Port
        return $true
    }
    catch {
        return $false
    }
}

function Open-CareerQuest {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$DataDirectory
    )
    $ready = Get-ApplicationReady -Port $Port
    $url = "http://127.0.0.1:$Port/"
    if ($ready.setup_required) {
        $tokenPath = Join-Path $DataDirectory "setup-token.txt"
        if (Test-Path -LiteralPath $tokenPath) {
            $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
            if ($token) {
                # Fragment stays in the browser and never enters an HTTP access log.
                $url += "#setup_token=" + [Uri]::EscapeDataString($token)
            }
        }
    }
    # Do not log this URL: its fragment can hold the one-time setup token.
    Start-Process $url
}

function Get-FreeLocalPort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Test-OpenAiConfiguration {
    param(
        [Parameter(Mandatory = $true)][System.Security.SecureString]$SecureKey,
        [Parameter(Mandatory = $true)][string]$Model
    )

    # This deliberately contains no employee or dataset context. It verifies
    # both the selected model and the strict Structured Outputs feature used
    # by recommendations before replacing a known-good local configuration.
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
    $apiKey = $null
    try {
        $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        $payload = @{
            model = $Model
            input = "Return JSON with status set to ok."
            text = @{
                format = @{
                    type = "json_schema"
                    name = "career_quest_launcher_check"
                    strict = $true
                    schema = @{
                        type = "object"
                        additionalProperties = $false
                        properties = @{
                            status = @{ type = "string" }
                        }
                        required = @("status")
                    }
                }
            }
            max_output_tokens = 1024
            store = $false
        }
        if ($Model -eq "gpt-6-luna") {
            $payload.reasoning = @{ effort = "none" }
        }
        $payload = $payload | ConvertTo-Json -Depth 10 -Compress
        $response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "https://api.openai.com/v1/responses" `
            -Method Post `
            -Headers @{ Authorization = "Bearer $apiKey" } `
            -ContentType "application/json" `
            -Body $payload `
            -TimeoutSec 9
        $responsePayload = $response.Content | ConvertFrom-Json
        if ($responsePayload.status -ne "completed") {
            return $false
        }
        $outputText = ([string]$responsePayload.output_text).Trim()
        if ([string]::IsNullOrWhiteSpace($outputText)) {
            foreach ($message in @($responsePayload.output)) {
                foreach ($content in @($message.content)) {
                    if ($content.type -eq "output_text" -and $content.text) {
                        $outputText = ([string]$content.text).Trim()
                        break
                    }
                }
                if (-not [string]::IsNullOrWhiteSpace($outputText)) {
                    break
                }
            }
        }
        if ([string]::IsNullOrWhiteSpace($outputText)) {
            return $false
        }
        $validation = $outputText | ConvertFrom-Json
        return $validation.status -eq "ok"
    }
    catch {
        # Do not expose a provider error because it can contain request details.
        return $false
    }
    finally {
        $apiKey = $null
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Test-ManagedCareerQuestInstance {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ExpectedPythonPath
    )

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        if (-not $process -or [string]::IsNullOrWhiteSpace([string]$processInfo.CommandLine)) {
            return $false
        }
        if ([string]::IsNullOrWhiteSpace([string]$processInfo.ExecutablePath)) {
            return $false
        }
        if ($processInfo.ExecutablePath -ine $ExpectedPythonPath) {
            return $false
        }
        if ($processInfo.CommandLine -notmatch [Regex]::Escape("app.main:app")) {
            return $false
        }
        if ($processInfo.CommandLine -notmatch ("--port\s+" + $Port + "(\s|$)")) {
            return $false
        }
        return Test-Ready -Port $Port
    }
    catch {
        return $false
    }
}

function Get-ProtectedApiKey {
    param(
        [Parameter(Mandatory = $true)][string]$SecretPath,
        [Parameter(Mandatory = $true)][string]$SettingsPath,
        [switch]$ConfigureAi
    )

    $script:ConfiguredModel = "gpt-6-luna"
    if (Test-Path -LiteralPath $SettingsPath) {
        try {
            $settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
            if ($settings.model -and -not [string]::IsNullOrWhiteSpace([string]$settings.model)) {
                $script:ConfiguredModel = ([string]$settings.model).Trim()
            }
        }
        catch {
            Write-LauncherLog "AI settings could not be read; using the default model."
        }
    }

    if ($ConfigureAi -or -not (Test-Path -LiteralPath $SecretPath)) {
        Write-Host ""
        if ($ConfigureAi) {
            Write-Host "Configure or replace the protected AI key."
        }
        else {
            Write-Host "AI is not configured. The app can start in its explicit AI-not-configured mode."
            $configure = Read-Host "Configure a new API key now? [y/N]"
            if ($configure -notmatch '^[YyДд]$') {
                return $null
            }
        }

        $secureKey = Read-Host -AsSecureString "OpenAI API key (hidden input)"
        if ($secureKey.Length -eq 0) {
            if ($ConfigureAi -and (Test-Path -LiteralPath $SecretPath)) {
                Write-LauncherLog "No replacement key was entered; retaining the existing protected AI configuration."
            }
            else {
                Write-LauncherLog "No AI key was entered; continuing without AI."
                return $null
            }
        }
        else {
            $selectedModel = Read-Host "Model ID [${script:ConfiguredModel}]"
            if (-not [string]::IsNullOrWhiteSpace($selectedModel)) {
                $script:ConfiguredModel = $selectedModel.Trim()
            }

            Write-LauncherLog "Checking the AI key and selected model without profile data."
            if (-not (Test-OpenAiConfiguration -SecureKey $secureKey -Model $script:ConfiguredModel)) {
                throw "The AI key or model could not be verified. No protected key was changed; check network access, credits and model access, then retry."
            }

            # ConvertFrom-SecureString uses DPAPI for the current Windows user when
            # no explicit encryption key is supplied. Only that user can decrypt it.
            $encrypted = $secureKey | ConvertFrom-SecureString
            [System.IO.File]::WriteAllText($SecretPath, $encrypted, [System.Text.Encoding]::ASCII)
            [ordered]@{ model = $script:ConfiguredModel } |
                ConvertTo-Json | Set-Content -LiteralPath $SettingsPath -Encoding UTF8
            Write-LauncherLog "Stored a user-scoped protected AI key; the secret itself was not logged."
        }
    }

    try {
        $encrypted = (Get-Content -LiteralPath $SecretPath -Raw).Trim()
        if ([string]::IsNullOrWhiteSpace($encrypted)) {
            throw "The protected AI key file is empty."
        }
        $secureKey = ConvertTo-SecureString -String $encrypted
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        try {
            return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
    catch {
        throw "The protected AI key cannot be read for this Windows user. Run 'launcher.cmd /configure-ai' to replace it."
    }
}

function Get-PinnedUv {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ToolsDirectory
    )

    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    foreach ($property in @("version", "url", "sha256")) {
        if ([string]::IsNullOrWhiteSpace([string]$manifest.$property)) {
            throw "uv manifest is missing '$property'."
        }
    }
    if ($manifest.sha256 -notmatch '^[a-fA-F0-9]{64}$') {
        throw "uv manifest contains an invalid SHA-256 value."
    }

    $uvRoot = Join-Path $ToolsDirectory ("uv-" + $manifest.version)
    $archivePath = Join-Path $ToolsDirectory ("uv-" + $manifest.version + ".zip")
    $downloadPath = $archivePath + ".download"
    $uvPath = Join-Path $uvRoot "uv.exe"
    New-Item -ItemType Directory -Path $uvRoot -Force | Out-Null

    if (-not (Test-Path -LiteralPath $archivePath)) {
        Write-LauncherLog "Downloading pinned uv $($manifest.version) from its manifest URL."
        if (Test-Path -LiteralPath $downloadPath) {
            Remove-Item -LiteralPath $downloadPath -Force
        }
        Invoke-WebRequest -UseBasicParsing -Uri $manifest.url -OutFile $downloadPath -TimeoutSec 60
        if ((Get-StringSha256 -Path $downloadPath) -ne $manifest.sha256.ToLowerInvariant()) {
            throw "The downloaded uv archive does not match the pinned SHA-256. Retry on a trusted network."
        }
        Move-Item -LiteralPath $downloadPath -Destination $archivePath -Force
    }
    if ((Get-StringSha256 -Path $archivePath) -ne $manifest.sha256.ToLowerInvariant()) {
        throw "The downloaded uv archive does not match the pinned SHA-256. Delete '$archivePath' and retry on a trusted network."
    }
    if (-not (Test-Path -LiteralPath $uvPath)) {
        Write-LauncherLog "Extracting verified uv $($manifest.version)."
        Expand-Archive -LiteralPath $archivePath -DestinationPath $uvRoot -Force
    }
    if (-not (Test-Path -LiteralPath $uvPath)) {
        throw "Verified uv archive did not contain uv.exe."
    }
    $reportedVersion = (& $uvPath --version | Out-String).Trim()
    if ($reportedVersion -notmatch ("^uv " + [Regex]::Escape([string]$manifest.version) + "(\s|$)")) {
        throw "Cached uv version '$reportedVersion' does not match pinned version '$($manifest.version)'."
    }
    return $uvPath
}

try {
    if (($ConfigureAi -and $DisableAi) -or ($SmokeTest -and ($ConfigureAi -or $DisableAi))) {
        throw "Use one of -ConfigureAi, -DisableAi or -SmokeTest."
    }
    if ($env:OS -ne "Windows_NT") {
        throw "This launcher targets Windows 10/11. Use a verified platform-specific launch method elsewhere."
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "Career Quest launcher requires 64-bit Windows."
    }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is unavailable; a per-user data directory cannot be created."
    }

    # Never pass a key inherited from a terminal to uv, an installer or any
    # subprocess other than the local server we explicitly start below.
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

    $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    foreach ($requiredPath in @(
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "app\main.py",
        "scripts\uv-manifest.json"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $requiredPath))) {
            throw "Required project file is missing: $requiredPath"
        }
    }

    $instanceRoot = if ([string]::IsNullOrWhiteSpace($env:CAREERQUEST_DATA_DIR)) {
        Join-Path $env:LOCALAPPDATA "CareerQuest\instances\hack-9be09345-jassai"
    } else {
        [System.IO.Path]::GetFullPath($env:CAREERQUEST_DATA_DIR)
    }
    $settingsDirectory = Join-Path $instanceRoot "settings"
    $logsDirectory = Join-Path $instanceRoot "logs"
    $runtimeDirectory = Join-Path $instanceRoot "runtime"
    $toolsDirectory = Join-Path $instanceRoot "tools"
    foreach ($directory in @($settingsDirectory, $logsDirectory, $runtimeDirectory, $toolsDirectory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $script:LogPath = Join-Path $logsDirectory "launcher.log"
    Write-LauncherLog "Starting Career Quest launcher."

    $secretPath = Join-Path $settingsDirectory "openai-key.dpapi"
    $settingsPath = Join-Path $settingsDirectory "ai-settings.json"
    $skipAiSetup = $false

    $venvPath = Join-Path $instanceRoot "venv"
    $pythonPath = Join-Path $venvPath "Scripts\python.exe"
    $statePath = Join-Path $runtimeDirectory "server.json"
    $state = $null
    if (Test-Path -LiteralPath $statePath) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        }
        catch {
            Write-LauncherLog "Stored server state is stale; a new local instance will be started."
        }
    }
    if ($null -ne $state) {
        $stateIsManaged = $false
        try {
            $stateIsManaged = Test-ManagedCareerQuestInstance `
                -ProcessId ([int]$state.pid) `
                -Port ([int]$state.port) `
                -ExpectedPythonPath $pythonPath
        }
        catch {
            $stateIsManaged = $false
        }
        if ($stateIsManaged) {
            if ($ConfigureAi -or $DisableAi) {
                throw "Stop the running Career Quest instance with Ctrl+C before changing its AI configuration."
            }
            if ($SmokeTest) {
                Write-LauncherLog "Launcher check passed: an existing managed instance is ready."
                exit 0
            }
            Write-LauncherLog "An existing Career Quest instance is ready; opening its browser tab."
            Open-CareerQuest -Port ([int]$state.port) -DataDirectory $instanceRoot
            exit 0
        }
        Write-LauncherLog "Stored server state is stale or is not this Career Quest instance; a new local instance will be started."
    }

    if ($DisableAi) {
        $confirmDisable = Read-Host "Remove this app's stored AI key and start without AI? [y/N]"
        if ($confirmDisable -match '^[YyДд]$') {
            if (Test-Path -LiteralPath $secretPath) {
                Remove-Item -LiteralPath $secretPath -Force
            }
            if (Test-Path -LiteralPath $settingsPath) {
                Remove-Item -LiteralPath $settingsPath -Force
            }
            $skipAiSetup = $true
            Write-LauncherLog "Removed this app's protected AI configuration; starting without AI."
        }
        else {
            Write-LauncherLog "Kept the existing protected AI configuration."
        }
    }

    $uvPath = Get-PinnedUv -ManifestPath (Join-Path $ProjectRoot "scripts\uv-manifest.json") -ToolsDirectory $toolsDirectory
    $env:UV_CACHE_DIR = Join-Path $instanceRoot "uv-cache"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $instanceRoot "python"
    $env:UV_PROJECT_ENVIRONMENT = $venvPath
    $env:UV_NO_PROGRESS = "1"
    Write-LauncherLog "Synchronizing the pinned Python environment from uv.lock."
    & $uvPath sync --locked --no-dev --project $ProjectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "uv could not prepare the pinned environment (exit code $LASTEXITCODE). Check network access and '$script:LogPath'."
    }

    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "uv sync completed but the managed Python executable is missing."
    }

    if ($skipAiSetup -or $SmokeTest) {
        $apiKey = $null
        $script:ConfiguredModel = "gpt-6-luna"
    }
    else {
        $apiKey = Get-ProtectedApiKey `
            -SecretPath $secretPath `
            -SettingsPath $settingsPath `
            -ConfigureAi:$ConfigureAi
    }
    if ($apiKey) {
        $env:OPENAI_API_KEY = $apiKey
    }
    else {
        Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
    }
    $env:OPENAI_MODEL = $script:ConfiguredModel
    $env:CAREERQUEST_DATA_DIR = $instanceRoot
    $env:CAREERQUEST_AI_TIMEOUT = "9"
    if ($apiKey) {
        $env:CAREERQUEST_RECOMMENDER = "app.ai.provider:recommend"
    }
    else {
        Remove-Item Env:CAREERQUEST_RECOMMENDER -ErrorAction SilentlyContinue
    }

    $server = $null
    try {
        $port = Get-FreeLocalPort
        $stdoutPath = Join-Path $logsDirectory "server.stdout.log"
        $stderrPath = Join-Path $logsDirectory "server.stderr.log"
        Write-LauncherLog "Starting local server on 127.0.0.1:$port."
        $server = Start-Process -FilePath $pythonPath `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$port") `
            -WorkingDirectory $ProjectRoot `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath `
            -WindowStyle Hidden `
            -PassThru

        # The child inherited the secret if configured. Clear it before any
        # later launcher action, including browser creation and readiness work.
        $apiKey = $null
        Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

        [ordered]@{
            pid = $server.Id
            port = $port
            python_path = $pythonPath
            started_at = (Get-Date).ToUniversalTime().ToString("o")
        } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

        $deadline = (Get-Date).AddSeconds(30)
        $isReady = $false
        while ((Get-Date) -lt $deadline) {
            if ($server.HasExited) {
                throw "The local server exited before it became ready. Read '$stderrPath'."
            }
            if (Test-Ready -Port $port) {
                $isReady = $true
                break
            }
            Start-Sleep -Milliseconds 250
            $server.Refresh()
        }
        if (-not $isReady) {
            throw "The server did not pass /ready within 30 seconds. Read '$stderrPath'."
        }

        if ($SmokeTest) {
            $null = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/" -TimeoutSec 5
            $null = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/static/app.js" -TimeoutSec 5
            Write-LauncherLog "Launcher check passed: server and UI are ready. AI and browser interaction were not tested."
            exit 0
        }
        Write-LauncherLog "Career Quest is ready; opening the browser."
        Open-CareerQuest -Port $port -DataDirectory $instanceRoot
        Write-Host "Career Quest is running. Keep this window open; press Ctrl+C to stop this instance."
        Wait-Process -Id $server.Id
    }
    finally {
        # The child inherited the secret if configured. Clear it even if the
        # server fails before readiness or the browser cannot be opened.
        $apiKey = $null
        Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
        if ($null -ne $server) {
            try {
                $server.Refresh()
                if (-not $server.HasExited) {
                    Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
                }
            }
            catch {
                # The process may have already exited; do not mask the launch error.
            }
            try {
                if (Test-Path -LiteralPath $statePath) {
                    $recordedState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                    if ($recordedState -and ([int]$recordedState.pid -eq $server.Id)) {
                        Remove-Item -LiteralPath $statePath -Force
                    }
                }
            }
            catch {
                # A stale state file is harmless and is checked on the next launch.
            }
        }
    }
}
catch {
    $message = $_.Exception.Message
    if ($script:LogPath) {
        Write-LauncherLog "ERROR: $message"
        Write-Host ""
        Write-Host "Launcher could not continue: $message" -ForegroundColor Red
        Write-Host "Log: $script:LogPath"
    }
    else {
        Write-Host "Launcher could not continue: $message" -ForegroundColor Red
    }
    exit 1
}
