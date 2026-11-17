# Running Workhorse

**Fresh Windows checkout:** follow the [four setup steps](../README.md#run-it-on-windows). Use a permanent directory; the shortcut points to it. Setup requires internet access for the first dependency and Chromium downloads. It does not download model weights.

| Component | Default address | When needed |
| --- | --- | --- |
| Workhorse | `127.0.0.1:8765` | The local web interface |
| Ollama | `127.0.0.1:11434` | Inference; choose an installed model |
| SearXNG | `127.0.0.1:8080` | Web search |
| Crawl4AI | `127.0.0.1:11235` | Optional alternative reader |

**Check a startup problem:** run `.\.venv\Scripts\python.exe scripts\doctor.py`. If a model isn't listed, check `ollama list`, open Ollama and retry **Find installed models**. A successful port or health check doesn't establish the quality of a model's answers.

**Choose the right folder:** select a separate project directory in the workspace picker. Enable only the permissions needed for the task. A working style such as Development doesn't turn on file edits or terminal access.

**Stop the app:** press Ctrl+C in its console window. Closing the browser does not stop the server; Docker and Ollama may keep running. The [desktop launcher notes](../launcher/README.txt) cover the optional crawler and removing the shortcut.

**Existing installation:** keep your current installation and its data when trying this source checkout. If you are specifically migrating Companion 0.3.1 to the original Workplace 0.4 distribution, use the [historical updater](../maintenance/README.md). It is not an in-place updater to this refactored checkout.
