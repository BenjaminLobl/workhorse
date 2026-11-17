from __future__ import annotations

import concurrent.futures
import os
import queue
import threading
import uuid
from urllib.parse import urlsplit

from .research import public_target
from .safety import redact


class Browser:
    """Playwright objects live on one dedicated thread, never HTTP/model threads."""

    def __init__(self, data, allowed):
        self.data = data
        self.allowed = allowed
        self.queue = queue.Queue()
        self.sessions = {}
        self.pw = None
        self.browser = None
        self.blocked_ports = {8765, 11434, 8080, 11235}
        self.thread = threading.Thread(target=self.worker, daemon=True)
        self.thread.start()

    def worker(self):
        while True:
            item = self.queue.get()
            if item is None:
                break
            future, workspace, action, args, online = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(self.perform(workspace, action, args, online))
            except Exception as e:
                future.set_exception(e)
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

    def call(self, workspace, action, args, online=False):
        f = concurrent.futures.Future()
        self.queue.put((f, workspace, action, args, online))
        return f.result(timeout=65)

    def check(self, workspace, url, online):
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or u.username or u.password:
            raise PermissionError("Only HTTP(S) browser pages are allowed.")
        if u.hostname in ("localhost", "127.0.0.1", "::1"):
            origin = f"{u.scheme}://127.0.0.1:{u.port or (443 if u.scheme == 'https' else 80)}"
            if u.port in self.blocked_ports:
                raise PermissionError(
                    "Browser access to Workhorse, Ollama and research control services is blocked."
                )
            if origin not in self.allowed(workspace):
                raise PermissionError(
                    "Local URL not approved. Start its dev server through Workhorse or approve its origin in workspace settings."
                )
        elif online:
            public_target(url)
        else:
            raise PermissionError("Internet access is off for this run.")

    def context(self, workspace, online):
        if not self.pw:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise ValueError(
                    "Install dependencies and run python -m playwright install chromium."
                ) from None
            self.pw = sync_playwright().start()
            try:
                self.browser = self.pw.chromium.launch(
                    headless=True,
                    **(
                        {"executable_path": os.environ["WORKHORSE_CHROMIUM_EXECUTABLE"]}
                        if os.environ.get("WORKHORSE_CHROMIUM_EXECUTABLE")
                        else {}
                    ),
                )
            except Exception:
                self.pw.stop()
                self.pw = None
                raise
        if workspace not in self.sessions:
            ctx = self.browser.new_context(
                viewport={"width": 1440, "height": 900},
                accept_downloads=False,
                service_workers="block",
            )
            session = {"context": ctx, "pages": {}, "logs": [], "online": online}
            self.sessions[workspace] = session

            def route(r):
                try:
                    if r.request.url.startswith("data:"):
                        return r.continue_()
                    self.check(workspace, r.request.url, session["online"])
                    r.continue_()
                except Exception:
                    r.abort()

            ctx.route("**/*", route)
            if hasattr(ctx, "route_web_socket"):

                def ws(r):
                    try:
                        self.check(
                            workspace,
                            r.url.replace("ws:", "http:").replace("wss:", "https:"),
                            session["online"],
                        )
                        r.connect_to_server()
                    except Exception:
                        r.close()

                ctx.route_web_socket("**/*", ws)
        self.sessions[workspace]["online"] = online
        self.sessions[workspace]["context"].set_offline(False)
        return self.sessions[workspace]

    def perform(self, workspace, action, a, online):
        if action == "__pause__":
            if workspace in self.sessions:
                self.sessions[workspace]["online"] = False
                self.sessions[workspace]["context"].set_offline(True)
            return {}
        if action == "browser_open":
            self.check(workspace, a["url"], online)
        s = self.context(workspace, online)
        if action == "browser_tabs":
            return {"tabs": [{"tab": id, "url": p.url} for id, p in s["pages"].items()]}
        if action == "browser_open":
            self.check(workspace, a["url"], online)
            id = uuid.uuid4().hex[:12]
            p = s["context"].new_page()
            s["pages"][id] = p
            p.set_default_timeout(10000)
            p.set_default_navigation_timeout(25000)

            def log(kind, msg):
                s["logs"].append({"tab": id, "kind": kind, "text": redact(str(msg))[:1500]})
                s["logs"][:] = s["logs"][-100:]

            p.on(
                "console",
                lambda m: (log(m.type, m.text) if m.type in ("error", "warning") else None),
            )
            p.on("pageerror", lambda e: log("pageerror", e))
            p.on("requestfailed", lambda r: log("network", r.url + " " + str(r.failure)))
            p.on("dialog", lambda d: d.dismiss())
            p.goto(a["url"], wait_until="domcontentloaded")
            return {"tab": id, "url": p.url, "title": p.title()}
        id = a.get("tab")
        p = s["pages"].get(id)
        if not p:
            raise ValueError("Unknown tab. Use browser_open first.")
        if action == "browser_close":
            p.close()
            del s["pages"][id]
            return {"closed": id}
        if action == "browser_click":
            p.locator(a["selector"]).click()
        elif action == "browser_type":
            if p.locator(a["selector"]).get_attribute("type") == "password":
                raise PermissionError("Password entry is not an agent tool.")
            p.locator(a["selector"]).fill(a["text"])
        elif action == "browser_scroll":
            p.mouse.wheel(0, a.get("pixels", 600))
        elif action == "browser_resize":
            p.set_viewport_size({"width": a["width"], "height": a["height"]})
        elif action == "browser_reload":
            p.reload(wait_until="domcontentloaded")
        elif action == "browser_console":
            return {"events": s["logs"]}
        elif action == "browser_screenshot":
            name = uuid.uuid4().hex + ".png"
            directory = self.data / "screenshots"
            directory.mkdir(exist_ok=True)
            p.screenshot(
                path=str(directory / name),
                full_page=False,
                timeout=15000,
                mask=[p.locator("input[type=password]")],
            )
            return {"screenshot": name, "url": p.url, "viewport": p.viewport_size}
        elif action == "browser_assert":
            loc = p.locator(a["selector"])
            kind = a.get("assertion", "visible")
            if kind == "visible":
                ok = loc.is_visible()
            else:
                ok = a.get("text", "") in loc.inner_text(timeout=10000)
            return {"passed": ok, "selector": a["selector"], "assertion": kind}
        elif action != "browser_dom":
            raise ValueError("Unknown browser action.")
        # Only fixed inspection JS is executed; arbitrary page.evaluate is not a tool.
        dom = p.evaluate(
            """() => ({title:document.title,url:location.href,text:document.body.innerText.slice(0,10000),overflow:document.documentElement.scrollWidth>innerWidth,elements:[...document.querySelectorAll('a,button,input,select,textarea')].slice(0,80).map(e=>({tag:e.tagName,id:e.id,role:e.getAttribute('role'),text:(e.innerText||e.getAttribute('aria-label')||'').slice(0,120),type:e.type,href:e.getAttribute('href')}))})"""
        )
        return redact({"tab": id, **dom})

    def fetch_text(self, url):
        tab = self.call("__research__", "browser_open", {"url": url}, True)["tab"]
        try:
            return self.call("__research__", "browser_dom", {"tab": tab}, True)["text"]
        finally:
            self.call("__research__", "browser_close", {"tab": tab}, True)

    def pause(self, workspace):
        if workspace in self.sessions:
            self.call(workspace, "__pause__", {})

    def close(self):
        self.queue.put(None)
        self.thread.join(timeout=5)
