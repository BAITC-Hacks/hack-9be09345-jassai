@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Resolve this file's directory rather than trusting the current directory.
set "CQ_PROJECT_ROOT=%~dp0"
set "CQ_AI_ARGUMENT="
if /I "%~1"=="/configure-ai" set "CQ_AI_ARGUMENT=-ConfigureAi"
if /I "%~1"=="/disable-ai" set "CQ_AI_ARGUMENT=-DisableAi"
if /I "%~1"=="/check" set "CQ_AI_ARGUMENT=-SmokeTest"

rem Prefer an installed PowerShell 7; otherwise use Windows PowerShell 5.1.
set "CQ_POWERSHELL=powershell.exe"
where pwsh.exe >nul 2>nul
if not errorlevel 1 set "CQ_POWERSHELL=pwsh.exe"
where %CQ_POWERSHELL% >nul 2>nul
if errorlevel 1 (
  echo [Career Quest] Windows PowerShell was not found.
  echo Install or enable the Windows PowerShell component, then run launcher.cmd again.
  if /I not "%~1"=="/check" pause
  exit /b 1
)

rem Do not override PowerShell execution policy here. If a device policy blocks
rem the script, PowerShell will show the policy error and the next safe step.
rem The dot prevents a trailing backslash from escaping the closing argv quote.
%CQ_POWERSHELL% -NoLogo -NoProfile -File "%CQ_PROJECT_ROOT%scripts\launcher.ps1" -ProjectRoot "%CQ_PROJECT_ROOT%." %CQ_AI_ARGUMENT%
set "CQ_EXIT=%ERRORLEVEL%"

if not "%CQ_EXIT%"=="0" (
  echo.
  echo [Career Quest] Launcher stopped with code %CQ_EXIT%.
  echo Read the message above and the launcher log under %%LOCALAPPDATA%%\CareerQuest\instances\hack-9be09345-jassai\logs.
  if /I not "%~1"=="/check" pause
)

endlocal & exit /b %CQ_EXIT%
