@echo off
setlocal
rem Applies only to the current Windows user's future Ollama processes.
rem Existing Ollama settings for these variables will be replaced.
echo Configuring Ollama for local-only Workhorse testing.
echo Cloud model features will be disabled and Ollama will bind to this computer only.
setx OLLAMA_NO_CLOUD "1"
setx OLLAMA_HOST "127.0.0.1:11434"
setx OLLAMA_ORIGINS "http://127.0.0.1:11434,http://localhost:11434"
echo.
echo Quit Ollama from the system tray, then reopen it from Start.
echo Workhorse talks to Ollama server-side, so broad browser CORS access is not needed.
echo In a new PowerShell window, download a model with:
echo ollama pull qwen3.5:27b
echo.
pause
