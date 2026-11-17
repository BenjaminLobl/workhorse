import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_workhorse import FakeOllama

from server import Run, ident, now
from workhorse.appearance_lab import AppearanceLab, validate_css
from workhorse.runtime import Workbench
from workhorse.tools import REGISTRY


class IntelligenceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projects"
        self.root.mkdir()
        self.w = Workbench(Path(self.tmp.name) / "data", FakeOllama())
        self.space = self.w.add_workspace(
            "Projects", str(self.root), {"edit": True, "browser": True}
        )
        self.r = Run(ident(), "t", "actual-test-model")
        self.r.workspace = self.space["id"]
        self.r.mode = "chat"
        self.r.online = False

    def tearDown(self):
        self.w.close()
        self.tmp.cleanup()


class IntelligenceTests(IntelligenceFixture):
    def test_database_connection_commits_and_closes(self):
        with self.w.connect() as connection:
            connection.execute("CREATE TABLE closure_check(value TEXT)")
            connection.execute("INSERT INTO closure_check VALUES ('saved')")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        self.assertEqual(self.w.rows("SELECT value FROM closure_check"), [{"value": "saved"}])

    def test_database_connection_rolls_back_and_closes_on_error(self):
        self.w.write("CREATE TABLE rollback_check(value TEXT)")
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            with self.w.connect() as connection:
                connection.execute("INSERT INTO rollback_check VALUES ('discard')")
                raise RuntimeError("test failure")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        self.assertEqual(self.w.rows("SELECT * FROM rollback_check"), [])

    def test_preferences_survive_compaction_models_and_restart(self):
        self.w.preference_change("style", "Keep updates short.")
        self.w.preference_change("style", "Use a friendly tone.", self.space["id"])
        messages = [
            {
                "role": "system",
                "task": "Hello",
                "workspace": self.space["id"],
                "content": "",
            },
            {"role": "user", "content": "Hello"},
        ]
        self.w.compact(messages, [], 20000)
        self.assertIn("Use a friendly tone.", messages[0]["content"])
        another = Workbench(self.w.data, FakeOllama())
        try:
            self.assertIn("Keep updates short.", another.preference_prompt())
            another.preference_change("style", delete=True)
            self.assertNotIn("Keep updates short.", another.preference_prompt())
        finally:
            another.close()

    def test_preferences_available_in_chat_but_require_approval(self):
        REGISTRY.validate(
            "remember_preference",
            {"key": "style", "value": "Be concise"},
            self.w.groups(self.r),
        )
        with patch.object(self.w, "approval", side_effect=PermissionError("Denied")):
            with self.assertRaises(PermissionError):
                self.w.execute(
                    self.r,
                    "remember_preference",
                    {"key": "style", "value": "Be concise"},
                )
        self.assertEqual(self.w.control_preferences(), {})

    def test_scan_manifests_readme_notes_and_no_completion_claim(self):
        p = self.root / "booking"
        p.mkdir()
        (p / "package.json").write_text(
            json.dumps(
                {
                    "dependencies": {"react": "x", "vite": "x"},
                    "scripts": {"test": "vitest"},
                }
            )
        )
        (p / "README.md").write_text("Room booking\n- [ ] Add calendar tests")
        result = self.w.control_scan_projects(self.space["id"])
        self.assertEqual(len(result["projects"]), 1)
        item = result["projects"][0]
        self.assertIn("react", item["stack"])
        self.assertEqual(item["status"], "Checklist items found")
        self.w.control_action(
            {
                "action": "project_note",
                "workspace": self.space["id"],
                "path": "booking",
                "note": "Check teacher permissions",
            }
        )
        self.assertEqual(
            self.w.control_snapshot()["projects"][0]["note"],
            "Check teacher permissions",
        )

    def test_scan_rejects_unapproved_and_symlink(self):
        with self.assertRaises(ValueError):
            self.w.control_scan_projects("unknown")
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "index.html").write_text("private")
        try:
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink privileges unavailable")
        self.assertEqual(self.w.control_scan_projects(self.space["id"])["projects"], [])

    def test_factual_runtime_model_permissions_and_tools(self):
        facts = self.w.runtime_facts(self.r)
        self.assertEqual(facts["active_model"], "actual-test-model")
        self.assertIsNone(facts["installed_models"])
        self.assertIn("remember_preference", facts["tool_names"])
        self.assertNotIn("run_terminal", facts["tool_names"])
        self.assertEqual(facts["active_workspace"], self.space["id"])

    def test_preserve_style_until_user_applies_theme(self):
        self.assertEqual(self.w.control_theme_css(), "")

    def test_source_stage_rejects_external_and_backend_content(self):
        for css in [
            "body { background: url(https://x); }",
            '@import "x";',
            "#approve { display:none; }",
            "body { color:expression(x); }",
        ]:
            with self.assertRaises(ValueError):
                validate_css(css)
        self.assertIn("#123456", validate_css("body { color: #123456; }"))

    def test_apply_failure_rolls_back_and_stale_proposal_refused(self):
        root = Path(self.tmp.name) / "install"
        (root / "web").mkdir(parents=True)
        target = root / "web" / "workhorse-appearance.css"
        target.write_text("body { color: #123456; }\n")
        lab = AppearanceLab(self.w, root)
        p = lab.stage("New look", "body { color: #234567; }")
        p["status"] = "ready"
        lab.save(p)
        with patch.object(lab, "render", side_effect=ValueError("Health failed")):
            with self.assertRaises(ValueError):
                lab.apply(p["id"])
        self.assertEqual(target.read_text(), "body { color: #123456; }\n")
        self.assertEqual(lab.get(p["id"])["status"], "rolled_back_after_failure")
        q = lab.stage("Next look", "body { color: #345678; }")
        q["status"] = "ready"
        lab.save(q)
        target.write_text("body { color: #456789; }\n")
        with self.assertRaisesRegex(ValueError, "changed since"):
            lab.apply(q["id"])

    def test_css_restart_recovers_interrupted_transaction(self):
        root = Path(self.tmp.name) / "install"
        (root / "web").mkdir(parents=True)
        target = root / "web" / "workhorse-appearance.css"
        target.write_text("body { color: #123456; }\n")
        lab = AppearanceLab(self.w, root)
        p = lab.stage("A proposal", "body { color: #234567; }")
        p["status"] = "applying"
        lab.save(p)
        target.write_text("body { color: #234567; }\n")
        AppearanceLab(self.w, root)
        self.assertEqual(target.read_text(), "body { color: #123456; }\n")


class VisionEvidenceTests(IntelligenceFixture):
    def test_vision_requires_both_sizes_and_invalidates_old_capture(self):
        self.r.mode = "work"
        self.r.design_first = True
        self.r.revision = 1
        self.r.visual_reviews = set()
        self.r.changed = True
        self.r.verified = True
        self.r.finished = None
        shots = self.w.data / "screenshots"
        shots.mkdir(exist_ok=True)
        with (
            patch.object(self.w.ollama, "validate", return_value=["vision"]),
            patch.object(
                self.w.ollama,
                "request",
                create=True,
                return_value={
                    "message": {"content": '{"summary":"Readable layout","critical_issues":[]}'}
                },
            ) as request,
        ):
            for width in [1440, 390]:
                name = ident() + ".png"
                (shots / name).write_bytes(b"test-image")
                self.w.write(
                    "INSERT INTO screenshots VALUES(?,?,?,?)",
                    (name, self.r.workspace, self.r.id, now()),
                )
                self.w.write(
                    "INSERT INTO visual_evidence VALUES(?,?,?,?,?,0)",
                    (name, self.r.id, 1, width, 900),
                )
                out = self.w.execute(
                    self.r,
                    "inspect_screenshot",
                    {"screenshot": name, "question": "Inspect layout"},
                )
                self.assertTrue(out["visual_passed"])
                self.assertTrue(request.call_args.args[1]["messages"][0]["images"])
            self.assertEqual(self.r.visual_reviews, {"desktop", "mobile"})
            self.r.revision = 2
            with self.assertRaisesRegex(ValueError, "predates"):
                self.w.execute(
                    self.r,
                    "inspect_screenshot",
                    {"screenshot": name, "question": "Inspect layout"},
                )

    def test_critical_visual_issues_do_not_pass(self):
        self.r.mode = "work"
        self.r.design_first = True
        self.r.revision = 1
        self.r.visual_reviews = set()
        name = ident() + ".png"
        shots = self.w.data / "screenshots"
        shots.mkdir(exist_ok=True)
        (shots / name).write_bytes(b"test-image")
        self.w.write(
            "INSERT INTO screenshots VALUES(?,?,?,?)",
            (name, self.r.workspace, self.r.id, now()),
        )
        self.w.write(
            "INSERT INTO visual_evidence VALUES(?,?,?,?,?,0)",
            (name, self.r.id, 1, 390, 844),
        )
        with (
            patch.object(self.w.ollama, "validate", return_value=["vision"]),
            patch.object(
                self.w.ollama,
                "request",
                create=True,
                return_value={
                    "message": {
                        "content": '{"summary":"Broken","critical_issues":["Navigation overlaps heading"]}'
                    }
                },
            ),
        ):
            out = self.w.execute(
                self.r, "inspect_screenshot", {"screenshot": name, "question": "Review"}
            )
            self.assertFalse(out["visual_passed"])
            self.assertEqual(self.r.visual_reviews, set())
