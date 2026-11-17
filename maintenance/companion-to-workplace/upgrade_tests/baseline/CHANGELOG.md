# 0.2 — Local work agent foundation

## Preserved

Existing Workhorse local interface and visual style; projects, project instructions, chats, text imports, deterministic CSV summaries, approved downloadable outputs, Ollama local/cloud checks, session/origin checks and SQLite data. Existing tables are extended additively. No hosted site deployment or model-weight training is included.

## Modified files

- `server.py`: integrate Workbench, workspace/configuration/conversation-delete routes, screenshots, health checks and orderly shutdown. Original import/chat compatibility path retained.
- `web/index.html`, `web/app.js`, `web/style.css`: modes, approved path, workspaces/permissions, local model budgets/vision model, activity/diffs/screenshots/source links, conversation deletion, responsive access to files/changes.
- `README.md`, `start-workhorse.cmd`, `start-workhorse.sh`, `configure-ollama.cmd`: local-agent setup and migration instructions.
- Existing `tests/test_workhorse.py`: formatting; original regression coverage retained.

## Added files

- `workhorse/runtime.py`: persistent agent runs, permission profiles, approval dispatch, iterative model loop, context excerpts, completion evidence, source provenance and recovery.
- `workhorse/tools.py`: modular strict JSON-schema tool registry.
- `workhorse/safety.py`: scoped files, conflict-safe writes, exact edits, redaction and diffs.
- `workhorse/processes.py`: native PowerShell/bash, approvals/trust classification, bounded output, process trees, deadlines and localhost detection.
- `workhorse/changes.py`: bounded source snapshots around foreground command execution.
- `workhorse/research.py`: SearXNG, TTL caches, protected public page retrieval, extraction and optional renderer integrations.
- `workhorse/browser.py`: Playwright thread, isolated contexts, browser actions, network checks, screenshots and idle suspension.
- `requirements.txt`, `.gitignore`, `compose.yaml`, `services/searxng/settings.yml`.
- `Start-Workhorse.ps1`, `setup-workhorse.cmd`, `scripts/init_services.py`, `scripts/doctor.py`.
- `tests/test_platform.py`, `tests/test_browser.py`, `tests/test_ui.py`, `tests/test_development.py`.
- `SECURITY.md`, `TESTING.md`.

## Deliberate limits

No OS command sandbox, no unlimited research guarantee, no model fine-tuning, no persistent browser/process resurrection, no automated Git rollback, no live verification on the owner's Windows PC. SearXNG/Crawl4AI and local model quality need the included machine-side checks. Background command file changes after launch require explicit review; foreground snapshots are bounded and disclose truncation.
