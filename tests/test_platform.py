import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_workhorse import FakeOllama, wait_for

from server import Run, ident, now
from workhorse.processes import Processes
from workhorse.research import public_target
from workhorse.runtime import Workbench
from workhorse.safety import Files, redact


class PlatformFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir()
        self.w = Workbench(Path(self.tmp.name) / "state", FakeOllama())
        self.ws = self.w.add_workspace(
            "Project",
            str(self.root),
            {"edit": True, "terminal": True, "browser": True, "internet": True},
        )
        self.w.write("INSERT INTO threads VALUES(?,?,?,?)", ("t", "Task", None, now()))
        self.w.bind("t", self.ws["id"])
        self.run = Run(ident(), "t", "fixture")
        self.run.workspace = self.ws["id"]
        self.run.mode = "work"
        self.run.online = True
        self.run.changed = False
        self.run.verified = False
        self.run.plan = []
        self.run.finished = None
        self.w.runs[self.run.id] = self.run

    def tearDown(self):
        self.w.close()
        self.tmp.cleanup()


class PlatformTests(PlatformFixture):
    def test_workspace_paths_secrets_links_and_stale_write(self):
        fs = Files(self.root, lambda r: None)
        for p in [
            "../escape",
            "/etc/passwd",
            "C:/outside",
            "a/../../outside",
            ".env",
            ".env.local",
            ".git/config",
            "folder\\file",
        ]:
            with self.assertRaises((PermissionError, ValueError)):
                fs.path(p)
        target = Path(self.tmp.name) / "secret"
        target.write_text("private")
        (self.root / "link").symlink_to(target)
        with self.assertRaises(PermissionError):
            fs.read("link")
        fs.write("src/app.txt", "before", "Create")
        r = fs.read("src/app.txt")
        with self.assertRaises(ValueError):
            fs.write("src/app.txt", "oops", "Stale", "bad")
        fs.write("src/app.txt", "after", "Edit", r["sha256"])
        self.assertEqual((self.root / "src/app.txt").read_text(), "after")

    def test_schema_and_permission_enforcement(self):
        with self.assertRaises(ValueError):
            self.w.execute(
                self.run,
                "write_file",
                {"path": "a.txt", "content": "a", "reason": "x", "injected": "x"},
            )
        self.run.mode = "search"
        with self.assertRaises(PermissionError):
            self.w.execute(
                self.run, "write_file", {"path": "a.txt", "content": "a", "reason": "x"}
            )
        self.run.online = False
        with self.assertRaises(PermissionError):
            self.w.execute(self.run, "search_web", {"query": "x"})

    def test_diff_and_finish_verification_gate(self):
        self.w.execute(
            self.run,
            "write_file",
            {"path": "test.txt", "content": "Hello\n", "reason": "Requested file"},
        )
        self.assertIn("+Hello", self.w.snapshot("t")["changes"][0]["diff"])
        with self.assertRaises(ValueError):
            self.w.execute(
                self.run,
                "finish_task",
                {"summary": "done", "status": "success", "evidence": []},
            )
        self.w.execute(
            self.run,
            "finish_task",
            {
                "summary": "Tests unavailable",
                "status": "blocked",
                "evidence": ["File saved"],
            },
        )

    def test_dangerous_commands_never_routine(self):
        for c in [
            "git push",
            "git reset --hard",
            "npm run deploy",
            "Remove-Item -Recurse C:\\",
            "npm test; rm -rf /",
            "python evil.py",
            "docker run -v /:/host x",
            "npm test | sh",
        ]:
            self.assertFalse(Processes.routine(c), c)
        self.assertTrue(Processes.routine("npm run build"))
        self.assertTrue(Processes.routine("git status"))

    def test_terminal_requires_exact_approval_and_captures_output(self):
        result = {}
        self.w.write(
            "INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?)",
            (self.run.id, "t", self.ws["id"], "fixture", "running", "", now(), now()),
        )
        command = "printf hello" if os.name != "nt" else "Write-Output hello"

        def do():
            result.update(self.w.execute(self.run, "run_terminal", {"command": command}))

        t = threading.Thread(target=do)
        t.start()
        wait_for(self.run, "approval")
        self.assertFalse(result)
        with self.assertRaises(ValueError):
            self.w.decide(self.run.id, "wrong", True)
        self.w.decide(self.run.id, self.run.pending["id"], True)
        t.join(5)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello", result["stdout"])

    def test_command_timeout_and_redaction(self):
        p = Processes()
        try:
            command = "sleep 5" if os.name != "nt" else "Start-Sleep 5"
            r = p.start("w", self.root, command, timeout=1)
            self.assertEqual(r["reason"], "timeout")
            self.assertIsNotNone(r["exit_code"])
        finally:
            p.close()
        self.assertNotIn("privatevalue", redact("TOKEN=privatevalue"))
        self.assertEqual(redact("hidden foo-secret", ["foo-secret"]), "hidden [REDACTED]")

    def test_search_cache_and_expiry(self):
        with patch(
            "workhorse.research.service",
            return_value={
                "results": [
                    {
                        "title": "Docs",
                        "url": "https://example.com",
                        "content": "Evidence",
                        "engines": ["a", "b"],
                    }
                ]
            },
        ) as f:
            first = self.w.research.search("query")
            second = self.w.research.search("query")
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertEqual(f.call_count, 1)
            self.w.write("UPDATE cache SET expires=0")
            self.assertFalse(self.w.research.search("query")["cached"])
            self.assertEqual(f.call_count, 2)

    def test_page_cache_and_private_network_rejection(self):
        for u in [
            "file:///etc/passwd",
            "http://127.0.0.1",
            "http://169.254.169.254",
            "https://user:pass@example.com",
        ]:
            with self.assertRaises((ValueError, PermissionError)):
                public_target(u)
        with (
            patch("workhorse.research.public_target", return_value=(None, "8.8.8.8")),
            patch(
                "workhorse.research.public_fetch",
                return_value=(
                    "https://example.com",
                    "<h1>Title</h1><script>bad()</script><p>Evidence</p>",
                ),
            ) as f,
        ):
            a = self.w.research.page("https://example.com")
            b = self.w.research.page("https://example.com")
            self.assertIn("Evidence", a["content"])
            self.assertNotIn("bad()", a["content"])
            self.assertTrue(b["cached"])
            self.assertEqual(f.call_count, 1)

    def test_persistent_workspaces_and_run_interrupt(self):
        self.w.write(
            "INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?)",
            ("interrupted", "t", self.ws["id"], "x", "running", "", now(), now()),
        )
        again = Workbench(self.w.data, FakeOllama())
        try:
            self.assertEqual(again.workspace(self.ws["id"])["path"], str(self.root))
            self.assertEqual(
                again.rows("SELECT status FROM agent_runs WHERE id=?", ("interrupted",))[0][
                    "status"
                ],
                "interrupted",
            )
        finally:
            again.close()


class ScriptedOllama:
    def models(self):
        return ["fixture"]

    def validate(self, m):
        return ["tools", "completion"]

    def request(self, path, payload=None, timeout=None):
        if path == "/api/show":
            return {"thinking": {"values": [False, True]}}
        messages = payload["messages"]
        tools = [m for m in messages if m["role"] == "tool"]
        if not tools:
            name, args = (
                "write_file",
                {
                    "path": "hello.txt",
                    "content": "Hello\n",
                    "reason": "Requested deliverable",
                },
            )
        else:
            name, args = (
                "finish_task",
                {
                    "summary": "Created hello.txt. This fixture cannot run a production build.",
                    "status": "blocked",
                    "evidence": ["write_file saved hello.txt"],
                },
            )
        return {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": args}}],
            },
            "done_reason": "stop",
        }


class LoopTests(unittest.TestCase):
    def test_full_agent_write_observe_finish_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            w = Workbench(Path(tmp) / "data", ScriptedOllama())
            try:
                ws = w.add_workspace("Project", str(root), {"edit": True})
                w.write("INSERT INTO threads VALUES(?,?,?,?)", ("t", "Task", None, now()))
                w.bind("t", ws["id"])
                r = w.start("t", "Create hello.txt", "fixture", mode="work")
                run = w.runs[r["id"]]
                wait_for(run, "blocked")
                self.assertEqual((root / "hello.txt").read_text(), "Hello\n")
                self.assertEqual(len(w.rows("SELECT * FROM tool_calls")), 2)
                self.assertEqual(w.snapshot("t")["messages"][-1]["role"], "assistant")
            finally:
                w.close()


class RecoveryTests(PlatformFixture):
    def test_new_current_page_cannot_reuse_reference_cache(self):
        with (
            patch("workhorse.research.public_target", return_value=(None, "8.8.8.8")),
            patch(
                "workhorse.research.public_fetch",
                return_value=("https://example.com", "<p>Evidence</p>"),
            ) as fetch,
        ):
            self.w.research.page("https://example.com", freshness="reference")
            self.w.research.page("https://example.com", freshness="current")
            self.assertEqual(fetch.call_count, 2)

    def test_long_file_context_is_bounded(self):
        (self.root / "long.txt").write_text("a" * 900000)
        out = self.w.execute(self.run, "read_file", {"path": "long.txt"})
        self.assertLessEqual(len(out["content"]), 18000)

    def test_approved_command_records_source_changes(self):
        cmd = (
            "printf revised > source.txt"
            if os.name != "nt"
            else "Set-Content source.txt revised"
        )
        with patch.object(self.w, "approval"):
            result = self.w.execute(self.run, "run_terminal", {"command": cmd})
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("source.txt", result["changed_files"])
        self.assertIn("revised", self.w.snapshot("t")["changes"][0]["diff"])
        self.assertTrue(self.run.changed)

    def test_rejected_delete_preserves_file(self):
        (self.root / "keep.txt").write_text("Keep")
        with patch.object(self.w, "approval", side_effect=PermissionError("Rejected")):
            with self.assertRaises(PermissionError):
                self.w.execute(self.run, "delete_file", {"path": "keep.txt", "reason": "No"})
        self.assertEqual((self.root / "keep.txt").read_text(), "Keep")

    def test_cancel_background_server_and_capture_local_url(self):
        command = (
            'printf "http://localhost:5173\\n"; sleep 8'
            if os.name != "nt"
            else "Write-Output http://localhost:5173; Start-Sleep 8"
        )
        out = self.w.processes.start(
            self.run.workspace,
            self.root,
            command,
            background=True,
            cancel=self.run.cancel,
        )
        self.assertIn("http://127.0.0.1:5173", out["urls"])
        self.run.cancel.set()
        for _ in range(30):
            state = self.w.processes.snapshot(out["id"], self.run.workspace)
            if not state["running"]:
                break
            time.sleep(0.1)
        self.assertFalse(state["running"])
        with self.assertRaises(ValueError):
            self.w.processes.snapshot(out["id"], "another-workspace")


if __name__ == "__main__":
    unittest.main()
