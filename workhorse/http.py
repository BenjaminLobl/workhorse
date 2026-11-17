"""Loopback HTTP server: session checks, API handlers and frontend assets."""

from __future__ import annotations

import json
import mimetypes
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from .common import ident, now, text

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 600_000


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, workspace):
        super().__init__(("127.0.0.1", port), Handler)
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        if hasattr(workspace, "browser"):
            workspace.browser.blocked_ports.add(self.server_port)

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, *args):
        pass  # Never log prompts, content or session cookies.

    def allowed(self, api=False, write=False):
        host = self.headers.get("Host", "")
        if host not in (
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        ):
            raise PermissionError("Invalid local host.")
        origin = self.headers.get("Origin")
        if origin and origin not in (
            self.server.origin,
            f"http://localhost:{self.server.server_port}",
        ):
            raise PermissionError("Cross-origin requests are disabled.")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PermissionError("Cross-site requests are disabled.")
        if api:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            value = cookie.get("workhorse_session")
            if not value or not secrets.compare_digest(value.value, self.server.token):
                raise PermissionError("Open Workhorse in your local browser first.")
        if write and self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("Expected application/json.")

    def reply(self, status, data, content_type="application/json", cookie=False, filename=None):
        body = (
            json.dumps(data).encode()
            if content_type == "application/json"
            else (data.encode() if isinstance(data, str) else data)
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header(
                "Set-Cookie",
                f"workhorse_session={self.server.token}; HttpOnly; SameSite=Strict; Path=/",
            )
        if filename:
            self.send_header(
                "Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename)
            )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def error(self, e):
        self.reply(403 if isinstance(e, PermissionError) else 400, {"error": str(e)[:500]})

    def do_GET(self):
        try:
            url = urlsplit(self.path)
            q = parse_qs(url.query)
            self.allowed(api=url.path.startswith("/api/"))
            w = self.server.workspace
            if url.path == "/api/appearance-lab":
                return self.reply(200, {"proposals": w.appearance_lab.list()})
            if url.path == "/api/appearance-shot":
                row = w.appearance_lab.get(q.get("id", [""])[0])
                name = q.get("name", [""])[0]
                if name not in row["screenshots"]:
                    raise ValueError("Unknown preview screenshot.")
                return self.reply(
                    200,
                    (w.appearance_lab.directory / row["id"] / name).read_bytes(),
                    "image/png",
                )
            if url.path == "/api/control-theme-preview.css":
                row = w.rows(
                    "SELECT palette FROM cc_themes WHERE id=?", (q.get("id", [""])[0],)
                )
                if not row:
                    raise ValueError("Theme not found.")
                return self.reply(
                    200, w.control_theme_css(json.loads(row[0]["palette"])), "text/css"
                )
            if url.path == "/api/runtime-facts":
                return self.reply(200, w.runtime_facts(probe=True))
            if url.path == "/api/control-centre":
                return self.reply(200, w.control_snapshot())
            if url.path == "/api/control-theme.css":
                return self.reply(200, w.control_theme_css(), "text/css; charset=utf-8")
            if url.path == "/api/workspace":
                return self.reply(200, w.snapshot(q.get("thread", [None])[0]))
            if url.path == "/api/screenshot":
                name = q.get("id", [""])[0]
                if not w.rows("SELECT id FROM screenshots WHERE id=?", (name,)):
                    raise ValueError("Screenshot not found.")
                return self.reply(
                    200, (w.data / "screenshots" / name).read_bytes(), "image/png"
                )
            if url.path == "/api/health":
                import shutil

                return self.reply(
                    200,
                    {
                        "python": True,
                        "docker": bool(shutil.which("docker")),
                        "powershell": bool(shutil.which("pwsh") or shutil.which("powershell")),
                        "config": w.settings(),
                    },
                )
            if url.path == "/api/models":
                return self.reply(200, {"models": w.ollama.models()})
            if url.path == "/api/run":
                r = w.runs.get(q.get("id", [""])[0])
                if not r:
                    raise ValueError(
                        "Run not found. It may have ended when the server restarted."
                    )
                return self.reply(200, w.run_state(r))
            if url.path == "/api/file":
                f = w.file(q.get("thread", [""])[0], q.get("id", [""])[0])
                return self.reply(
                    200, f["content"], "text/plain; charset=utf-8", filename=f["name"]
                )
            if url.path == "/api/audit":
                thread = q.get("thread", [""])[0]
                w.thread(thread)
                return self.reply(
                    200,
                    json.dumps(
                        w.rows(
                            "SELECT event,detail,created FROM audit WHERE thread=? ORDER BY created,rowid",
                            (thread,),
                        ),
                        indent=2,
                    ),
                    "text/plain; charset=utf-8",
                    filename="workhorse-audit.json",
                )
            assets = {
                "/": "index.html",
                "/app.js": "app.js",
                "/style.css": "style.css",
                "/favicon.svg": "favicon.svg",
                "/control-centre.js": "control-centre.js",
                "/workplace.js": "workplace.js",
                "/workplace.css": "workplace.css",
                "/control-centre.css": "control-centre.css",
                "/workhorse-appearance.css": "workhorse-appearance.css",
            }
            if url.path not in assets:
                return self.reply(404, {"error": "Not found"})
            file = ROOT / "web" / assets[url.path]
            return self.reply(
                200,
                file.read_bytes(),
                mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                cookie=url.path == "/",
            )
        except Exception as e:
            self.error(e)

    def do_POST(self):
        try:
            self.allowed(api=True, write=True)
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BODY:
                raise ValueError("Request size is invalid.")
            b = json.loads(self.rfile.read(length))
            w = self.server.workspace
            path = urlsplit(self.path).path
            if not isinstance(b, dict):
                raise ValueError("Expected a JSON object.")
            if path == "/api/appearance-lab":
                action = b.get("action")
                if action == "stage":
                    return self.reply(200, w.appearance_lab.stage(b.get("title"), b.get("css")))
                if action == "preview":
                    return self.reply(200, w.appearance_lab.preview(b.get("id")))
                if action == "apply":
                    return self.reply(200, w.appearance_lab.apply(b.get("id")))
                if action == "rollback":
                    return self.reply(200, w.appearance_lab.rollback(b.get("id")))
                raise ValueError("Unknown appearance action.")
            if path == "/api/control-centre":
                return self.reply(200, w.control_action(b))
            if path == "/api/config":
                return self.reply(200, w.set_settings(b))
            if path == "/api/add-workspace":
                return self.reply(
                    200,
                    w.add_workspace(b.get("name"), b.get("path"), b.get("permissions", {})),
                )
            if path == "/api/workspace-permissions":
                if any(r.status in ("running", "approval") for r in w.runs.values()):
                    raise ValueError("Stop the active run before changing permissions.")
                space = w.workspace(b.get("id"))
                p = space["permissions"]
                for key in (
                    "edit",
                    "terminal",
                    "browser",
                    "internet",
                    "trust_commands",
                ):
                    if key in b:
                        p[key] = b[key] is True
                origins = b.get("origins", p.get("origins", []))
                clean = []
                if not isinstance(origins, list) or len(origins) > 10:
                    raise ValueError("At most ten local origins.")
                for origin in origins:
                    u = urlsplit(origin)
                    if (
                        u.scheme != "http"
                        or u.hostname not in ("localhost", "127.0.0.1")
                        or not u.port
                        or u.port in (8765, 11434, 8080, 11235)
                        or u.username
                    ):
                        raise ValueError("Approve a local app origin, not a control service.")
                    clean.append("http://127.0.0.1:" + str(u.port))
                p["origins"] = clean
                w.write(
                    "UPDATE workspaces SET permissions=? WHERE id=?",
                    (json.dumps(p), space["id"]),
                )
                return self.reply(200, {"ok": True})
            if path == "/api/delete-thread":
                thread = b.get("thread")
                w.thread(thread)
                if any(
                    r.thread == thread and r.status in ("running", "approval")
                    for r in w.runs.values()
                ):
                    raise ValueError("Stop the run before deleting its conversation.")
                with w.connect() as c:
                    for table in ("messages", "files", "thread_workspaces"):
                        c.execute("DELETE FROM " + table + " WHERE thread=?", (thread,))
                    c.execute("DELETE FROM threads WHERE id=?", (thread,))
                return self.reply(200, {"ok": True})
            if path == "/api/project":
                id = ident()
                w.write(
                    "INSERT INTO projects VALUES(?,?,?,?)",
                    (
                        id,
                        text(b.get("name"), 80),
                        str(b.get("instructions", ""))[:6000],
                        now(),
                    ),
                )
                return self.reply(200, {"id": id})
            if path == "/api/thread":
                project = b.get("project") or None
                if project and not w.rows("SELECT id FROM projects WHERE id=?", (project,)):
                    raise ValueError("Project not found.")
                if b.get("workspace"):
                    w.workspace(b["workspace"])
                id = ident()
                w.write(
                    "INSERT INTO threads VALUES(?,?,?,?)",
                    (id, text(b.get("title"), 100), project, now()),
                )
                if b.get("workspace"):
                    w.bind(id, b["workspace"])
                return self.reply(200, {"id": id})
            if path == "/api/upload":
                return self.reply(200, w.save(b.get("thread"), b.get("name"), b.get("content")))
            if path == "/api/start":
                return self.reply(
                    200,
                    w.start(
                        b.get("thread"),
                        b.get("prompt"),
                        b.get("model"),
                        b.get("agent") is True,
                        **(
                            {
                                "mode": b["mode"],
                                "online": b.get("online") is True,
                                "design_first": b.get("design_first") is True,
                            }
                            if "mode" in b
                            else {}
                        ),
                    ),
                )
            if path == "/api/decision":
                w.decide(b.get("run"), b.get("approval"), b.get("approve"))
                return self.reply(200, {"ok": True})
            if path == "/api/stop":
                w.stop(b.get("run"))
                return self.reply(200, {"ok": True})
            if path == "/api/test":
                model = text(b.get("model"), 120)
                caps = w.ollama.validate(model)
                r = w.ollama.chat(
                    model,
                    [
                        {
                            "role": "user",
                            "content": "Reply with only: Workhorse is connected. /no_think",
                        }
                    ],
                    False,
                )
                answer = r.get("message", {}).get("content", "")
                if not answer:
                    raise ValueError("Model returned no text.")
                return self.reply(200, {"answer": answer[:500], "capabilities": caps})
            raise ValueError("Unknown action.")
        except Exception as e:
            self.error(e)
