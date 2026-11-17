import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from test_workhorse import FakeOllama

from server import Server
from workhorse.appearance_lab import AppearanceLab
from workhorse.runtime import Workbench


class ControlBrowserTests(unittest.TestCase):
    def test_preferences_project_search_and_appearance_preview_apply_rollback(self):
        if not os.environ.get("WORKHORSE_BROWSER_TESTS"):
            self.skipTest("Enable browser integration tests.")
        from playwright.sync_api import expect, sync_playwright

        with tempfile.TemporaryDirectory() as tmp:
            app = Workbench(Path(tmp) / "data", FakeOllama())
            project = Path(tmp) / "projects"
            (project / "Booking").mkdir(parents=True)
            (project / "Booking" / "package.json").write_text('{"dependencies":{"react":"x"}}')
            (project / "Booking" / "README.md").write_text(
                "Room booking for teachers. TODO: test permissions."
            )
            ws = app.add_workspace("Development projects", str(project), {})
            app.control_scan_projects(ws["id"])
            installation = Path(tmp) / "installation"
            shutil.copytree(Path(__file__).resolve().parents[1] / "web", installation / "web")
            app.appearance_lab = AppearanceLab(app, installation)
            server = Server(0, app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(
                        headless=True,
                        **(
                            {"executable_path": os.environ["WORKHORSE_CHROMIUM_EXECUTABLE"]}
                            if os.environ.get("WORKHORSE_CHROMIUM_EXECUTABLE")
                            else {}
                        ),
                    )
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 1000})
                        errors = []
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.goto(server.origin)
                        page.get_by_role("button", name="Control Centre", exact=True).click()
                        expect(page.locator(".cc-content")).to_contain_text("Booking")
                        page.get_by_label("Search projects").fill("missing")
                        expect(page.locator(".cc-project")).to_be_hidden()
                        page.get_by_label("Search projects").fill("react")
                        expect(page.locator(".cc-project")).to_be_visible()
                        shots = Path(os.environ.get("WORKHORSE_TEST_ARTIFACTS", tmp))
                        shots.mkdir(exist_ok=True, parents=True)
                        page.screenshot(path=str(shots / "control-projects-desktop.png"))
                        page.get_by_role("button", name="Preferences", exact=True).click()
                        page.locator(".cc-form input").fill("reply_style")
                        page.locator(".cc-form textarea").fill("Use concise natural language.")
                        page.get_by_role("button", name="Save preference").click()
                        expect(page.locator(".cc-content")).to_contain_text(
                            "Use concise natural language."
                        )
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.screenshot(path=str(shots / "control-preferences-mobile.png"))
                        self.assertFalse(
                            page.evaluate("document.documentElement.scrollWidth>innerWidth")
                        )
                        page.get_by_role("button", name="Appearance Lab", exact=True).click()
                        page.locator(".cc-form input").fill("Quiet charcoal")
                        page.locator(".cc-form textarea").fill(
                            "body { background-color: #f3f4f1; } .brand { letter-spacing: -1px; }"
                        )
                        page.get_by_role("button", name="Stage CSS proposal").click()
                        expect(page.locator(".cc-lab-card")).to_contain_text("staged")
                        page.get_by_role("button", name="Run preview checks").click()
                        expect(page.locator(".cc-lab-card")).to_contain_text(
                            "ready", timeout=30000
                        )
                        page.on("dialog", lambda dialog: dialog.accept())
                        page.get_by_role("button", name="Approve and apply").click()
                        expect(page.locator(".cc-lab-card")).to_contain_text(
                            "applied", timeout=30000
                        )
                        page.get_by_role("button", name="Rollback", exact=True).click()
                        expect(page.locator(".cc-lab-card")).to_contain_text("rolled_back")
                        self.assertEqual(errors, [])
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                app.close()
