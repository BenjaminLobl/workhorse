WORKHORSE DESKTOP LAUNCHER

1. Extract this ZIP.
2. Double-click Install-Desktop.cmd and confirm your Workhorse folder.
3. Double-click the new Workhorse desktop icon whenever you want to use it.

The installer builds a real Workhorse.exe locally using Windows PowerShell's
built-in C# compiler. It creates a desktop shortcut pointing to that executable.
No Visual Studio, additional Python packages or administrator access required.
The existing Workhorse installation and its virtual environment must already
be set up. This package does not install Docker, Ollama or model weights.

Startup opens Docker Desktop when needed, waits for its engine, starts the
existing Docker Compose search service, starts Ollama if needed, and runs
server.py, which opens the website. An already running Workhorse is reused.
A second launch during startup opens the browser; refresh once startup completes.
The launcher targets the existing default ports: Workhorse 8765/Ollama 11434.

Keep the console minimized while working. Ctrl+C in that window stops
Workhorse; Docker and Ollama remain running. Closing the browser alone does
not stop Workhorse. Reused Ollama processes keep their existing configuration.

Optional Crawl4AI: create an empty file named enable-crawl4ai.txt inside
%LOCALAPPDATA%\WorkhorseDesktopLauncher. It enables the existing crawl profile.
The first Compose launch may download images and requires internet access.

The .cmd uses a process-only PowerShell execution-policy override, addressing
the earlier unsigned-script error without changing your machine policy.
Organization-enforced policies may still prevent execution.

To uninstall: stop Workhorse, delete its desktop shortcut and delete
%LOCALAPPDATA%\WorkhorseDesktopLauncher. Your Workhorse app/data stay intact.
Rerun the installer if you move the Workhorse installation. Keep the EXE next
to its supporting files; use its desktop shortcut rather than moving the EXE.

Validation: reviewed against the supplied Start-Workhorse.ps1 and compose.yaml.
Archive integrity checked. Native Windows C# compilation, shortcut creation
and Docker/Ollama startup cannot be executed in the Linux build environment;
they have not been claimed as tested. Installer errors remain visible.
