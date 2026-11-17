# Workhorse Local Agent — 0.2

An upgrade of the existing Workhorse local application, preserving its green interface, projects, conversations, imported files, CSV calculations and approval flow. It adds an Ollama tool loop, approved filesystem workspaces, native commands, local research and browser testing. No paid inference/search API is required.

This is a runnable local foundation, not a claim that a small local model matches ChatGPT on every task. Model weights have not been fine-tuned. The improvements are in tools, permissions, context management and verification.

## Windows quick start

Install **Python 3.12+**, **Ollama**, and **Docker Desktop** (Linux containers). For JavaScript development install Node.js LTS and Git; install PHP/Composer/Python project dependencies only when your projects need them. Workhorse itself runs natively on Windows, outside WSL.

1. Extract the ZIP to a permanent folder, for example `C:\Workhorse`. Do not run from inside the ZIP.
2. Keep Ollama open. If needed, download a model in PowerShell:

   ```powershell
   ollama pull qwen3.5:27b
   ```

   Your already-installed `qwen3.5:9b` is also selectable. The 27B download listed by Ollama is larger than an 11 GB GPU's VRAM, so expect RAM offloading and slower responses on a 2080 Ti. Use 9B if latency or memory is a problem. A model name is configurable; tool/vision capabilities are checked against your local Ollama installation.
3. Start Docker Desktop, then double-click **setup-workhorse.cmd**, or run:

   ```powershell
   .\Start-Workhorse.ps1 -Setup
   ```

4. Workhorse opens at **http://127.0.0.1:8765**. Open **Local model settings**, select an installed model, test it, and save.
5. Create an empty project folder (or choose an existing project), select **Approve workspace**, and enter its full directory path. Choose permissions deliberately. The approved path remains visible above the chat.
6. Select **Development / Work** for coding, **Search** for research, or **Agent** for imported files and general tools. Enable **Internet** for search, and also allow Internet in workspace permissions when a workspace is selected.

Subsequent starts use `start-workhorse.cmd` or `.\Start-Workhorse.ps1`. Setup installs Python dependencies and Chromium only when requested or when creating the virtual environment. It generates a local service secret in `.env`; it does not print or embed a secret in a launcher.

If Windows marks the downloaded script as blocked, review it and use `Unblock-File .\Start-Workhorse.ps1`. If your organisation's execution policy prohibits scripts, follow its policy or use the manual Python commands below; the launcher does not bypass execution policy.

### Manual setup / service controls

From the extracted Workhorse folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe scripts\init_services.py
docker compose up -d
.\.venv\Scripts\python.exe server.py
```

Optional Crawl4AI:

```powershell
docker compose --profile crawl up -d
# Or launch everything with:
.\Start-Workhorse.ps1 -Crawl4AI
```

Offline use without Docker/search:

```powershell
.\Start-Workhorse.ps1 -WithoutSearch
```

Stop Workhorse with Ctrl+C. This stops its managed child processes. Docker services and an independently running Ollama remain running; stop the containers with `docker compose --profile crawl down`. Do not add `-v` unless you intend to remove the search cache volume.

The optional `configure-ollama.cmd` sets user-level loopback/cloud-disable defaults for future Ollama processes. It changes existing values for those settings; review it first, then quit/reopen Ollama if you use it. Workhorse calls Ollama from its backend, so broad `OLLAMA_ORIGINS` access and browser CORS workarounds are unnecessary. Do not connect the hosted website to this privileged runtime.

## First useful test

Create `C:\Projects\WorkhorseGym` yourself, approve it, enable terminal and browser access, and select Development / Work. For a trusted project you may explicitly trust routine install/build/test/dev commands. Otherwise approve each requested command.

> Inspect this workspace. Create a modern responsive gym website using React and Vite. Define completion criteria. Install dependencies, run the development server in the background, test navigation and the enquiry form, inspect desktop and 390x844 mobile layouts, take and inspect screenshots, fix problems, and run the production build. Report the commands, results, changed files and any limitations. Do not commit or deploy.

Node/npm must be installed for this example. Dependency installation needs Internet even when the model runs locally. On Windows, if an npm PowerShell shim is blocked by execution policy, request `npm.cmd`; that custom command will ask for approval.

For research, select Search + Internet and ask for current weather in **Bath, Bristol and Chippenham, Wiltshire, UK**, with sources and retrieval times. The new research path searches and reads pages; it does not use the hosted site's old weather-disambiguation loop or Ollama's hosted Web Search API. Search access does not guarantee a particular website, login-only profile, or search engine will be available.

## Architecture

| Component | Role | Address / storage |
|---|---|---|
| Existing HTML/CSS/JS interface | Chat, workspaces, modes, approvals, activity, diffs, screenshots | `127.0.0.1:8765` |
| Python local server | Session/origin checks, SQLite, structured agent runtime | Same process, loopback only |
| Ollama | Local text/tool inference and optional vision | `127.0.0.1:11434` |
| SearXNG container | Multiple-engine structured web search | `127.0.0.1:8080` |
| Local page reader | Bounded text extraction and redirect validation | Python; no hosted reader API |
| Playwright Chromium | JavaScript reading, local app actions, DOM/assertions/screenshots | Fresh local browser contexts |
| Crawl4AI container, optional | Markdown extraction/rendering | `127.0.0.1:11235` |
| SQLite | Conversations, workspaces, permissions, configuration, runs, tools, diffs and caches | `data/workhorse.sqlite3` |
| Screenshot files | Recorded viewport images, referenced in SQLite | `data/screenshots/` |

The model receives strict JSON-schema tools appropriate to its mode and permissions. The runtime validates arguments, executes one action, records its observation, then asks the model what to do next. It carries the current task, plan and recent evidence, uses file search/sections rather than sending the project wholesale, and trims old tool groups as context grows.

Work mode requires an explicit `finish_task` result. After tracked changes, a successful test/build or browser assertion is required before a success finish is accepted. This is a basic evidence gate, not proof that every user requirement was met. The model is instructed to reproduce, repair and retest; actual capability still depends on its reasoning and tool calling.

### Modes and tools

- **Chat:** ordinary local conversation; no tools. Use Agent to read imported files.
- **Search:** SearXNG + page reading when Internet is enabled; no project/terminal tools. Imported-file tools remain available.
- **Agent:** imported files plus permitted workspace file, command and browser tools.
- **Development / Work:** the same permitted tools, with a required approved workspace and explicit verification/finish protocol.

Filesystem tools list, search, read sections, create, edit, rename and request deletion. Existing-file replacement needs a fresh content hash; exact edits must match once. File tools record diffs and reasons. Foreground approved commands also get bounded before/after source snapshots, excluding secrets, dependencies, binaries and large files. Background processes are tracked with stdout/stderr, IDs, deadlines and detected localhost origins. Their later file changes are not automatically snapshot-tracked; use file tools or request `git status` / `git diff` to review them.

Browser tools open/close/list tabs, inspect DOM, click, fill, scroll, resize, reload, collect console/network failures, assert text/visibility and capture screenshots. The model can request `inspect_screenshot` using the main model or a separate installed vision model from Settings. Password entry, downloads and browser access to the Workhorse/Ollama/research control ports are blocked. Browser sessions use fresh profiles, and are placed offline between runs. Sessions do not survive restart.

`run_tests` executes the project's existing command, so Vitest/Jest/Playwright/Cypress/PHPUnit/framework-native tests are available when installed. Workhorse does not install every testing framework or invent a passing result when tests fail. Git commits, pushes and deployments are not automatic.

### Search and caching

The agent can issue multiple queries, review up to eight deduplicated results with source links and engine names, fetch useful pages, and search again. Raw JSON is hidden under Debug tool data. Pages actually opened are also attached to the final response when their URLs are missing from the model's text; this is provenance, not automatic fact-checking.

Search cache: 5 minutes for current information, 6 hours for reference queries. Page cache: 5 minutes current, 24 hours reference. Freshness profiles have separate keys. SQLite retains at most 500 cache entries and clears expired entries during writes. Search is paced at least one second apart. Engines can still block requests or return no results; no paid fallback is silently enabled.

Default page extraction pins a public IP for each request, rechecks redirects, rejects private/loopback destinations and limits downloads to 2 MB / model excerpts to 18,000 characters. Playwright handles short/JavaScript pages. Optional Crawl4AI uses its local REST service and asks for approval because its container's redirects/subresources are outside Workhorse's request-level network controls. No host project directories are mounted into that container.

### Limits and recovery

Defaults: 24 model rounds, at most 12 requested tools per round, 180-second inference timeout, 120-second foreground command timeout, 1-hour background command deadline, 5-minute approval expiry and bounded browser timeouts. Settings allow 4–40 rounds, 4K–32K context and 512–8192 output tokens. These are local resource limits, not billing quotas.

Incomplete model responses execute no partial tool calls and get one concise retry. Identical failed calls are not repeatedly executed until relevant state changes. Successful browser actions can repeat after reloads. Iteration caps terminate other loops with the recorded blocker. Stop prevents further actions and terminates managed processes; an in-flight inference or browser request may take until its timeout to return. Completed changes are retained, never silently rolled back.

## Permissions and data

Read **SECURITY.md** before approving terminal access. File tools are path-restricted, but native commands are **not an OS sandbox**. Terminal is off by default. By default every command needs approval; the optional trust setting allows a narrow list of routine project commands. Package install/build/test scripts can execute arbitrary code, even when their command name looks harmless. Other commands, pushes, deployments and individual file deletions require approval. Recursive deletion through file tools is blocked.

Local storage is not encrypted by Workhorse. Keep the install/data folder in your user account and use your operating system's disk protection as appropriate. `.env`, common credential files and key files are excluded from file tools; output redaction is best effort, not a guarantee that every possible secret is recognised. Public search queries and visited pages naturally leave your computer. Native commands and package managers have their own network access, independent of the Internet toggle.

Existing local databases are extended additively; no old tables are dropped. Back up `data/` while Workhorse is stopped before upgrading. Replace application files, preserving `data/` and `.env`; rerun setup for new dependencies. Conversation deletion removes messages and imported files, not source files or retained tool/change audit records. For a complete local reset, stop Workhorse and move/delete `data/` yourself. There is no automatic pruning of screenshots or historical audits yet.

The hosted Workhorse site is unchanged by this package. This local edition preserves the local project's UI and imported-file functionality; it does not migrate cloud conversations, replace hosted OpenRouter/OpenAI features, or expose a public remote-control endpoint.

## Diagnostics and tests

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py --search --crawl4ai
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$env:WORKHORSE_BROWSER_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Omit `--crawl4ai` if you did not start the optional service. Omit `--search` for an offline prerequisite check. Browser integration tests require Chromium and Node. Tests use temporary projects and scripted model responses; they do not call a paid service or modify your chosen workspace.

See **TESTING.md** for the release verification record, and **CHANGELOG.md** for files changed. Docker image tags currently follow upstream `latest`; pin validated digests for a reproducible business deployment after testing them on your machine.

## Known next steps

1. Validate the full workflow with your installed Qwen model and native Windows/Docker setup; tune timeout/context settings to actual throughput.
2. Add an opt-in isolated command runner (container/VM with workspace mounts) before allowing unattended work on untrusted projects.
3. Add persistent background change monitoring, richer Git review/rollback, audit retention controls and encrypted storage where required.
4. Add token-aware summaries/streaming cancellation and stronger task-specific completion checks.
5. Measure local visual-review accuracy on representative layouts; a vision-capable model is a capability, not a guarantee of good design judgement.

Upstream references: [Ollama Qwen 3.5](https://ollama.com/library/qwen3.5), [SearXNG search API](https://docs.searxng.org/dev/search_api.html), [SearXNG server settings](https://docs.searxng.org/admin/settings/settings_server.html), [Crawl4AI self-hosting](https://docs.crawl4ai.com/core/self-hosting/), [Playwright Python](https://playwright.dev/python/docs/intro).
