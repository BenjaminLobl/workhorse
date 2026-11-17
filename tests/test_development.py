"""Scripted model, real tools: reproduce a UI failure, edit, reload and retest."""

import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

from server import now
from workhorse.runtime import Workbench


class DevelopmentModel:
    def __init__(self, port):
        self.port = port
        self.step = 0
        self.tab = None

    def validate(self, m):
        return ["tools", "completion"]

    def request(self, path, payload=None, timeout=None):
        if path == "/api/show":
            return {"thinking": {"values": [False]}}
        for m in payload["messages"]:
            if m["role"] == "tool" and m.get("tool_name") == "browser_open":
                self.tab = json.loads(m["content"]).get("tab")
        actions = [
            (
                "write_file",
                {
                    "path": "index.html",
                    "content": '<!doctype html><title>App</title><button id="go">Greet</button><p id="result"></p><script src="app.js"></script>',
                    "reason": "Create fixture",
                },
            ),
            (
                "write_file",
                {
                    "path": "app.js",
                    "content": "document.querySelector('#go').onclick=()=>document.querySelector('#result').textContent='Broken';",
                    "reason": "Reproduce reported bug",
                },
            ),
            (
                "run_terminal",
                {
                    "command": ("& " if os.name == "nt" else "")
                    + '"'
                    + sys.executable
                    + '" -u -m http.server '
                    + str(self.port)
                    + " --bind 127.0.0.1",
                    "background": True,
                    "timeout": 60,
                },
            ),
            ("browser_open", {"url": f"http://127.0.0.1:{self.port}"}),
            ("browser_click", {"tab": self.tab or "pending", "selector": "#go"}),
            (
                "browser_assert",
                {
                    "tab": self.tab or "pending",
                    "selector": "#result",
                    "assertion": "text",
                    "text": "Hello",
                },
            ),
            (
                "edit_file",
                {
                    "path": "app.js",
                    "old_text": "Broken",
                    "new_text": "Hello",
                    "reason": "Correct the failing greeting",
                },
            ),
            ("browser_reload", {"tab": self.tab or "pending"}),
            ("browser_click", {"tab": self.tab or "pending", "selector": "#go"}),
            (
                "browser_assert",
                {
                    "tab": self.tab or "pending",
                    "selector": "#result",
                    "assertion": "text",
                    "text": "Hello",
                },
            ),
            (
                "browser_resize",
                {"tab": self.tab or "pending", "width": 390, "height": 844},
            ),
            ("browser_screenshot", {"tab": self.tab or "pending"}),
            ("run_tests", {"command": "node --check app.js"}),
            (
                "finish_task",
                {
                    "status": "success",
                    "summary": "Fixed greeting and verified the result.",
                    "evidence": [
                        "Browser assertion failed before edit and passed after reload.",
                        "Node syntax check passed.",
                        "Mobile screenshot recorded.",
                    ],
                },
            ),
        ]
        name, args = actions[self.step]
        self.step += 1
        return {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": args}}],
            },
            "done_reason": "stop",
        }


class DevelopmentTests(unittest.TestCase):
    def test_code_run_browser_fail_edit_reload_retest(self):
        if not os.environ.get("WORKHORSE_BROWSER_TESTS"):
            self.skipTest("Requires installed Chromium and Node.")
        import shutil

        if not shutil.which("node"):
            self.skipTest("Node required for syntax check.")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            w = Workbench(Path(tmp) / "data", DevelopmentModel(port))
            try:
                ws = w.add_workspace(
                    "App", str(root), {"edit": True, "terminal": True, "browser": True}
                )
                w.write("INSERT INTO threads VALUES(?,?,?,?)", ("t", "Fix app", None, now()))
                w.bind("t", ws["id"])
                r = w.runs[
                    w.start(
                        "t",
                        "Fix the greeting and test desktop and mobile.",
                        "fixture",
                        mode="work",
                    )["id"]
                ]
                deadline = time.monotonic() + 40
                while r.status in ("running", "approval") and time.monotonic() < deadline:
                    if r.status == "approval" and r.pending:
                        w.decide(r.id, r.pending["id"], True)
                    time.sleep(0.05)
                self.assertEqual(r.status, "complete", r.detail)
                calls = w.rows(
                    "SELECT name,result,status FROM tool_calls ORDER BY created,rowid"
                )
                assertions = [
                    json.loads(c["result"])["passed"]
                    for c in calls
                    if c["name"] == "browser_assert"
                ]
                self.assertEqual(assertions, [False, True])
                self.assertTrue(w.rows("SELECT * FROM screenshots"))
                self.assertIn("Hello", (root / "app.js").read_text())
                terminal = json.loads(
                    next(c["result"] for c in calls if c["name"] == "run_terminal")
                )
                self.assertIn(f"http://127.0.0.1:{port}", terminal["urls"])
            finally:
                w.close()
