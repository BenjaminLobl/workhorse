import http.client
import tempfile
import threading
import time
import unittest
from pathlib import Path

from server import Ollama, Server, Workspace


def wait_for(run, status, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if run.status == status:
            return
        if run.status == "error":
            raise AssertionError(run.detail)
        time.sleep(0.01)
    raise AssertionError(f"Expected {status}, got {run.status}: {run.detail}")


class FakeOllama:
    """Protocol fixture, not real model inference."""

    def __init__(self, calls=None):
        self.calls = calls or []
        self.messages = []

    def validate(self, model):
        return ["completion", "tools"]

    def models(self):
        return ["fixture-local"]

    def chat(self, model, messages, agent=True):
        self.messages.append(list(messages))
        if self.calls:
            return self.calls.pop(0)
        return {"message": {"role": "assistant", "content": "The task is complete."}}


def call(name, args):
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": args}}],
        }
    }


class WorkhorseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = Workspace(Path(self.tmp.name), FakeOllama())
        self.w.write("INSERT INTO threads VALUES(?,?,?,?)", ("t1", "Test", None, 1))
        self.w.write("INSERT INTO threads VALUES(?,?,?,?)", ("t2", "Other", None, 2))

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_scope_and_paths(self):
        f = self.w.save("t1", "safe.txt", "private")
        with self.assertRaises(ValueError):
            self.w.file("t2", f["id"])
        for name in ["../outside.txt", "C:\\secret.txt", "dir/file.txt"]:
            with self.assertRaises(ValueError):
                self.w.save("t1", name, "bad")
        with self.assertRaises(ValueError):
            self.w.tool("t1", "shell", {"command": "echo unsafe"})
        with self.assertRaises(ValueError):
            self.w.tool("t1", "create_file", {"name": "x.txt", "content": "x"})

    def test_csv_uses_deterministic_calculation(self):
        f = self.w.save(
            "t1",
            "sales.csv",
            "month,revenue,cost\nJan,4200,1600\nFeb,5100,1900\nMar,4800,1750\n",
        )
        r = self.w.tool("t1", "csv_summary", {"id": f["id"]})
        self.assertEqual(r["rows"], 3)
        self.assertEqual(r["numeric_totals"]["revenue"], 14100)
        self.assertEqual(r["numeric_totals"]["cost"], 5250)

    def test_agent_saves_only_after_exact_approval(self):
        self.w.ollama = FakeOllama(
            [call("create_file", {"name": "report.md", "content": "# Approved report"})]
        )
        r = self.w.start("t1", "Write a report", "fixture-local")
        run = self.w.runs[r["id"]]
        wait_for(run, "approval")
        self.assertEqual(len(self.w.snapshot("t1")["files"]), 0)
        with self.assertRaises(ValueError):
            self.w.decide(run.id, "wrong-id", True)
        self.w.decide(run.id, run.pending["id"], True)
        wait_for(run, "complete")
        self.assertEqual(len(self.w.snapshot("t1")["files"]), 1)
        with self.assertRaises(ValueError):
            self.w.decide(run.id, "old-id", True)
        self.assertEqual(self.w.ollama.messages[-1][-1]["role"], "tool")

    def test_rejected_output_never_saved(self):
        self.w.ollama = FakeOllama(
            [call("create_file", {"name": "report.md", "content": "No"})]
        )
        r = self.w.start("t1", "Write", "fixture-local")
        run = self.w.runs[r["id"]]
        wait_for(run, "approval")
        self.w.decide(run.id, run.pending["id"], False)
        wait_for(run, "complete")
        self.assertEqual(len(self.w.snapshot("t1")["files"]), 0)

    def test_cancel_pending_approval(self):
        self.w.ollama = FakeOllama(
            [call("create_file", {"name": "report.md", "content": "No"})]
        )
        r = self.w.start("t1", "Write", "fixture-local")
        run = self.w.runs[r["id"]]
        wait_for(run, "approval")
        self.w.stop(run.id)
        wait_for(run, "stopped")
        self.assertEqual(len(self.w.snapshot("t1")["files"]), 0)

    def test_restart_retains_data(self):
        self.w.save("t1", "persist.txt", "kept")
        w2 = Workspace(Path(self.tmp.name), FakeOllama())
        self.assertEqual(w2.snapshot("t1")["files"][0]["name"], "persist.txt")

    def test_cloud_detection(self):
        self.assertTrue(Ollama.cloud({"name": "model:cloud"}))
        self.assertTrue(Ollama.cloud({"remote_host": "https://remote.example"}))
        self.assertFalse(Ollama.cloud({"name": "qwen3.5:4b"}))

    def test_http_auth_origin_and_download_safety(self):
        server = Server(0, self.w)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, path, body=None, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", server.server_port)
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            status = r.status
            hs = dict(r.getheaders())
            data = r.read()
            c.close()
            return status, hs, data

        try:
            self.assertEqual(request("GET", "/api/workspace")[0], 403)
            status, headers, body = request("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(b"Workhorse Local", body)
            cookie = headers["Set-Cookie"].split(";")[0]
            self.assertIn("HttpOnly", headers["Set-Cookie"])
            auth = {"Cookie": cookie, "Content-Type": "application/json"}
            self.assertEqual(request("GET", "/api/workspace", headers=auth)[0], 200)
            self.assertEqual(
                request(
                    "POST",
                    "/api/thread",
                    '{"title":"Bad"}',
                    dict(auth, Origin="https://evil.example"),
                )[0],
                403,
            )
            self.assertEqual(request("GET", "/", headers={"Host": "rebind.example"})[0], 403)
            self.assertEqual(request("GET", "/../server.py", headers=auth)[0], 404)
            f = self.w.save("t1", "test.html", "<script>alert(1)</script>")
            st, hs, body = request("GET", "/api/file?thread=t1&id=" + f["id"], headers=auth)
            self.assertEqual(st, 200)
            self.assertIn("text/plain", hs["Content-Type"])
            self.assertIn("attachment", hs["Content-Disposition"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
