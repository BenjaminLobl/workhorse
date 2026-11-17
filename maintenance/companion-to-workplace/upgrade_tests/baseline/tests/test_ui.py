"""Real Chromium smoke test of the preserved UI against the local HTTP API."""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from server import Server
from workhorse.runtime import Workbench
from test_platform import ScriptedOllama


class UITests(unittest.TestCase):
    def test_workspace_chat_tools_permissions_and_responsive_ui(self):
        if not os.environ.get("WORKHORSE_BROWSER_TESTS"):
            self.skipTest("Set WORKHORSE_BROWSER_TESTS=1 after installing Chromium.")
        from playwright.sync_api import sync_playwright, expect

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            app = Workbench(Path(tmp) / "data", ScriptedOllama())
            server = Server(0, app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=True,
                    **(
                        {"executable_path": os.environ["WORKHORSE_CHROMIUM_EXECUTABLE"]}
                        if os.environ.get("WORKHORSE_CHROMIUM_EXECUTABLE")
                        else {}
                    ),
                )
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                try:
                    page.goto(server.origin)
                    page.locator("#settings").click()
                    expect(page.locator("#models")).to_have_value("fixture")
                    page.locator("#use-model").click()
                    page.locator("#add-workspace").click()
                    page.locator("#workspace-name").fill("Design Website")
                    page.locator("#workspace-directory").fill(str(root))
                    page.locator(
                        "#workspace-form button[type=submit],#workspace-form button.primary"
                    ).click()
                    expect(page.locator("#workspace-path")).to_contain_text(str(root))
                    page.locator("#mode").select_option("work")
                    page.locator("#prompt").fill("Create hello.txt")
                    page.locator("#send").click()
                    expect(page.locator("#activity")).to_contain_text(
                        "Blocked", timeout=15000
                    )
                    expect(page.locator("#messages")).to_contain_text(
                        "Created hello.txt"
                    )
                    expect(page.locator("#change-list")).to_contain_text("hello.txt")
                    self.assertEqual((root / "hello.txt").read_text(), "Hello\n")
                    page.locator(".tool-event").first.click()
                    expect(page.locator(".tool-event").first).to_have_attribute(
                        "open", ""
                    )
                    shots = Path(os.environ.get("WORKHORSE_TEST_ARTIFACTS", tmp))
                    shots.mkdir(parents=True, exist_ok=True)
                    for width, height in [(1440, 1000), (768, 1024), (390, 844)]:
                        page.set_viewport_size({"width": width, "height": height})
                        self.assertFalse(
                            page.evaluate(
                                "document.documentElement.scrollWidth>innerWidth"
                            ),
                            f"Overflow at {width}",
                        )
                        page.screenshot(
                            path=str(shots / f"workhorse-{width}.png"), full_page=True
                        )
                    page.on("dialog", lambda d: d.accept())
                    page.locator(".delete-thread").click()
                    expect(page.locator("#threads")).to_be_empty()
                    self.assertTrue((root / "hello.txt").exists())
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
                    server.shutdown()
                    server.server_close()
                    thread.join()
                    app.close()
