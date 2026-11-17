@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -File "%~dp0Start-Workhorse.ps1" %*
if errorlevel 1 (
 echo.
 echo Startup failed. Read the error above. If Windows blocks a downloaded script, use Unblock-File on Start-Workhorse.ps1 after reviewing it.
 pause
)
