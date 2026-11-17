param([switch]$Setup, [switch]$WithoutSearch, [switch]$Crawl4AI, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
    else { throw 'Install Python 3.12 or newer, then run this launcher again.' }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python virtual environment.' }
    $Setup = $true
}
& $venvPython -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required for Windows junction checks. Recreate .venv with Python 3.12+.' }
if ($Setup) {
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $venvPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed. Check network access and retry -Setup.' }
}
if (!$WithoutSearch) {
    if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install/start Docker Desktop, or use -WithoutSearch for offline work.' }
    & $venvPython scripts/init_services.py
    if ($Crawl4AI) { & docker compose --profile crawl up -d } else { & docker compose up -d }
    if ($LASTEXITCODE -ne 0) { throw 'Docker services failed to start. Check Docker Desktop.' }
}
$env:OLLAMA_HOST='127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD='1'
$ollamaAvailable=$false
try { $null=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3; $ollamaAvailable=$true } catch {}
if (!$ollamaAvailable) {
    if (!(Get-Command ollama -ErrorAction SilentlyContinue)) { throw 'Install Ollama first.' }
    Start-Process ollama -ArgumentList 'serve' -WindowStyle Minimized
    Write-Host 'Started local Ollama. Model loading can take time.'
}
Write-Host 'Workhorse will open at http://127.0.0.1:8765. Ctrl+C stops Workhorse and its managed child processes.'
if ($NoBrowser) { & $venvPython server.py --no-browser } else { & $venvPython server.py }
