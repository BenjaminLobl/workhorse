$ErrorActionPreference = 'Stop'
$mutex = New-Object Threading.Mutex($false, 'Local\WorkhorseDesktopLauncher')
$owned = $false
function Invoke-Bounded([string]$Exe, [string]$Arguments, [int]$Seconds) {
    $p = Start-Process -FilePath $Exe -ArgumentList $Arguments -PassThru -NoNewWindow
    if (!$p.WaitForExit($Seconds * 1000)) {
        try { $p.Kill() } catch {}
        throw "Timed out: $Exe $Arguments"
    }
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { throw "Command failed (exit $($p.ExitCode)): $Exe $Arguments" }
}
function Ollama-Ready {
    try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; return $true } catch { return $false }
}
try {
    $configuration = Join-Path $PSScriptRoot 'installation.txt'
    $root = if (Test-Path -LiteralPath $configuration) { (Get-Content -LiteralPath $configuration -Raw).Trim() } else { Split-Path $PSScriptRoot -Parent }
    if (!(Test-Path -LiteralPath (Join-Path $root 'server.py'))) { throw 'Workhorse installation moved. Run Install-Desktop.cmd again.' }
    Set-Location -LiteralPath $root
    $url = 'http://127.0.0.1:8765'
    try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
    if (!$owned) { Start-Process $url; Write-Host 'Workhorse is already starting or running.'; exit 0 }
    $running = $false
    try {
        $page = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2
        if ($page.Content -match 'Workhorse') { $running = $true }
        else { throw 'Another application is using port 8765.' }
    } catch {
        if ($_.Exception.Message -eq 'Another application is using port 8765.') { throw }
    }
    if ($running) { Start-Process $url; exit 0 }
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (!(Test-Path -LiteralPath $python)) { throw 'Run Workhorse setup first. Its Python virtual environment is missing.' }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (!$docker) {
        $candidate = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
        if (Test-Path $candidate) { $docker = Get-Item $candidate } else { throw 'Docker Desktop is not installed.' }
    }
    $dockerExe = if ($docker.Source) { $docker.Source } else { $docker.FullName }
    $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (!(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue) -and (Test-Path $desktop)) {
        Write-Host 'Starting Docker Desktop...'
        Start-Process -FilePath $desktop
    }
    Write-Host 'Waiting for Docker (up to 3 minutes)...'
    $ready = $false
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        try { Invoke-Bounded $dockerExe 'info --format {{.ServerVersion}}' 8; $ready = $true; break } catch { Start-Sleep -Seconds 3 }
    }
    if (!$ready) { throw 'Docker did not become ready. Open Docker Desktop, resolve any WSL/startup error and try again.' }
    Invoke-Bounded $python 'scripts/init_services.py' 30
    $compose = 'compose up -d'
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'enable-crawl4ai.txt')) { $compose = 'compose --profile crawl up -d' }
    Invoke-Bounded $dockerExe $compose 600
    $env:OLLAMA_HOST = '127.0.0.1:11434'
    $env:OLLAMA_NO_CLOUD = '1'
    if (!(Ollama-Ready)) {
        $ollama = Get-Command ollama -ErrorAction SilentlyContinue
        $ollamaExe = if ($ollama) { $ollama.Source } else { Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe' }
        if (!(Test-Path -LiteralPath $ollamaExe)) { throw 'Cannot find Ollama. Install it or add it to PATH.' }
        Write-Host 'Starting local Ollama...'
        Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Minimized
        $deadline = (Get-Date).AddSeconds(60)
        while (!(Ollama-Ready)) {
            if ((Get-Date) -ge $deadline) { throw 'Ollama did not respond on port 11434. Check its server window.' }
            Start-Sleep -Seconds 2
        }
    }
    Write-Host 'Starting Workhorse. Its website will open automatically.'
    Write-Host 'Keep this window open or minimized. Press Ctrl+C here to stop Workhorse.'
    Write-Host 'Docker and Ollama remain available after Workhorse stops.'
    & $python server.py
    if ($LASTEXITCODE -ne 0) { throw "Workhorse exited with code $LASTEXITCODE. See the error above." }
} catch {
    Write-Host "Workhorse could not start: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
} finally {
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
