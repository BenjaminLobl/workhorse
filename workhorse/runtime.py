from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path

from .appearance_lab import SELECTORS, AppearanceLab  # WORKHORSE_COMPANION_V2
from .browser import Browser
from .changes import capture, record_command_changes
from .common import ident, now, text
from .control_centre import ControlCentre  # WORKHORSE_CONTROL_CENTRE_V1
from .intelligence import Intelligence
from .processes import Processes
from .prompts import DESIGN_FIRST_PROMPT, PROMPT
from .research import Research
from .safety import Files, redact
from .settings import ModelSettings
from .tools import REGISTRY
from .workplace import Workplace  # WORKHORSE_WORKPLACE_V1
from .workspace import Run, Workspace


class Workbench(Workspace, Intelligence, ControlCentre, Workplace, ModelSettings):
    def __init__(self, data, ollama=None):
        super().__init__(data, ollama)
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL,permissions TEXT NOT NULL,created INTEGER);
            CREATE TABLE IF NOT EXISTS thread_workspaces(thread TEXT PRIMARY KEY,workspace TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS agent_runs(id TEXT PRIMARY KEY,thread TEXT,workspace TEXT,model TEXT,status TEXT,summary TEXT,created INTEGER,updated INTEGER);
            CREATE TABLE IF NOT EXISTS tool_calls(id TEXT PRIMARY KEY,run TEXT,workspace TEXT,name TEXT,args TEXT,result TEXT,status TEXT,created INTEGER,duration REAL);
            CREATE TABLE IF NOT EXISTS changes(id TEXT PRIMARY KEY,workspace TEXT,run TEXT,path TEXT,detail TEXT,created INTEGER);
            CREATE TABLE IF NOT EXISTS cache(kind TEXT,key TEXT,value TEXT,created REAL,expires REAL,bytes INTEGER,PRIMARY KEY(kind,key));
            CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS screenshots(id TEXT PRIMARY KEY,workspace TEXT,run TEXT,created INTEGER);
            """)
            c.execute(
                "UPDATE agent_runs SET status='interrupted',summary='Server restarted; processes and browser sessions were not restored.' WHERE status IN ('running','approval')"
            )
        self.processes = Processes()
        self.research = Research(self)
        self.browser = Browser(self.data, self.origins)
        self.control_init()
        self.intelligence_init()
        self.workplace_init()
        self.appearance_lab = AppearanceLab(self, Path(__file__).resolve().parents[1])

    def workspace(self, id):
        rows = self.rows("SELECT * FROM workspaces WHERE id=?", (id,))
        if not rows:
            raise ValueError("Workspace not found.")
        w = rows[0]
        w["permissions"] = json.loads(w["permissions"])
        return w

    def add_workspace(self, name, path, permissions):
        root = Path(path).expanduser().resolve(strict=True)
        Files(root, lambda r: None)
        if (
            root == Path.home()
            or self.data.is_relative_to(root)
            or Path(__file__).resolve().parents[1].is_relative_to(root)
        ):
            raise ValueError(
                "Choose a project subfolder, not your home or Workhorse installation/data directory."
            )
        p = {
            key: permissions.get(key) is True
            for key in ("edit", "terminal", "browser", "internet", "trust_commands")
        }
        p["origins"] = []
        id = ident()
        self.write(
            "INSERT INTO workspaces VALUES(?,?,?,?,?)",
            (id, text(name, 80), str(root), json.dumps(p), now()),
        )
        return self.workspace(id)

    def bind(self, thread, workspace):
        self.thread(thread)
        self.workspace(workspace)
        if self.rows("SELECT * FROM thread_workspaces WHERE thread=?", (thread,)):
            raise ValueError(
                "A conversation cannot switch filesystem workspace. Start a new conversation."
            )
        self.write("INSERT INTO thread_workspaces VALUES(?,?)", (thread, workspace))

    def origins(self, workspace):
        if workspace == "__research__":
            return set()
        try:
            return set(
                self.workspace(workspace)["permissions"].get("origins", [])
            ) | self.processes.urls(workspace)
        except ValueError:
            return set()

    def snapshot(self, thread=None):
        d = super().snapshot(thread)
        d["workspaces"] = [
            self.workspace(w["id"])
            for w in self.rows("SELECT id FROM workspaces ORDER BY created DESC")
        ]
        d["config"] = self.settings()
        d["progress_preview"] = self.progress_preview(thread) if thread else None
        if thread:
            binding = self.rows(
                "SELECT workspace FROM thread_workspaces WHERE thread=?", (thread,)
            )
            wid = binding[0]["workspace"] if binding else None
            d["workspace_id"] = wid
            d["changes"] = (
                [
                    json.loads(x["detail"])
                    for x in self.rows(
                        "SELECT detail FROM changes WHERE workspace=? ORDER BY created DESC LIMIT 50",
                        (wid,),
                    )
                ]
                if wid
                else []
            )
        return d

    def record(self, run, row):
        self.write(
            "INSERT INTO changes VALUES(?,?,?,?,?,?)",
            (
                ident(),
                run.workspace,
                run.id,
                row["path"],
                json.dumps(redact(row)),
                now(),
            ),
        )

    def groups(self, r):
        groups = {"plan", "attachment", "memory"}
        if r.mode == "chat":
            return {"memory"}
        if r.online and (
            not r.workspace or self.workspace(r.workspace)["permissions"]["internet"]
        ):
            groups.add("internet")
        if r.workspace and r.mode in ("agent", "work"):
            p = self.workspace(r.workspace)["permissions"]
            groups.add("file")
            if p["edit"]:
                groups.add("edit")
            if p["terminal"]:
                groups.add("terminal")
            if p["browser"]:
                groups.add("browser")
        return groups

    def approval(self, r, name, args):
        with r.lock:
            r.decision.clear()
            r.approved = False
            r.pending = {
                "id": ident(),
                "name": name,
                "content": json.dumps(redact(args), indent=2),
            }
            r.status = "approval"
            r.detail = "Review this action before it runs."
        self.write("UPDATE agent_runs SET status=? WHERE id=?", ("approval", r.id))
        r.decision.wait(300)
        with r.lock:
            ok = r.approved and not r.cancel.is_set()
            r.pending = None
            r.status = "running"
        self.write("UPDATE agent_runs SET status=? WHERE id=?", ("running", r.id))
        if not ok:
            raise PermissionError(
                "Action was rejected, cancelled or approval expired. Do not retry it."
            )

    def execute(self, r, name, a):
        groups = self.groups(r)
        REGISTRY.validate(name, a, groups)
        if r.cancel.is_set():
            raise ValueError("Run cancelled.")
        if name == "inspect_workhorse_frontend":
            root = Path(__file__).resolve().parents[1] / "web"
            return {
                "editable_surface": "Restricted CSS appearance overlay only. Backend and JavaScript edits are not available.",
                "selectors": sorted(SELECTORS),
                "css": (root / "style.css").read_text()[:16000],
                "html": (root / "index.html").read_text()[:16000],
            }
        if name == "propose_self_appearance":
            row = self.appearance_lab.stage(a["title"], a["css"])
            return self.appearance_lab.preview(row["id"])
        if name == "control_info":
            return self.runtime_facts(r, probe=True)
        if name == "list_preferences":
            return {
                "global": self.control_preferences(),
                "workspace": self.rows(
                    "SELECT key,value FROM cc_scoped_preferences WHERE workspace=?",
                    (r.workspace,),
                ),
            }
        if name in ("remember_preference", "forget_preference"):
            scope = r.workspace if a.get("scope") == "workspace" else None
            if a.get("scope") == "workspace" and not scope:
                raise ValueError("Select a workspace first.")
            self.approval(r, name, a)
            return self.preference_change(
                a["key"], a.get("value"), scope, delete=name == "forget_preference"
            )
        if name == "scan_approved_projects":
            if not r.workspace:
                raise PermissionError(
                    "Choose an approved workspace before scanning project files."
                )
            return self.control_scan_projects(r.workspace)
        if name == "propose_workhorse_theme":
            return self.control_propose_theme(a["title"], a["note"], a["palette"])
        if name == "update_plan":
            r.plan = a["steps"]
            return a
        if name == "finish_task":
            if a["status"] == "success" and r.mode == "work" and r.changed and not r.verified:
                raise ValueError(
                    "File changes have no successful test/build/browser assertion. Verify them or finish with status blocked and state the limitation."
                )
            if (
                a["status"] == "success"
                and getattr(r, "design_first", False)
                and r.changed
                and not {"desktop", "mobile"}.issubset(getattr(r, "visual_reviews", set()))
            ):
                raise ValueError(
                    "Design-first changes require a desktop and mobile browser screenshot reviewed with "
                    "inspect_screenshot after the latest file edits. If unavailable, finish blocked."
                )
            r.finished = a
            return {"finished": a["status"]}
        if name in (
            "list_attachments",
            "read_attachment",
            "csv_summary",
            "create_file",
        ):
            if name == "create_file":
                self.approval(r, name, a)
            out = super().tool(
                r.thread,
                {"list_attachments": "list_files", "read_attachment": "read_file"}.get(
                    name, name
                ),
                a,
                approved=name == "create_file",
            )
            if isinstance(out, dict) and isinstance(out.get("content"), str):
                out["content"] = out["content"][:18000]
            return out
        if name == "search_web":
            return self.research.search(a["query"], a.get("freshness", "reference"))
        if name == "fetch_webpage":
            if a.get("reader") == "crawl4ai":
                self.approval(
                    r,
                    name,
                    {
                        "url": a["url"],
                        "reader": "Crawl4AI",
                        "warning": "The optional crawler runs in Docker. Unlike the built-in reader, its redirects and subresources do not use Workhorse network restrictions. Approve only a public URL you trust.",
                    },
                )
            return self.research.page(
                a["url"],
                a.get("freshness", "reference"),
                a.get("reader", "auto"),
                self.browser.fetch_text,
            )
        w = self.workspace(r.workspace)
        fs = Files(w["path"], lambda row: self.record(r, row))
        if name == "list_files":
            return fs.list(a.get("path", "."))
        if name == "read_file":
            return fs.read(a["path"], a.get("start", 1), a.get("lines", 200))
        if name == "search_files":
            return fs.search(a["query"])
        if name in ("write_file", "edit_file", "rename_file", "delete_file"):
            if name == "delete_file":
                self.approval(r, name, a)
            if name == "write_file":
                out = fs.write(a["path"], a["content"], a["reason"], a.get("expected_hash"))
            elif name == "edit_file":
                out = fs.edit(a["path"], a["old_text"], a["new_text"], a["reason"])
            elif name == "rename_file":
                out = fs.rename(a["path"], a["destination"], a["reason"])
            else:
                out = fs.delete(a["path"], a["reason"])
            r.changed = True
            r.verified = False
            r.visual_verified = False
            r.visual_reviews = set()
            r.revision = getattr(r, "revision", 0) + 1
            return out
        if name in ("run_terminal", "run_tests"):
            command = a["command"]
            trusted = w["permissions"]["trust_commands"] and self.processes.routine(command)
            if not trusted:
                self.approval(
                    r,
                    name,
                    {
                        "command": command,
                        "directory": w["path"],
                        "warning": "A native command can access files and networks outside this workspace. Approve only commands you trust.",
                    },
                )
            before = capture(fs)
            out = self.processes.start(
                r.workspace,
                fs.root,
                command,
                a.get("background", False),
                a.get("timeout", 3600 if a.get("background") else 120),
                r.cancel,
            )
            out.update(
                record_command_changes(
                    fs,
                    before,
                    capture(fs),
                    "Approved command: " + redact(command)[:200],
                )
            )
            if out["changed_files"]:
                r.changed = True
                r.verified = False
                r.visual_verified = False
                r.visual_reviews = set()
                r.revision = getattr(r, "revision", 0) + 1
            if out["exit_code"] == 0 and (
                name == "run_tests"
                or any(x in command for x in (" test", "build", "pytest", "phpunit"))
            ):
                r.verified = True
            return out
        if name == "process_output":
            return self.processes.snapshot(a["id"], r.workspace)
        if name == "stop_process":
            return self.processes.stop(a["id"], r.workspace)
        if name == "inspect_screenshot":
            rows = self.rows(
                "SELECT * FROM screenshots WHERE id=? AND workspace=?",
                (a["screenshot"], r.workspace),
            )
            if not rows:
                raise ValueError("Screenshot not found in this workspace.")
            if getattr(r, "design_first", False) and rows[0]["run"] != r.id:
                raise ValueError(
                    "Design-first review requires a screenshot from the active run."
                )
            model = self.settings()["vision_model"] or r.model
            caps = self.ollama.validate(model)
            if "vision" not in caps:
                raise ValueError("Select an installed vision-capable model in settings.")
            image = base64.b64encode(
                (self.data / "screenshots" / a["screenshot"]).read_bytes()
            ).decode()
            response = self.ollama.request(
                "/api/chat",
                {
                    "model": model,
                    "stream": False,
                    "format": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "critical_issues": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["summary", "critical_issues"],
                        "additionalProperties": False,
                    },
                    "messages": [
                        {
                            "role": "user",
                            "content": a["question"]
                            + self.preference_prompt(r.workspace)
                            + " Describe only visible evidence. Look for overlap, clipping, overflow, unreadable text, distorted images and broken layout. Return JSON with summary and critical_issues (array). Report critical issues honestly; do not claim interactive behaviour from a screenshot.",
                            "images": [image],
                        }
                    ],
                    "options": {"num_ctx": 8192, "num_predict": 2048},
                },
                timeout=180,
            )
            findings = response.get("message", {}).get("content", "")
            if not findings or response.get("done_reason") == "length":
                raise ValueError(
                    "Vision response was empty or truncated; no completed visual review is recorded."
                )
            try:
                review = json.loads(findings)
                if not isinstance(review.get("summary"), str) or not isinstance(
                    review.get("critical_issues"), list
                ):
                    raise ValueError()
            except (ValueError, AttributeError):
                raise ValueError(
                    "Vision model did not return a structured critique; visual completion is not verified."
                )
            if review["critical_issues"]:
                return {
                    "findings": review["summary"],
                    "critical_issues": review["critical_issues"],
                    "visual_passed": False,
                    "model": model,
                    "screenshot": a["screenshot"],
                }
            evidence = self.rows("SELECT * FROM visual_evidence WHERE id=?", (a["screenshot"],))
            if getattr(r, "design_first", False):
                if not evidence or evidence[0]["revision"] != getattr(r, "revision", 0):
                    raise ValueError(
                        "Screenshot predates the latest edits; capture and review it again."
                    )
                width = evidence[0]["width"]
                r.visual_reviews = getattr(r, "visual_reviews", set())
                if width <= 480:
                    r.visual_reviews.add("mobile")
                if width >= 1024:
                    r.visual_reviews.add("desktop")
            self.write("UPDATE visual_evidence SET reviewed=1 WHERE id=?", (a["screenshot"],))
            r.visual_verified = True
            return {
                "findings": review["summary"],
                "critical_issues": [],
                "visual_passed": True,
                "model": model,
                "screenshot": a["screenshot"],
            }
        if name.startswith("browser_"):
            out = self.browser.call(
                r.workspace, name, a, r.online and w["permissions"]["internet"]
            )
            if out.get("screenshot"):
                self.write(
                    "INSERT INTO screenshots VALUES(?,?,?,?)",
                    (out["screenshot"], r.workspace, r.id, now()),
                )
                self.write(
                    "INSERT INTO visual_evidence VALUES(?,?,?,?,?,0)",
                    (
                        out["screenshot"],
                        r.id,
                        getattr(r, "revision", 0),
                        out.get("viewport", {}).get("width", 0),
                        out.get("viewport", {}).get("height", 0),
                    ),
                )
            out = self.capture_progress(r, name, a, out)
            if name == "browser_assert" and out.get("passed"):
                r.verified = True
            return out
        raise ValueError("Tool not implemented.")

    def select_run_model(self, selected_model, mode, design_first):
        """Routing occurs server-side; never ask the LLM to switch itself."""
        settings = self.settings()
        if mode == "work":
            return settings["design_model"] if design_first else settings["coding_model"]
        return selected_model

    def start(
        self,
        thread,
        prompt,
        model,
        agent=True,
        mode=None,
        online=False,
        design_first=False,
    ):
        if mode is None:
            return super().start(thread, prompt, model, agent)
        if mode not in ("chat", "search", "agent", "work"):
            raise ValueError("Unknown mode.")
        self.thread(thread)
        prompt = text(prompt, 12000)
        model = text(model, 120)
        if type(design_first) is not bool:
            raise ValueError("Invalid design-first option.")
        design_first = design_first and mode == "work"
        model = text(self.select_run_model(model, mode, design_first), 120)
        with self.lock:
            if any(r.status in ("running", "approval") for r in self.runs.values()):
                raise ValueError("Stop or finish the active run first.")
            binding = self.rows(
                "SELECT workspace FROM thread_workspaces WHERE thread=?", (thread,)
            )
            wid = binding[0]["workspace"] if binding else None
            if mode == "work" and not wid:
                raise ValueError(
                    "Choose an approved filesystem workspace, or use Chat/Search mode."
                )
            if len(self.runs) > 100:
                self.runs = {
                    k: r for k, r in self.runs.items() if r.status in ("running", "approval")
                }
            self.message(thread, "user", prompt)
            r = Run(ident(), thread, model)
            r.workspace = wid
            r.mode = mode
            r.design_first = design_first
            r.visual_verified = False
            r.visual_reviews = set()
            r.revision = getattr(r, "revision", 0) + 1
            r.online = online
            r.plan = []
            r.sources = {}
            r.finished = None
            r.changed = False
            r.verified = False
            self.runs[r.id] = r
            self.write(
                "INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?)",
                (r.id, thread, wid, model, "running", "", now(), now()),
            )
        threading.Thread(target=self.run_local, args=(r,), daemon=True).start()
        return self.run_state(r)

    def answer(self, r, content):
        missing = [
            (url, title)
            for url, title in getattr(r, "sources", {}).items()
            if url not in content
        ][:8]
        if missing:
            content += "\n\nPages opened:\n" + "\n".join(
                "[" + title + "](" + url + ")" for url, title in missing
            )
        self.message(r.thread, "assistant", redact(content))

    def model_call(self, r, messages, schemas):
        cfg = self.settings()
        return self.ollama.request(
            "/api/chat",
            {
                "model": r.model,
                "messages": messages,
                "tools": schemas,
                "stream": False,
                "options": {
                    "num_ctx": cfg["context"],
                    "num_predict": cfg["output"],
                    "temperature": 0.2,
                },
                **({"think": r.think} if r.think is not None else {}),
            },
            timeout=180,
        )

    def compact(self, messages, plan, budget, design_first=False):
        # Preserve system + latest task; drop complete earlier assistant/tool groups together.
        for m in messages:
            if m["role"] == "tool" and len(m.get("content", "")) > 9000:
                m["content"] = (
                    m["content"][:9000]
                    + "\n[Result excerpt; use focused file sections or page retrieval for more.]"
                )
        while len(json.dumps(messages)) > budget and len(messages) > 4:
            end = 2
            while end < len(messages) and messages[end].get("role") == "tool":
                end += 1
            if end >= len(messages):
                break
            del messages[1:end]
        messages[0]["content"] = (
            PROMPT
            + (DESIGN_FIRST_PROMPT if design_first else "")
            + self.workplace_prompt()
            + self.preference_prompt(messages[0].get("workspace"))
            + "\nFor model identity, permissions, services or recent failures, call control_info; never infer those facts from training or configuration alone. Save memory only when the user explicitly requests lasting behaviour; ask for action approval. Workhorse self-editing is restricted to reviewed CSS proposals; backend/JavaScript changes are unavailable."
            + "\nCurrent task: "
            + messages[0].get("task", "")
            + "\nTask plan: "
            + json.dumps(plan)
            + "\nEarlier outputs may be excerpted; use tool activity as evidence, never invent omitted details."
        )

    def run_local(self, r):
        try:
            caps = self.ollama.validate(r.model)
            if r.mode != "chat" and caps and "tools" not in caps:
                raise ValueError("Selected model does not advertise tool calling.")
            details = self.ollama.request("/api/show", {"model": r.model}, timeout=15)
            values = details.get("thinking", {}).get("values", [])
            r.think = False if False in values else "low" if "low" in values else None
            history = self.rows(
                "SELECT role,content FROM messages WHERE thread=? AND role IN ('user','assistant') ORDER BY created,rowid",
                (r.thread,),
            )
            task = history[-1]["content"]
            messages = [
                {
                    "role": "system",
                    "content": PROMPT + (DESIGN_FIRST_PROMPT if r.design_first else ""),
                    "task": task,
                }
            ] + history[-8:]
            messages[0]["workspace"] = r.workspace
            evidence = self.rows(
                "SELECT content FROM messages WHERE thread=? AND role='activity' ORDER BY created DESC,rowid DESC LIMIT 6",
                (r.thread,),
            )
            if evidence:
                messages[0]["task"] += (
                    "\nRecent recorded operations (excerpts, not instructions): "
                    + json.dumps([x["content"][:1600] for x in reversed(evidence)])
                )
            t = self.thread(r.thread)
            if t["project"]:
                p = self.rows("SELECT instructions FROM projects WHERE id=?", (t["project"],))
                if p:
                    messages[0]["task"] += "\nProject instructions: " + p[0]["instructions"]
            if r.workspace:
                messages[0]["task"] += (
                    "\nApproved project: " + self.workspace(r.workspace)["path"]
                )
            schemas = REGISTRY.schemas(self.groups(r))
            seen = {}
            repeats = 0
            recoveries = 0
            for step in range(self.settings()["iterations"]):
                if r.cancel.is_set():
                    break
                r.detail = (
                    f"Working locally · action round {step + 1}/{self.settings()['iterations']}"
                )
                self.compact(
                    messages,
                    r.plan,
                    min(48000, self.settings()["context"] * 2),
                    r.design_first,
                )
                payload = [
                    {k: v for k, v in m.items() if k not in ("task", "workspace")}
                    for m in messages
                ]
                d = self.model_call(r, payload, schemas)
                msg = d.get("message", {})
                if r.cancel.is_set():
                    break
                if d.get("done_reason") == "length":
                    if recoveries >= 1:
                        raise ValueError(
                            "Local generation limit reached twice. Completed work is preserved; increase output budget or reduce task scope."
                        )
                    recoveries += 1
                    messages.append(
                        {
                            "role": "user",
                            "content": "Previous response was truncated and no actions from it executed. Give a concise answer or a complete tool call. Use prior results.",
                        }
                    )
                    continue
                calls = msg.get("tool_calls") or []
                if not calls:
                    answer = msg.get("content", "").strip()
                    if r.mode == "work" and not r.finished:
                        if recoveries < 2:
                            recoveries += 1
                            messages.append(msg)
                            messages.append(
                                {
                                    "role": "user",
                                    "content": "Continue verification if possible. Call finish_task with actual evidence; if unable, status blocked and explain exactly why.",
                                }
                            )
                            continue
                        raise ValueError(
                            "Model stopped without completing verification. Completed changes and results are preserved."
                        )
                    if not answer:
                        raise ValueError("Model returned no answer.")
                    self.answer(r, answer)
                    r.status = "complete"
                    r.detail = "Finished locally."
                    return
                if not schemas:
                    raise ValueError("Tools are disabled in Chat mode.")
                if len(calls) > 12:
                    raise ValueError("Model requested too many tools in one turn.")
                messages.append({k: v for k, v in msg.items() if k != "thinking"})
                for call in calls:
                    if r.cancel.is_set():
                        break
                    name = call.get("function", {}).get("name", "")
                    a = call.get("function", {}).get("arguments", {})
                    started = time.monotonic()
                    key = None
                    try:
                        if isinstance(a, str):
                            a = json.loads(a)
                        REGISTRY.validate(name, a, self.groups(r))
                        key = name + json.dumps(a, sort_keys=True)
                        if key in seen and "error" in seen[key]:
                            repeats += 1
                            out = {
                                **seen[key],
                                "reused": True,
                                "instruction": "Do not repeat unchanged failed actions; change the approach.",
                            }
                        else:
                            r.detail = name.replace("_", " ")
                            out = self.execute(r, name, a)
                            out = out if isinstance(out, dict) else {"result": out}
                            seen[key] = out
                            if "error" not in out:
                                repeats = 0
                                if name in {
                                    "write_file",
                                    "edit_file",
                                    "rename_file",
                                    "delete_file",
                                    "run_terminal",
                                    "run_tests",
                                    "browser_open",
                                    "browser_click",
                                    "browser_type",
                                    "browser_reload",
                                }:
                                    # A changed project/page may make a previously failed action valid.
                                    seen.clear()
                    except Exception as e:
                        out = {"error": redact(str(e))[:1000]}
                        if key:
                            seen[key] = out
                    safe = redact(out)
                    if name == "fetch_webpage" and "error" not in safe:
                        for source in safe.get("sources", []):
                            r.sources[source["url"]] = source.get("title", source["url"])
                    status = (
                        "error"
                        if "error" in safe
                        or safe.get("passed") is False
                        or safe.get("visual_passed") is False
                        or safe.get("exit_code") not in (None, 0)
                        else "ok"
                    )
                    duration = round(time.monotonic() - started, 3)
                    safe_args = redact(a)
                    safe_args = (
                        safe_args
                        if isinstance(safe_args, dict)
                        else {"invalid_arguments": str(safe_args)[:1000]}
                    )
                    safe_args = {
                        k: (
                            v[:12000] + " [excerpt]"
                            if isinstance(v, str) and len(v) > 12000
                            else v
                        )
                        for k, v in safe_args.items()
                    }
                    self.write(
                        "INSERT INTO tool_calls VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            ident(),
                            r.id,
                            r.workspace,
                            name,
                            json.dumps(safe_args),
                            json.dumps(safe),
                            status,
                            now(),
                            duration,
                        ),
                    )
                    self.message(
                        r.thread,
                        "activity",
                        json.dumps(
                            {
                                "tool": name,
                                "status": status,
                                "args": safe_args,
                                "result": safe,
                                "duration": duration,
                            }
                        ),
                    )
                    messages.append(
                        {"role": "tool", "tool_name": name, "content": json.dumps(safe)}
                    )
                    if r.finished:
                        self.answer(
                            r,
                            r.finished["summary"]
                            + "\n\nEvidence:\n"
                            + "\n".join(r.finished["evidence"]),
                        )
                        r.status = (
                            "complete" if r.finished["status"] == "success" else "blocked"
                        )
                        r.detail = (
                            "Finished."
                            if r.status == "complete"
                            else "Blocked; see the task summary."
                        )
                        return
                if repeats >= 4:
                    raise ValueError(
                        "Stopped repeated identical tool calls. Change the approach or resolve the recorded error before retrying."
                    )
            r.status = "stopped" if r.cancel.is_set() else "limited"
            r.detail = (
                "Stopped; completed work is saved."
                if r.cancel.is_set()
                else "Iteration limit reached; completed work is saved. Send a follow-up to continue."
            )
        except Exception as e:
            r.status = "error"
            r.detail = redact(str(e))[:600]
        finally:
            try:
                self.browser.pause(r.workspace)
            except Exception:
                pass
            r.pending = None
            self.write(
                "UPDATE agent_runs SET status=?,summary=?,updated=? WHERE id=?",
                (r.status, r.detail, now(), r.id),
            )
            self.log(r.thread, "run_finished", {"status": r.status, "message": r.detail})

    def close(self):
        for r in self.runs.values():
            r.cancel.set()
            r.decision.set()
        self.processes.close()
        self.browser.close()
