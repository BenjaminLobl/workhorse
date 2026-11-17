import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_workhorse import FakeOllama

from server import Run, Server, ident, now
from workhorse.runtime import Workbench


class WorkplaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = Workbench(Path(self.tmp.name) / "data", FakeOllama())
        project = Path(self.tmp.name) / "project"
        project.mkdir()
        self.ws = self.w.add_workspace("Project", str(project), {"browser": True})
        self.r = Run(ident(), "t", "fixture")
        self.r.workspace = self.ws["id"]
        self.r.online = False
        self.w.write("INSERT INTO threads VALUES(?,?,?,?)", ("t", "Preview test", None, now()))
        self.w.bind("t", self.ws["id"])

    def tearDown(self):
        self.w.close()
        self.tmp.cleanup()

    def test_profile_validation_persistence_and_permissions(self):
        before = self.w.workspace(self.ws["id"])["permissions"]
        self.w.set_settings({"work_profile": "reception", "progress_preview": False})
        with self.assertRaises(ValueError):
            self.w.set_settings({"work_profile": "administrator"})
        with self.assertRaises(ValueError):
            self.w.set_settings({"progress_preview": "yes"})
        self.assertEqual(before, self.w.workspace(self.ws["id"])["permissions"])
        second = Workbench(self.w.data, FakeOllama())
        try:
            self.assertEqual(second.settings()["work_profile"], "reception")
        finally:
            second.close()

    def test_conversation_survives_compaction(self):
        self.w.set_settings({"work_profile": "manager"})
        messages = [
            {"role": "system", "content": "", "task": "Help me plan"},
            {"role": "user", "content": "Help me plan"},
        ]
        self.w.compact(messages, [], 20000)
        self.assertIn("Management support", messages[0]["content"])
        self.assertIn("do not force a coding plan", messages[0]["content"])

    def test_preview_thread_scope_and_query_redaction(self):
        self.w.remember_preview(
            self.r,
            {
                "screenshot": "a.png",
                "url": "http://127.0.0.1:5173/?token=private#secret",
                "viewport": {"width": 390, "height": 844},
            },
        )
        self.assertEqual(
            self.w.snapshot("t")["progress_preview"]["url"], "http://127.0.0.1:5173/"
        )
        self.assertIsNone(self.w.progress_preview("other"))
        self.assertIsNone(self.w.snapshot()["progress_preview"])

    def test_external_pages_not_captured(self):
        with patch.object(self.w.browser, "call") as call:
            self.w.capture_progress(
                self.r, "browser_open", {}, {"tab": "x", "url": "https://example.com"}
            )
            call.assert_not_called()

    def test_auto_capture_not_visual_verification(self):
        with patch.object(
            self.w.browser,
            "call",
            return_value={
                "screenshot": "a.png",
                "url": "http://127.0.0.1:5173/",
                "viewport": {"width": 1440, "height": 900},
            },
        ):
            out = self.w.capture_progress(
                self.r, "browser_open", {}, {"tab": "x", "url": "http://127.0.0.1:5173/"}
            )
        self.assertEqual(out["preview"], "a.png")
        self.assertEqual(self.w.rows("SELECT reviewed FROM visual_evidence")[0]["reviewed"], 0)

    def test_capture_failure_preserves_action(self):
        with patch.object(self.w.browser, "call", side_effect=RuntimeError("capture failed")):
            out = self.w.capture_progress(
                self.r,
                "browser_click",
                {"tab": "x"},
                {"tab": "x", "url": "http://localhost:5173/"},
            )
        self.assertIn("preview_warning", out)
        self.assertEqual(out["tab"], "x")

    def test_disabled_preview_not_captured(self):
        self.w.set_settings({"progress_preview": False})
        with patch.object(self.w.browser, "call") as call:
            self.w.capture_progress(
                self.r, "browser_open", {}, {"tab": "x", "url": "http://localhost:5173/"}
            )
            call.assert_not_called()


class WorkplaceBrowserTests(unittest.TestCase):
    def test_profile_starters_and_preview_mobile(self):
        if not os.environ.get("WORKHORSE_BROWSER_TESTS"):
            self.skipTest("Enable Chromium tests")
        from playwright.sync_api import expect, sync_playwright

        with tempfile.TemporaryDirectory() as tmp:
            w = Workbench(Path(tmp) / "data", FakeOllama())
            server = Server(0, w)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as pw:
                    kwargs = (
                        {"executable_path": os.environ["WORKHORSE_CHROMIUM_EXECUTABLE"]}
                        if os.environ.get("WORKHORSE_CHROMIUM_EXECUTABLE")
                        else {}
                    )
                    browser = pw.chromium.launch(headless=True, **kwargs)
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 1000})
                        errors = []
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.goto(server.origin)
                        page.get_by_label("Working style", exact=True).select_option(
                            "reception"
                        )
                        expect(
                            page.get_by_text("Working style saved for future replies.")
                        ).to_be_visible()
                        page.reload()
                        expect(
                            page.get_by_role("button", name="Prepare a handover")
                        ).to_be_visible()
                        page.get_by_role("button", name="Prepare a handover").click()
                        expect(page.locator("#prompt")).to_have_value(
                            "Turn the notes I provide into a clear reception handover, marking anything awaiting confirmation."
                        )
                        shots = w.data / "screenshots"
                        shots.mkdir(exist_ok=True)
                        page.screenshot(path=str(shots / "fixture.png"))
                        w.write(
                            "INSERT INTO screenshots VALUES(?,?,?,?)",
                            ("fixture.png", "ws", "run", now()),
                        )
                        page.evaluate(
                            """() => window.dispatchEvent(new CustomEvent('workhorse:snapshot',{detail:{config:{work_profile:'reception',progress_preview:true},run:{id:'run'},progress_preview:{screenshot:'fixture.png',url:'http://127.0.0.1:5173/',captured:Date.now(),viewport:{width:1440,height:1000}}}}))"""
                        )
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.locator("#panel-toggle").click()
                        expect(page.locator("#progress-preview img")).to_be_visible()
                        page.get_by_role("button", name="Expand capture").click()
                        expect(page.locator(".preview-dialog img")).to_be_visible()
                        page.get_by_role("button", name="Close preview").click()
                        expect(
                            page.get_by_role("link", name="Open interactive app")
                        ).to_have_attribute("href", "http://127.0.0.1:5173/")
                        self.assertTrue(
                            page.locator("#progress-preview img").evaluate(
                                "(img)=>img.complete && img.naturalWidth>0"
                            )
                        )
                        self.assertFalse(
                            page.evaluate("document.documentElement.scrollWidth>innerWidth")
                        )
                        self.assertEqual(errors, [])
                        artifacts = os.environ.get("WORKHORSE_TEST_ARTIFACTS")
                        if artifacts:
                            Path(artifacts).mkdir(parents=True, exist_ok=True)
                            page.screenshot(
                                path=str(Path(artifacts) / "workplace-mobile.png"),
                                full_page=True,
                            )
                            page.set_viewport_size({"width": 1440, "height": 1000})
                            page.screenshot(path=str(Path(artifacts) / "workplace-desktop.png"))
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                w.close()
