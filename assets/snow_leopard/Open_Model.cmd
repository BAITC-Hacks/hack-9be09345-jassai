@echo off
setlocal
set "BLENDER=%LOCALAPPDATA%\Programs\Blender\blender-5.2.2-windows-x64\blender.exe"
if exist "%BLENDER%" (
    start "" "%BLENDER%" "%~dp0Irbis_SnowLeopard.blend"
    exit /b 0
)
where blender.exe >nul 2>nul
if not errorlevel 1 (
    start "" blender.exe "%~dp0Irbis_SnowLeopard.blend"
    exit /b 0
)
echo Open Irbis_SnowLeopard.blend in Blender 5.2 or newer.
echo Blender was not found in PATH or the portable install folder.
pause
