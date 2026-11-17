import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from workhorse.browser import Browser


class Page(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b"""<!doctype html><html><head><title>Fixture</title></head><body><h1>Test application</h1><input id="name"><button id="go" onclick="document.querySelector('#result').textContent='Hello '+document.querySelector('#name').value">Greet</button><p id="result"></p><script>console.error('fixture console error')</script></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)


class BrowserTests(unittest.TestCase):
    def test_real_chromium_interaction_screenshot_viewports_console_and_scope(self):
        if not os.environ.get("WORKHORSE_BROWSER_TESTS"):
            self.skipTest("Set WORKHORSE_BROWSER_TESTS=1 after installing Chromium.")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        with tempfile.TemporaryDirectory() as tmp:
            origin = f"http://127.0.0.1:{server.server_port}"
            b = Browser(Path(tmp), lambda w: {origin} if w == "workspace" else set())
            try:
                with self.assertRaises(PermissionError):
                    b.call("workspace", "browser_open", {"url": "http://127.0.0.1:11434"})
                tab = b.call("workspace", "browser_open", {"url": origin})["tab"]
                b.call(
                    "workspace",
                    "browser_type",
                    {"tab": tab, "selector": "#name", "text": "Ben"},
                )
                b.call("workspace", "browser_click", {"tab": tab, "selector": "#go"})
                r = b.call(
                    "workspace",
                    "browser_assert",
                    {
                        "tab": tab,
                        "selector": "#result",
                        "assertion": "text",
                        "text": "Hello Ben",
                    },
                )
                self.assertTrue(r["passed"])
                for width, height in [(1440, 900), (768, 1024), (390, 844)]:
                    dom = b.call(
                        "workspace",
                        "browser_resize",
                        {"tab": tab, "width": width, "height": height},
                    )
                    self.assertFalse(dom["overflow"])
                    shot = b.call("workspace", "browser_screenshot", {"tab": tab})
                    self.assertTrue((Path(tmp) / "screenshots" / shot["screenshot"]).exists())
                self.assertTrue(
                    any(
                        "fixture console error" in e["text"]
                        for e in b.call("workspace", "browser_console", {"tab": tab})["events"]
                    )
                )
                b.call("workspace", "browser_close", {"tab": tab})
                self.assertEqual(b.call("workspace", "browser_tabs", {})["tabs"], [])
            finally:
                b.close()
                server.shutdown()
                server.server_close()
                t.join()
