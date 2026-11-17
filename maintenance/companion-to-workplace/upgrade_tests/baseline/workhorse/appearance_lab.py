"""Experimental CSS-only source proposals. No backend or JavaScript self-editing.

Validation, isolated browser preview, explicit UI approval, conflict checking,
atomic replacement, post-apply browser checks and automatic rollback.
"""

from __future__ import annotations
import difflib, hashlib, json, os, re, tempfile, threading, uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SELECTORS = {
    ":root",
    "body",
    "main",
    "aside",
    "header",
    "#composer",
    "#prompt",
    ".suggestions button",
    ".message",
    ".message.user",
    ".model-badge",
    ".file-panel",
    ".brand",
    "h1",
    "h1 span",
    ".primary",
    ".secondary",
}
PROPERTIES = {
    "color",
    "background-color",
    "border-color",
    "border-radius",
    "font-family",
    "font-size",
    "line-height",
    "letter-spacing",
    "padding",
    "gap",
    "max-width",
    "box-shadow",
    "--green",
    "--soft",
    "--muted",
    "--line",
}


def validate_css(css):
    if not isinstance(css, str) or not 1 <= len(css) <= 12000:
        raise ValueError("CSS must be 1–12000 characters.")
    if any(
        x in css.lower()
        for x in ("url", "@", "\\", "<", ">", "!important", "expression", "/*")
    ):
        raise ValueError(
            "External assets, at-rules, escapes and executable content are not permitted."
        )
    rules = list(re.finditer(r"([^{}]+)\{([^{}]*)\}", css))
    if not rules or re.sub(r"([^{}]+)\{([^{}]*)\}", "", css).strip():
        raise ValueError("Use simple CSS selector blocks.")
    for rule in rules:
        if any(s.strip() not in SELECTORS for s in rule[1].split(",")):
            raise ValueError("Selector outside the permitted appearance surface.")
        for declaration in rule[2].split(";"):
            if not declaration.strip():
                continue
            if ":" not in declaration:
                raise ValueError("Invalid CSS declaration.")
            key, value = map(str.strip, declaration.split(":", 1))
            if key not in PROPERTIES or not re.fullmatch(
                r"[A-Za-z0-9#.,%()'\" +\-]+", value
            ):
                raise ValueError("Unsupported appearance property or value.")
            if key in ("font-size", "line-height") and value.strip() == "0":
                raise ValueError("Text must remain visible.")
    return css.strip() + "\n"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".workhorse-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class AppearanceLab:
    def __init__(self, store, root):
        self.store = store
        self.root = Path(root)
        self.directory = store.data / "appearance-lab"
        self.directory.mkdir(exist_ok=True)
        self.lock = threading.Lock()
        with store.connect() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS self_proposals(id TEXT PRIMARY KEY,detail TEXT NOT NULL)"
            )
        # Recover a process interrupted during the one-file source transaction.
        for row in self.list():
            if row["status"] == "applying":
                self._restore(row, "rolled_back_after_restart")

    @property
    def target(self):
        p = self.root / "web" / "workhorse-appearance.css"
        if p.is_symlink() or (p.exists() and p.stat().st_nlink > 1):
            raise PermissionError("Appearance target is a link.")
        return p

    def list(self):
        return [
            json.loads(r["detail"])
            for r in self.store.rows(
                "SELECT detail FROM self_proposals ORDER BY rowid DESC LIMIT 30"
            )
        ]

    def get(self, id):
        rows = self.store.rows("SELECT detail FROM self_proposals WHERE id=?", (id,))
        if not rows:
            raise ValueError("Appearance proposal not found.")
        return json.loads(rows[0]["detail"])

    def save(self, row):
        self.store.write(
            "INSERT OR REPLACE INTO self_proposals VALUES(?,?)",
            (row["id"], json.dumps(row)),
        )

    def stage(self, title, css):
        if not isinstance(title, str) or not 3 <= len(title) <= 100:
            raise ValueError("Use a 3–100 character title.")
        css = validate_css(css)
        before = self.target.read_bytes() if self.target.exists() else b""
        id = uuid.uuid4().hex
        directory = self.directory / id
        directory.mkdir()
        atomic(directory / "before.css", before)
        atomic(directory / "proposal.css", css.encode())
        row = {
            "id": id,
            "title": title,
            "status": "staged",
            "path": "web/workhorse-appearance.css",
            "before_hash": digest(before),
            "after_hash": digest(css.encode()),
            "diff": "".join(
                difflib.unified_diff(
                    before.decode().splitlines(True),
                    css.splitlines(True),
                    fromfile="current appearance",
                    tofile="proposed appearance",
                )
            ),
            "checks": [],
            "screenshots": [],
        }
        self.save(row)
        return row

    def preview(self, id):
        with self.lock:
            row = self.get(id)
            if row["status"] not in ("staged", "ready", "failed"):
                raise ValueError("Proposal is not previewable.")
            try:
                row.update(self.render(id))
                row.pop("error", None)
                row["status"] = "ready"
            except Exception as e:
                row["status"] = "failed"
                row["error"] = str(e)[:500]
            self.save(row)
            return row

    def render(self, id):
        """Copy only frontend assets into an ephemeral static, mocked-data preview."""
        from playwright.sync_api import sync_playwright

        proposal = self.directory / id
        with tempfile.TemporaryDirectory(prefix="workhorse-preview-") as temp:
            staging = Path(temp)
            for path in (self.root / "web").iterdir():
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and path.suffix in (".js", ".css", ".html", ".svg")
                    and path.stat().st_size < 1_000_000
                ):
                    (staging / path.name).write_bytes(path.read_bytes())
            (staging / "workhorse-appearance.css").write_bytes(
                (proposal / "proposal.css").read_bytes()
            )
            html = (staging / "index.html").read_text()
            if "/workhorse-appearance.css" not in html:
                html = html.replace(
                    "</head>",
                    '<link rel="stylesheet" href="/workhorse-appearance.css"></head>',
                )
            (staging / "index.html").write_text(html)

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *a):
                    pass

                def do_GET(self):
                    name = self.path.split("?", 1)[0]
                    if name.startswith("/api/"):
                        if "workspace" in name:
                            body = json.dumps(
                                {
                                    "projects": [],
                                    "threads": [],
                                    "workspaces": [],
                                    "config": {"model": "Preview — no model connected"},
                                }
                            ).encode()
                            kind = "application/json"
                        elif "control-theme.css" in name:
                            body = b""
                            kind = "text/css"
                        else:
                            body = b"{}"
                            kind = "application/json"
                    else:
                        name = "index.html" if name == "/" else name.lstrip("/")
                        if "/" in name or name not in {
                            p.name for p in staging.iterdir()
                        }:
                            self.send_error(404)
                            return
                        import mimetypes

                        body = (staging / name).read_bytes()
                        kind = mimetypes.guess_type(name)[0] or "text/plain"
                    self.send_response(200)
                    self.send_header("Content-Type", kind)
                    self.send_header(
                        "Content-Security-Policy",
                        "default-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'",
                    )
                    self.end_headers()
                    self.wfile.write(body)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            origin = f"http://127.0.0.1:{server.server_port}"
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(
                        headless=True,
                        **(
                            {
                                "executable_path": os.environ[
                                    "WORKHORSE_CHROMIUM_EXECUTABLE"
                                ]
                            }
                            if os.environ.get("WORKHORSE_CHROMIUM_EXECUTABLE")
                            else {}
                        ),
                    )
                    try:
                        context = browser.new_context(
                            service_workers="block", accept_downloads=False
                        )
                        if hasattr(context, "route_web_socket"):
                            context.route_web_socket("**/*", lambda ws: ws.close())
                        context.route(
                            "**/*",
                            lambda route: (
                                route.continue_()
                                if route.request.url.startswith(origin + "/")
                                else route.abort()
                            ),
                        )
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.set_default_timeout(5000)
                        checks = []
                        screenshots = []
                        for width, height in ((1440, 1000), (390, 844)):
                            page.set_viewport_size({"width": width, "height": height})
                            page.goto(origin, wait_until="networkidle")
                            if page.evaluate(
                                "document.documentElement.scrollWidth>innerWidth"
                            ):
                                raise ValueError(f"Horizontal overflow at {width}px.")
                            for selector in ("#prompt", "#send", "#settings"):
                                if not page.locator(selector).is_visible():
                                    raise ValueError(
                                        f"{selector} is not visible at {width}px."
                                    )
                            page.locator("#prompt").fill("Preview interaction check")
                            page.locator("#prompt").fill("")
                            name = f"{width}.png"
                            page.screenshot(path=str(proposal / name), full_page=True)
                            screenshots.append(name)
                            checks.append(
                                f"{width}×{height}: no horizontal overflow; prompt, send and settings visible; typing works."
                            )
                        if errors:
                            raise ValueError("Browser script errors: " + errors[0])
                        return {
                            "checks": checks
                            + [
                                "Isolated static preview; no real conversations or model connection."
                            ],
                            "screenshots": screenshots,
                        }
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)

    def apply(self, id):
        with self.lock:
            if any(
                r.status in ("running", "approval") for r in self.store.runs.values()
            ):
                raise ValueError(
                    "Finish or stop the current agent run before applying appearance changes."
                )
            row = self.get(id)
            if row["status"] != "ready":
                raise ValueError("A successful preview is required before approval.")
            current = self.target.read_bytes() if self.target.exists() else b""
            if digest(current) != row["before_hash"]:
                raise ValueError(
                    "Appearance changed since proposal; create a new proposal."
                )
            raw = (self.directory / id / "proposal.css").read_bytes()
            if digest(raw) != row["after_hash"]:
                raise ValueError("Staged proposal changed after review.")
            validate_css(raw.decode())
            row["status"] = "applying"
            self.save(row)
            try:
                atomic(self.target, raw)
                result = self.render(id)
                if digest(self.target.read_bytes()) != row["after_hash"]:
                    raise ValueError("Post-apply file check failed.")
                row.update(result)
                row["status"] = "applied"
                self.save(row)
            except Exception:
                self._restore(row, "rolled_back_after_failure")
                raise
            return row

    def _restore(self, row, status):
        before = (self.directory / row["id"] / "before.css").read_bytes()
        if digest(before) != row["before_hash"]:
            raise ValueError("Backup checksum failed; automatic recovery refused.")
        atomic(self.target, before)
        row["status"] = status
        self.save(row)

    def rollback(self, id):
        with self.lock:
            row = self.get(id)
            if row["status"] != "applied":
                raise ValueError("Only applied proposals can be rolled back.")
            if digest(self.target.read_bytes()) != row["after_hash"]:
                raise ValueError("Later edits detected; rollback would overwrite them.")
            self._restore(row, "rolled_back")
            return row
