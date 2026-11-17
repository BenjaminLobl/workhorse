# Workhorse Workplace 0.4

A local assistant for everyday work: writing, research, management support,
reception/admin tasks and software development. Ollama runs the model; Workhorse
provides permissions, tools, memory, browser actions and the task loop.

## New in 0.4

- Working style selector: General assistant, Management, Development, Reception & admin.
- Natural conversation guidance: answer direct questions directly; ask useful focused questions; avoid unnecessary plans/tool calls for simple drafting or discussion.
- Role-specific conversation starters. Profiles persist locally and change guidance only; they grant no permissions and add no email/calendar/CRM integrations.
- Preview & files panel: local application screenshots appear during browser navigation, reload, resize and click actions. Explicit screenshots also update the panel. Open the interactive app in a separate tab.
- Screenshot captures are observations, not passed tests or vision approval. Existing Design First checks still apply.
- Bundled desktop EXE builder/shortcut installer and Setup.cmd.

Preview is event-driven, not a video stream. It requires an approved workspace,
browser permission, Chromium, and an app the agent has started/opened. Code in a
chat message is not automatically executed. CLI/backend code has logs and tests,
not a visual UI preview. The latest capture is saved per conversation, with a
time and viewport; it may be older than subsequent edits or a stopped server.
Automatic captures are restricted to loopback websites and can be turned off.
Browser screenshots may contain project data and are stored locally like existing
screenshots. No additional vision inference occurs just for a progress capture.

## Download and use on Windows

Prerequisites: Python 3.12+, Ollama with a downloaded local model, and Docker
Desktop for SearXNG search. Install these from their official distributions first.
Docker must be able to run Linux containers. No WSL development shell is needed.

1. Download the ZIP / GitHub source and extract it to a permanent folder.
2. Double-click **Setup.cmd** once. It installs Python requirements and Chromium,
   generates local service configuration, checks startup and creates your desktop shortcut.
3. Start **Workhorse** from the desktop, or double-click **Workhorse.cmd**.
4. Open Local model settings → Find installed models. Select your model and set
   coding/design/vision models to names actually installed on your computer.
5. Pick Working style. Use Chat for conversation, Search for research, and
   Agent/Development modes with a specifically approved workspace for actions.

Initial dependency, browser, container and model downloads need internet and
can take time. This is source distribution, not a zero-dependency bundled app.
Model weights are not included or downloaded without your choice. Existing
configured model names are preserved on upgrade; they are not proof that those
models are installed. A lighter model may be needed for your hardware.

If you want offline use without Docker/search, after setup run:

```bat
start-workhorse.cmd -WithoutSearch
```

The desktop launcher automatically starts Docker, Compose search services and
Ollama when needed, then opens Workhorse at http://127.0.0.1:8765. Keep its console
open/minimized; Ctrl+C stops Workhorse. Docker/Ollama stay running. Optional
Crawl4AI setup is described in launcher/README.txt. No administrator privileges
are requested. Process-only execution-policy flags do not change machine policy.

## Upgrade an existing installation

Use **Apply-Workplace-Upgrade.cmd** from this new release folder, point it at your
existing installation, review the file list and type APPLY. Supported baseline:
Companion 0.3.1 (the Windows SQLite fix). Stop Workhorse first. Extract this release
outside the installed folder. Do not copy the entire source over your old folder.

The updater uses exact source patches, backups and temporary-data health checks.
It preserves the existing base style.css, SQLite data, projects and model config.
It adds one snapshot event hook to app.js and new JS/CSS assets; custom versions
that conflict are refused. Rollback: stop Workhorse and run
Rollback-Workplace-Upgrade.cmd from this release folder. Later edits are protected.
After upgrading, run launcher/Install-Desktop.cmd to refresh the desktop launcher
for that installed folder, then restart and press Ctrl+F5.

## Put it on GitHub

The release folder itself is the repository root: server.py, workhorse/, web/,
launcher/, scripts/, tests/, compose.yaml, requirements.txt and .github/.
The included updater is optional release tooling. Upload this clean source copy,
not your running installation. Review `git status --short` before publishing.
.gitignore excludes local data, .env, backups, venvs, logs and generated launcher
binaries. Do not add model weights, private project files or database snapshots.
Choose a license before inviting redistribution; no license is imposed here.
A Windows/Linux Python CI workflow is included; remote CI has not been run here.
No repository has been created or pushed on your behalf.

## Architecture and boundaries

- server.py: loopback HTTP API, session/origin checks and explicit SQLite closure.
- workhorse/runtime.py: schema-based agent loop, model routing and evidence gates.
- workhorse/workplace.py: response profiles and local progress-preview records.
- web/workplace.js / workplace.css: additive working-style UI and preview panel.
- Existing intelligence/control_centre/appearance_lab retain memory, project
  discovery, runtime facts and approved CSS self-improvement.
- launcher/: local C# EXE compilation, PowerShell orchestration, desktop shortcut.

This is a single-user local application that can assist different job roles;
it is not a shared enterprise service with accounts, tenant isolation or SSO.
It does not send emails, book appointments or update business systems unless
those capabilities are added later. Native terminal approvals are not an OS
sandbox. Model quality and instruction-following require local evaluation.
The existing browser-origin restrictions and Design First gates are retained.

See TEST-RESULTS-WORKPLACE.md for exactly what was tested and what remains unverified.
