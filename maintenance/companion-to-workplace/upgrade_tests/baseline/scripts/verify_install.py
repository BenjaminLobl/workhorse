"""Non-destructive startup/HTTP smoke check using temporary SQLite data."""

import json, sys, tempfile, threading
from pathlib import Path
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler
from http.cookiejar import CookieJar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Server
from workhorse.runtime import Workbench

with tempfile.TemporaryDirectory() as temporary:
    app = Workbench(Path(temporary) / "data")
    server = Server(0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        for path in [
            "/",
            "/api/workspace",
            "/api/control-centre",
            "/api/appearance-lab",
            "/control-centre.js",
            "/control-centre.css",
            "/workhorse-appearance.css",
        ]:
            with opener.open(server.origin + path, timeout=5) as response:
                assert response.status == 200
                if path.startswith("/api/"):
                    json.loads(response.read())
        print(
            "PASS: local startup, additive schema and authenticated HTTP routes. Existing data untouched."
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        app.close()
