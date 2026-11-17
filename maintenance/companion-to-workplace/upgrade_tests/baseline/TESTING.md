# Verification — 8 October 2026

## Executed here

Linux, Python 3.12, Node, jsonschema 4.26.0 and Playwright 1.63.0. The current Chromium download endpoint returned incomplete files in this environment; tests used an installed Chromium 134 headless shell through `WORKHORSE_CHROMIUM_EXECUTABLE`. The shipped Windows setup uses Playwright's normal Chromium installer, without this override.

**26 tests passed**, including all 8 original regression tests. Tests cover:

- Authenticated loopback HTTP, cross-origin rejection and safe downloads.
- Workspace traversal, protected files, symlinks, stale-write hashes and schema validation.
- Exact command approval, rejected deletion, process timeout/cancellation, stdout and detected dev-server URLs.
- Command-generated source diffs and verification-before-success behaviour.
- Search/page cache hits, expiry and freshness separation; local/private URL rejection.
- Persistent conversations/workspaces and interrupted-run state after restart.
- Real Chromium DOM/click/type/assertions, console errors, screenshots and desktop/tablet/mobile viewports.
- Actual Workhorse UI: workspace creation, model selection, scripted agent action, diffs, responsive screenshots and conversation deletion without deleting project source.
- Full development loop with a **scripted model but real tools**: create an app, start its actual local server, reproduce a failing greeting in Chromium, edit JavaScript, reload/click again, observe a passing assertion, capture mobile screenshot and run Node's syntax check.

The development-loop test specifically verifies that repeated browser clicks really execute after source edits; previous successful tool results must not suppress necessary retesting. UI testing also caught and fixed conversation controls remaining disabled after a run.

`node --check web/app.js` passes. Python source is Black-formatted. Compose and SearXNG YAML are syntax-checked. Desktop and mobile UI screenshots were visually reviewed.

## Not verified here

- Real Qwen/Gemma/GLM inference, actual visual reasoning accuracy or performance on an RTX 2080 Ti. No access to the owner's Ollama server or PC was available.
- Native Windows PowerShell, Windows junction handling or Docker Desktop execution. Their code paths/configurations are supplied but must be checked on Windows.
- Live SearXNG engine availability or live Crawl4AI container behaviour. Adapter tests use controlled responses; Docker is unavailable here.
- A real npm dependency installation/React production build driven autonomously by a local model. The end-to-end fixture proves the tool/observation/correction plumbing, not general model coding capability.

## Reproduce on Windows

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py --search
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$env:WORKHORSE_BROWSER_TESTS='1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The first test command skips three browser/development integration tests unless the environment flag is present. Tests operate in temporary folders. Node and Chromium are required for the full suite. Symlink tests may require Windows Developer Mode or an account with symlink privileges; a missing OS privilege is not evidence that the runtime allows links. Do not disable Windows security policy solely to make a test pass.

Run the README's gym-site task in a disposable approved workspace with your installed local model, review each command, then enable routine-script trust only if appropriate. For research, check citations and retrieval times against the actual pages. For vision, compare the model's report to the screenshot yourself before relying on it unattended.
