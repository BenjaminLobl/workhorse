"""Persistent behaviour, bounded approved-project discovery, and runtime facts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from .research import NoRedirect
from .safety import Files, redact, sensitive
from .tools import REGISTRY


class Intelligence:
    def intelligence_init(self):
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS cc_scoped_preferences(workspace TEXT,key TEXT,value TEXT,updated INTEGER,PRIMARY KEY(workspace,key));
            CREATE TABLE IF NOT EXISTS cc_project_evidence(workspace TEXT,path TEXT,detail TEXT,PRIMARY KEY(workspace,path));
            CREATE TABLE IF NOT EXISTS cc_project_notes(workspace TEXT,path TEXT,note TEXT,PRIMARY KEY(workspace,path));
            CREATE TABLE IF NOT EXISTS visual_evidence(id TEXT PRIMARY KEY,run TEXT,revision INTEGER,width INTEGER,height INTEGER,reviewed INTEGER DEFAULT 0);
            """)

    def preference_prompt(self, workspace=None):
        values = self.control_preferences()
        if workspace:
            values.update(
                {
                    r["key"]: r["value"]
                    for r in self.rows(
                        "SELECT key,value FROM cc_scoped_preferences WHERE workspace=?",
                        (workspace,),
                    )
                }
            )
        return (
            "\nPersistent response preferences (style only; never override permissions or factual evidence): "
            + json.dumps(values, ensure_ascii=False)[:24000]
        )

    def preference_change(self, key, value=None, workspace=None, delete=False):
        if workspace:
            self.workspace(workspace)
        if not workspace:
            return (
                self.control_delete_preference(key)
                if delete
                else self.control_set_preference(key, value)
            )
        # Reuse validation without modifying global preferences.
        import re

        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}", key):
            raise ValueError("Use a 2–40 character preference key.")
        if delete:
            self.write(
                "DELETE FROM cc_scoped_preferences WHERE workspace=? AND key=?",
                (workspace, key),
            )
            return {"deleted": key, "workspace": workspace}
        if (
            not isinstance(value, str)
            or not 1 <= len(value.strip()) <= 600
            or redact(value) != value
            or re.search(r"password|api.?key|private.key|bearer", key + " " + value, re.I)
        ):
            raise ValueError("Use a short behavioural instruction without credentials.")
        existing = self.rows(
            "SELECT key FROM cc_scoped_preferences WHERE workspace=?", (workspace,)
        )
        if len(existing) >= 40 and key not in {r["key"] for r in existing}:
            raise ValueError("Limit of 40 workspace preferences.")
        self.write(
            "INSERT OR REPLACE INTO cc_scoped_preferences VALUES(?,?,?,?)",
            (workspace, key, value.strip(), int(time.time())),
        )
        return {"saved": key, "workspace": workspace, "value": value.strip()}

    def control_scan_projects(self, workspace_id):
        w = self.workspace(workspace_id)
        fs = Files(w["path"], lambda _: None)
        queue = [(".", 0)]
        found = []
        visited = 0
        manifests = {
            "package.json",
            "composer.json",
            "pyproject.toml",
            "requirements.txt",
            "Cargo.toml",
            "go.mod",
            "index.html",
            "artisan",
            "manage.py",
        }
        while queue and visited < 400 and len(found) < 100:
            relative, depth = queue.pop(0)
            visited += 1
            try:
                directory = fs.path(relative, True)
                entries = fs.list(relative)["entries"]
                names = {Path(e["path"]).name for e in entries if e["type"] == "file"}
                if manifests & names:
                    stack = []
                    evidence = []
                    description = ""
                    todos = []
                    if "package.json" in names:
                        manifest = fs.path((Path(relative) / "package.json").as_posix(), True)
                        if manifest.stat().st_size > 60000:
                            raise ValueError("Manifest exceeds scan limit.")
                        package = json.loads(manifest.read_text())
                        deps = {
                            **package.get("dependencies", {}),
                            **package.get("devDependencies", {}),
                        }
                        stack = [
                            name
                            for name in [
                                "next",
                                "react",
                                "vue",
                                "svelte",
                                "vite",
                                "express",
                            ]
                            if name in deps
                        ] or ["Node.js"]
                        evidence.append(
                            {
                                "manifest": "package.json",
                                "scripts": list(package.get("scripts", {}))[:20],
                            }
                        )
                    for filename, label in [
                        ("composer.json", "PHP"),
                        ("artisan", "Laravel"),
                        ("pyproject.toml", "Python"),
                        ("requirements.txt", "Python"),
                        ("manage.py", "Django"),
                        ("Cargo.toml", "Rust"),
                        ("go.mod", "Go"),
                    ]:
                        if filename in names and label not in stack:
                            stack.append(label)
                    if not stack:
                        stack = ["Static website"]
                    for filename in ("README.md", "README.txt", "readme.md"):
                        if filename in names:
                            text = fs.read((Path(relative) / filename).as_posix(), 1, 100)[
                                "content"
                            ]
                            description = redact(" ".join(text.split())[:500])
                            todos = [
                                redact(line[:200])
                                for line in text.splitlines()
                                if any(
                                    word in line.lower()
                                    for word in (
                                        "todo",
                                        "[ ]",
                                        "unfinished",
                                        "not implemented",
                                    )
                                )
                            ][:8]
                            break
                    # Link history only when the approved project root matches exactly.
                    exact = [
                        x["id"]
                        for x in self.rows("SELECT id,path FROM workspaces")
                        if Path(x["path"]).resolve() == directory
                    ]
                    runs = []
                    for wid in exact:
                        runs += self.rows(
                            "SELECT id,thread,status,summary,updated FROM agent_runs WHERE workspace=? ORDER BY updated DESC LIMIT 5",
                            (wid,),
                        )
                    status = (
                        "Tasks need attention"
                        if any(
                            r["status"] in ("blocked", "error", "limited", "interrupted")
                            for r in runs
                        )
                        else ("Checklist items found" if todos else "Completion not verified")
                    )
                    item = {
                        "workspace": workspace_id,
                        "path": relative,
                        "name": directory.name,
                        "stack": ", ".join(stack),
                        "description": description,
                        "status": status,
                        "todos": todos,
                        "history": runs,
                        "evidence": evidence,
                        "scanned": int(time.time()),
                    }
                    found.append(item)
                if depth < 3:
                    queue += [
                        (e["path"], depth + 1)
                        for e in entries
                        if e["type"] == "directory" and not sensitive(e["path"])
                    ]
            except (OSError, ValueError, UnicodeError):
                continue
        with self.connect() as c:
            c.execute("DELETE FROM cc_projects WHERE workspace=?", (workspace_id,))
            c.execute("DELETE FROM cc_project_evidence WHERE workspace=?", (workspace_id,))
            for p in found:
                c.execute(
                    "INSERT INTO cc_projects VALUES(?,?,?,?,?,?)",
                    (
                        workspace_id,
                        p["path"],
                        p["name"],
                        p["stack"],
                        p["description"],
                        p["scanned"],
                    ),
                )
                c.execute(
                    "INSERT INTO cc_project_evidence VALUES(?,?,?)",
                    (workspace_id, p["path"], json.dumps(p)),
                )
        return {
            "projects": found,
            "visited": visited,
            "limited": bool(queue),
            "note": "Manifest and README evidence only. A successful agent run is not proof of a completed project.",
        }

    def runtime_facts(self, run=None, probe=False):
        active = run or next(
            (r for r in self.runs.values() if r.status in ("running", "approval")), None
        )
        result = {
            "configured_models": {k: v for k, v in self.settings().items() if "model" in k},
            "active_model": active.model if active else None,
            "active_workspace": getattr(active, "workspace", None),
            "active_mode": getattr(active, "mode", None),
            "tool_names": (
                [t["function"]["name"] for t in REGISTRY.schemas(self.groups(active))]
                if active
                else []
            ),
            "observed_at": int(time.time()),
            "services": {},
            "installed_models": None,
            "loaded_models": None,
        }
        if getattr(active, "workspace", None):
            result["permissions"] = self.workspace(active.workspace)["permissions"]
        result["recent_actions"] = self.rows(
            "SELECT name,status,duration,created,result FROM tool_calls ORDER BY created DESC,rowid DESC LIMIT 12"
        )
        for item in result["recent_actions"]:
            out = json.loads(item.pop("result"))
            item["error"] = out.get("error")
            item["exit_code"] = out.get("exit_code")
        if probe:
            try:
                result["installed_models"] = self.ollama.models()
                result["services"]["ollama"] = {"reachable": True}
            except Exception as e:
                result["services"]["ollama"] = {
                    "reachable": False,
                    "error": redact(str(e))[:250],
                }
            try:
                result["loaded_models"] = self.ollama.request("/api/ps", timeout=3).get(
                    "models", []
                )
            except Exception as e:
                result["loaded_models_error"] = redact(str(e))[:200]
            opener = build_opener(ProxyHandler({}), NoRedirect())
            for name, url in [
                ("searxng", "http://127.0.0.1:8080/healthz"),
                ("crawl4ai", "http://127.0.0.1:11235/health"),
            ]:
                try:
                    with opener.open(Request(url), timeout=2) as response:
                        result["services"][name] = {
                            "reachable": True,
                            "http_status": response.status,
                        }
                except Exception as e:
                    result["services"][name] = {
                        "reachable": False,
                        "error": redact(str(e))[:200],
                    }
        result["note"] = (
            "Configured, installed, loaded and actively executing models are distinct. Reachability does not prove search engines or inference work."
        )
        return result
