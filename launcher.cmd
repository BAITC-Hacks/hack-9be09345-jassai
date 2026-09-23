@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "CQ_PROJECT_ROOT=%~dp0"
set "CQ_MODE=%~1"
if /I "%CQ_MODE%"=="/help" goto help
if /I "%CQ_MODE%"=="/?" goto help
if "%CQ_MODE%"=="" goto bootstrap
if /I "%CQ_MODE%"=="/check" goto bootstrap
if /I "%CQ_MODE%"=="/configure-ai" goto bootstrap
if /I "%CQ_MODE%"=="/disable-ai" goto bootstrap
echo [Career Quest] Unknown option. Use launcher.cmd /help.
exit /b 2

:help
echo Career Quest - Windows 10/11 x64
echo   launcher.cmd                Prepare and open the local application.
echo   launcher.cmd /configure-ai  Configure or replace the protected OpenAI key.
echo   launcher.cmd /disable-ai    Remove the saved AI key after confirmation.
echo   launcher.cmd /check         Prepare, start, check and stop; no AI or browser.
echo   launcher.cmd /help          Show this help without downloads or changes.
echo First launch needs internet to download pinned uv, Python and dependencies.
echo Python, Node.js, Docker and PowerShell 7 do not need to be installed manually.
echo Keep the launcher window open. Ctrl+C stops its local server.
echo Data is preserved under %%LOCALAPPDATA%%\CareerQuest\instances\hack-9be09345-jassai.
exit /b 0

:bootstrap
rem Use built-in commands only: no PS1 execution, policy changes or encoded scripts.
rem Paths travel through environment variables, not interpolated PowerShell code.
set "OPENAI_API_KEY="
set "NVIDIA_API_KEY="
set "OPENAI_COMPANION_MODEL="
set "NVIDIA_COMPANION_MODEL="
set "CAREERQUEST_COMPANION_PROVIDER="
set "CQ_INSTANCE_ROOT=%CAREERQUEST_DATA_DIR%"
if not defined CQ_INSTANCE_ROOT if not defined LOCALAPPDATA goto no_data_directory
if not defined CQ_INSTANCE_ROOT set "CQ_INSTANCE_ROOT=%LOCALAPPDATA%\CareerQuest\instances\hack-9be09345-jassai"
set "CQ_UV_PATH=%CQ_INSTANCE_ROOT%\tools\uv.exe"
set "UV_CACHE_DIR=%CQ_INSTANCE_ROOT%\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%CQ_INSTANCE_ROOT%\python"
set "UV_NO_PROGRESS=1"
set "CQ_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%CQ_POWERSHELL%" goto no_powershell
rem Use built-in modules, including when started from a PowerShell 7 developer shell.
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"
echo [Career Quest] Checking the pinned runtime. First launch requires internet.
"%CQ_POWERSHELL%" -NoLogo -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; try { if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }; $m=Get-Content -LiteralPath (Join-Path $env:CQ_PROJECT_ROOT 'scripts\uv-manifest.json') -Raw | ConvertFrom-Json; if ($m.version -notmatch '^\d+\.\d+\.\d+$' -or $m.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $m.url -ne ('https://github.com/astral-sh/uv/releases/download/'+$m.version+'/uv-x86_64-pc-windows-msvc.zip')) { throw 'Invalid pinned uv manifest.' }; $dir=Split-Path -Parent $env:CQ_UV_PATH; New-Item -ItemType Directory -Path $dir -Force | Out-Null; $zip=Join-Path $dir ('uv-'+$m.version+'.zip'); if (-not (Test-Path -LiteralPath $zip)) { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri $m.url -OutFile ($zip+'.download') -TimeoutSec 60; if ((Get-FileHash -LiteralPath ($zip+'.download') -Algorithm SHA256).Hash -ine $m.sha256) { throw 'Downloaded uv SHA-256 mismatch; no executable was started.' }; Move-Item -LiteralPath ($zip+'.download') -Destination $zip -Force }; if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ine $m.sha256) { throw 'Cached uv SHA-256 mismatch. Remove the cached ZIP and retry.' }; Add-Type -AssemblyName System.IO.Compression.FileSystem; $archive=[IO.Compression.ZipFile]::OpenRead($zip); try { $entry=$archive.GetEntry('uv.exe'); if (-not $entry) { throw 'uv.exe is missing from the verified archive.' }; $stream=$entry.Open(); $sha=[Security.Cryptography.SHA256]::Create(); try { $expected=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','') } finally { $stream.Dispose(); $sha.Dispose() }; if (-not (Test-Path -LiteralPath $env:CQ_UV_PATH) -or (Get-FileHash -LiteralPath $env:CQ_UV_PATH -Algorithm SHA256).Hash -ne $expected) { [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,($env:CQ_UV_PATH+'.new'),$true); Move-Item -LiteralPath ($env:CQ_UV_PATH+'.new') -Destination $env:CQ_UV_PATH -Force } } finally { $archive.Dispose() } } catch { Write-Host ('[Career Quest] Runtime preparation failed: '+$_.Exception.Message); Write-Host 'Check internet access to GitHub and write access to the data folder, then retry.'; exit 1 }"
if errorlevel 1 goto failed
set "CQ_PYTHON_VERSION="
set /p CQ_PYTHON_VERSION=<"%CQ_PROJECT_ROOT%.python-version"
if not defined CQ_PYTHON_VERSION goto incomplete_zip
rem --no-project prevents a repository .venv and dependency resolution before sync.
"%CQ_UV_PATH%" run --no-project --managed-python --python "%CQ_PYTHON_VERSION%" "%CQ_PROJECT_ROOT%scripts\launcher.py" "%CQ_MODE%"
set "CQ_EXIT=%ERRORLEVEL%"
if not "%CQ_EXIT%"=="0" goto failed_code
exit /b 0

:no_powershell
echo [Career Quest] Built-in Windows PowerShell is unavailable. Contact the device administrator.
goto failed
:no_data_directory
echo [Career Quest] LOCALAPPDATA is unavailable. Set CAREERQUEST_DATA_DIR to a writable folder.
goto failed
:incomplete_zip
echo [Career Quest] Python version file is missing. Extract the complete ZIP and retry.
:failed
set "CQ_EXIT=1"
:failed_code
echo [Career Quest] Launch stopped. See the message above and the README troubleshooting steps.
if /I not "%CQ_MODE%"=="/check" pause
exit /b %CQ_EXIT%
