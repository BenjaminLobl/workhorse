param([string]$InstallRoot)
$ErrorActionPreference = 'Stop'
try {
    $default = if ($InstallRoot) { $InstallRoot } elseif (Test-Path -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) 'server.py')) { Split-Path $PSScriptRoot -Parent } else { Join-Path $env:USERPROFILE 'Desktop\Workhorse_Local_Agent' }
    $root = if ($InstallRoot) { $InstallRoot } else { Read-Host "Installed Workhorse folder [$default]" }
    if ([string]::IsNullOrWhiteSpace($root)) { $root = $default }
    $root = (Resolve-Path -LiteralPath $root.Trim('"')).Path
    if (!(Test-Path -LiteralPath (Join-Path $root 'server.py')) -or !(Test-Path -LiteralPath (Join-Path $root 'Start-Workhorse.ps1'))) { throw 'Choose the existing Workhorse installation folder.' }
    $dest = Join-Path $env:LOCALAPPDATA 'WorkhorseDesktopLauncher'
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    $temporary = Join-Path $dest ('Workhorse-' + [Guid]::NewGuid().ToString('N') + '.exe')
    Add-Type -TypeDefinition (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Workhorse.cs') -Raw) -Language CSharp -OutputAssembly $temporary -OutputType ConsoleApplication
    $exe = Join-Path $dest 'Workhorse.exe'
    Move-Item -LiteralPath $temporary -Destination $exe -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Start-Desktop.ps1') -Destination $dest -Force
    Set-Content -LiteralPath (Join-Path $dest 'installation.txt') -Value $root -Encoding UTF8
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Workhorse.lnk'))
    $link.TargetPath = $exe
    $link.WorkingDirectory = $dest
    $link.Description = 'Start local Workhorse, Docker search services and Ollama'
    $link.Save()
    Write-Host 'Installed. Double-click Workhorse on your desktop to start everything.' -ForegroundColor Green
    Write-Host "Executable: $exe"
} catch {
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
