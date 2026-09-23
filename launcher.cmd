@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Resolve this file's directory rather than trusting the current directory.
set "CQ_PROJECT_ROOT=%~dp0"
set "CQ_AI_ARGUMENT="
if /I "%~1"=="/configure-ai" set "CQ_AI_ARGUMENT=-ConfigureAi"
if /I "%~1"=="/disable-ai" set "CQ_AI_ARGUMENT=-DisableAi"

where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo [Career Quest] Windows PowerShell was not found.
  echo Install or enable the Windows PowerShell component, then run launcher.cmd again.
  pause
  exit /b 1
)

rem Do not override PowerShell execution policy here. If a device policy blocks
rem the script, PowerShell will show the policy error and the next safe step.
powershell.exe -NoLogo -NoProfile -File "%CQ_PROJECT_ROOT%scripts\launcher.ps1" -ProjectRoot "%CQ_PROJECT_ROOT%" %CQ_AI_ARGUMENT%
set "CQ_EXIT=%ERRORLEVEL%"

if not "%CQ_EXIT%"=="0" (
  echo.
  echo [Career Quest] Launcher stopped with code %CQ_EXIT%.
  echo Read the message above and the launcher log under %%LOCALAPPDATA%%\CareerQuest\instances\hack-9be09345-jassai\logs.
  pause
)

endlocal & exit /b %CQ_EXIT%
