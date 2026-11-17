$ErrorActionPreference = 'Stop'
try {
    $root = Split-Path $PSScriptRoot -Parent
    Set-Location -LiteralPath $root
    Write-Host 'Workhorse first-time setup. Existing data and model weights are preserved.'
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (!(Test-Path -LiteralPath $python)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
        elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
        else { throw 'Install Python 3.12 or newer, then run Setup.cmd again.' }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    & $python -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'This environment needs Python 3.12+. See README before recreating an existing environment.' }
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network access and retry Setup.cmd.' }
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Browser download failed. Check network access and retry Setup.cmd.' }
    & $python scripts/init_services.py
    if ($LASTEXITCODE -ne 0) { throw 'Local service configuration failed.' }
    & $python scripts/verify_install.py
    if ($LASTEXITCODE -ne 0) { throw 'Workhorse startup check failed. See the error above.' }
    & (Join-Path $root 'launcher\Install-Desktop.ps1') -InstallRoot $root
    Write-Host 'Setup complete. Start Workhorse with the desktop icon or Workhorse.cmd.' -ForegroundColor Green
    Write-Host 'Ollama and Docker Desktop must be installed. In Workhorse, choose Find installed models and select your local model.'
    Write-Host 'If no models are installed, download one with Ollama first. Setup does not download large model weights automatically.'
    Write-Host 'Use Local model settings to choose the coding, design and vision models too.'
} catch {
    Write-Host "Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
