@echo off
setlocal
cd /d "%~dp0"
set "TARGET=%USERPROFILE%\Desktop\Workhorse_Local_Agent"
set /p "TARGET=Installed Workhorse folder [%TARGET%]: "
if exist "%TARGET%\.venv\Scripts\python.exe" (
  "%TARGET%\.venv\Scripts\python.exe" "%~dp0upgrade.py" rollback --target "%TARGET%"
) else (
  py -3 "%~dp0upgrade.py" rollback --target "%TARGET%"
)
pause
