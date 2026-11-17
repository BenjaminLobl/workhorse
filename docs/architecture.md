# Following a task through Workhorse

Take the request “fix the greeting on this page.” The model suggests each step; the host decides whether the requested operation is available and records what actually happened.

1. **Accept the task.** The [frontend](../web/app.js) sends the thread, mode, selected model and options. The [HTTP layer](../workhorse/http.py) enforces the loopback session and origin checks. The runtime resolves the thread's workspace and model routing.
2. **Build a bounded conversation.** The [runtime](../workhorse/runtime.py) combines recent messages, project instructions, a task plan and recent tool output. [Workplace guidance](../workhorse/workplace.py) and [saved preferences](../workhorse/intelligence.py) are added again when context is compacted. [Prompts](../workhorse/prompts.py) and [model settings](../workhorse/settings.py) are separate from the [Ollama transport](../workhorse/ollama.py).
3. **Dispatch a tool.** The [registry](../workhorse/tools.py) validates the schema against the active tool groups. The [filesystem adapter](../workhorse/safety.py) checks paths; the [process manager](../workhorse/processes.py) starts approved commands, captures output and reports local server URLs.
4. **Observe the result.** The [browser adapter](../workhorse/browser.py) serializes Playwright actions on a dedicated thread. An assertion or a console error goes back to the model. The [preview panel](../web/workplace.js) can display the latest local capture before the run finishes.
5. **Finish with evidence.** The runtime records calls and edits, and distinguishes successful checks from attempted work. Development runs can fix and retry within a round limit. In Design First mode, tracked changes require current desktop and mobile reviews as well as functional evidence.

## Where data lives

The default local `data/` directory holds the SQLite database and screenshots. The [workspace store](../workhorse/workspace.py) closes each database connection after its transaction, including error paths. Project files remain in the directory the user approved. Neither default runtime data nor generated service secrets belong in Git.

## Other entry points

- [server.py](../server.py): command-line startup and shutdown; the desktop launcher's entry point.
- [Research](../workhorse/research.py): SearXNG query results, page extraction and expiration-aware cache.
- [Control Centre](../workhorse/control_centre.py) and [Appearance Lab](../workhorse/appearance_lab.py): persistent preferences and a staged CSS workflow with preview, approval and rollback.
- [Historical migration](../maintenance/README.md): isolated from the running application because the updater compares original source blocks and payload hashes.
