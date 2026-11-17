"""Focused tests for model routing and visual proof requirement."""

import tempfile
import unittest
from pathlib import Path

from test_workhorse import FakeOllama

from server import Run, ident, now
from workhorse.runtime import DESIGN_FIRST_PROMPT, Workbench


class DesignFirstTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir()
        self.app = Workbench(Path(self.tmp.name) / "state", FakeOllama())
        self.ws = self.app.add_workspace(
            "Site", str(self.root), {"edit": True, "browser": True}
        )
        self.app.write("INSERT INTO threads VALUES(?,?,?,?)", ("t", "Task", None, now()))
        self.app.bind("t", self.ws["id"])
        self.r = Run(ident(), "t", "qwen3.8:27b")
        self.r.workspace = self.ws["id"]
        self.r.mode = "work"
        self.r.online = False
        self.r.design_first = True
        self.r.changed = False
        self.r.verified = False
        self.r.visual_verified = False
        self.r.finished = None
        self.app.runs[self.r.id] = self.r

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def test_model_routing_and_settings(self):
        self.assertEqual(self.app.select_run_model("old", "chat", True), "old")
        self.assertEqual(self.app.select_run_model("old", "work", True), "qwen3.8:27b")
        self.app.set_settings(
            {
                "coding_model": "qwen3.8:27b",
                "design_model": "gemma4:26b",
                "vision_model": "gemma4:12b",
            }
        )
        self.assertEqual(self.app.select_run_model("old", "work", True), "gemma4:26b")
        self.assertEqual(self.app.select_run_model("old", "work", False), "qwen3.8:27b")
        self.assertEqual(self.app.settings()["vision_model"], "gemma4:12b")
        with self.assertRaises(ValueError):
            self.app.set_settings({"design_model": "gemma4:cloud"})

    def test_visual_proof_gate_after_edits(self):
        self.app.execute(
            self.r,
            "write_file",
            {"path": "index.html", "content": "<h1>Hello</h1>", "reason": "design"},
        )
        self.assertFalse(self.r.visual_verified)
        self.r.verified = True
        done = {
            "status": "success",
            "summary": "Looks good",
            "evidence": ["Build passed"],
        }
        with self.assertRaisesRegex(ValueError, "screenshot reviewed"):
            self.app.execute(self.r, "finish_task", done)
        self.r.visual_verified = True
        self.r.visual_reviews = {"desktop", "mobile"}
        self.assertEqual(self.app.execute(self.r, "finish_task", done)["finished"], "success")
        self.app.execute(
            self.r,
            "write_file",
            {"path": "new.css", "content": "body{}", "reason": "change"},
        )
        self.assertFalse(self.r.visual_verified)
        self.assertFalse(self.r.verified)

    def test_screenshot_requires_active_run(self):
        shot = ident()
        self.app.write(
            "INSERT INTO screenshots VALUES(?,?,?,?)",
            (shot, self.ws["id"], "old-run", now()),
        )
        with self.assertRaisesRegex(ValueError, "active run"):
            self.app.execute(
                self.r,
                "inspect_screenshot",
                {"screenshot": shot, "question": "Review design"},
            )

    def test_design_prompt_survives_compaction(self):
        messages = [
            {"role": "system", "content": "x", "task": "Build a catalogue"},
            {"role": "user", "content": "Build a catalogue"},
        ]
        self.app.compact(messages, [], 20000, True)
        self.assertIn(DESIGN_FIRST_PROMPT, messages[0]["content"])
        self.app.compact(messages, [], 20000, False)
        self.assertNotIn(DESIGN_FIRST_PROMPT, messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
