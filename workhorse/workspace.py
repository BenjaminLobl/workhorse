"""Conversation storage, approvals and the basic attachment workflow."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .common import ident, now, safe_name, text
from .ollama import Ollama
from .prompts import SYSTEM

MAX_FILE = 200_000
MAX_CONTEXT_CHARS = 24000


@dataclass
class Run:
    id: str
    thread: str
    model: str
    status: str = "running"
    detail: str = "Starting local model…"
    cancel: threading.Event = field(default_factory=threading.Event)
    decision: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)
    pending: dict | None = None
    approved: bool = False


class Workspace:
    def __init__(self, data: Path, ollama=None):
        self.data = data.resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.database = self.data / "workhorse.sqlite3"
        self.ollama = ollama or Ollama()
        self.runs = {}
        self.lock = threading.RLock()
        with self.connect() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,instructions TEXT NOT NULL,created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS threads(id TEXT PRIMARY KEY,title TEXT NOT NULL,project TEXT,created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,thread TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread);
            CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,thread TEXT NOT NULL,name TEXT NOT NULL,content TEXT NOT NULL,created INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_files_thread ON files(thread);
            CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,thread TEXT NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL,created INTEGER NOT NULL);
            """)
        try:
            os.chmod(self.data, 0o700)
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    @contextmanager
    def connect(self):
        # SQLite's own context manager commits/rolls back but does not close.
        # Explicit closure is essential for Windows file deletion and shutdown.
        c = sqlite3.connect(self.database, timeout=15)
        try:
            c.row_factory = sqlite3.Row
            with c:
                yield c
        finally:
            c.close()

    def rows(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def write(self, sql, args=()):
        with self.connect() as c:
            c.execute(sql, args)

    def thread(self, id):
        rows = self.rows("SELECT * FROM threads WHERE id=?", (id,))
        if not rows:
            raise ValueError("Conversation not found.")
        return rows[0]

    def log(self, thread, event, detail):
        self.write(
            "INSERT INTO audit VALUES(?,?,?,?,?)",
            (ident(), thread, event, json.dumps(detail), now()),
        )

    def message(self, thread, role, content):
        self.thread(thread)
        self.write(
            "INSERT INTO messages VALUES(?,?,?,?,?)",
            (ident(), thread, role, text(content, 100000), now()),
        )

    def file(self, thread, id):
        rows = self.rows("SELECT * FROM files WHERE id=? AND thread=?", (id, thread))
        if not rows:
            raise ValueError("File is not in this conversation.")
        return rows[0]

    def save(self, thread, name, content):
        self.thread(thread)
        name = safe_name(name)
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE:
            raise ValueError("Use a text file smaller than 200 KB.")
        id = ident()
        self.write("INSERT INTO files VALUES(?,?,?,?,?)", (id, thread, name, content, now()))
        self.log(
            thread,
            "file_saved",
            {"id": id, "name": name, "bytes": len(content.encode())},
        )
        return {"id": id, "name": name}

    def snapshot(self, thread=None):
        result = {
            "projects": self.rows("SELECT * FROM projects ORDER BY created DESC"),
            "threads": self.rows("SELECT * FROM threads ORDER BY created DESC"),
        }
        if thread:
            self.thread(thread)
            result.update(
                messages=self.rows(
                    "SELECT * FROM messages WHERE thread=? ORDER BY created,rowid",
                    (thread,),
                ),
                files=self.rows(
                    "SELECT id,name,length(CAST(content AS BLOB)) AS size FROM files WHERE thread=? ORDER BY created DESC",
                    (thread,),
                ),
            )
            with self.lock:
                run = next(
                    (
                        r
                        for r in self.runs.values()
                        if r.thread == thread and r.status in ("running", "approval")
                    ),
                    None,
                )
                result["run"] = self.run_state(run) if run else None
        return result

    def run_state(self, r):
        with r.lock:
            return {
                "id": r.id,
                "thread": r.thread,
                "status": r.status,
                "detail": r.detail,
                "pending": r.pending,
            }

    def tool(self, thread, name, args, approved=False):
        self.thread(thread)
        if not isinstance(args, dict):
            raise ValueError("Invalid tool arguments.")
        if name == "list_files":
            return self.rows("SELECT id,name FROM files WHERE thread=?", (thread,))
        if name == "read_file":
            f = self.file(thread, text(args.get("id"), 40))
            return {
                "name": f["name"],
                "content": f["content"][:12000],
                "truncated": len(f["content"]) > 12000,
            }
        if name == "search_files":
            q = text(args.get("query"), 200)
            matches = []
            for f in self.rows("SELECT id,name,content FROM files WHERE thread=?", (thread,)):
                i = f["content"].casefold().find(q.casefold())
                if i >= 0:
                    matches.append(
                        {
                            "id": f["id"],
                            "name": f["name"],
                            "excerpt": f["content"][max(0, i - 100) : i + 500],
                        }
                    )
                if len(matches) >= 10:
                    break
            return matches
        if name == "csv_summary":
            f = self.file(thread, text(args.get("id"), 40))
            reader = csv.DictReader(io.StringIO(f["content"]))
            if not reader.fieldnames:
                raise ValueError("CSV needs a header row.")
            totals = {}
            counts = {}
            rows = 0
            for row in reader:
                rows += 1
                for k, v in row.items():
                    if k is None or not isinstance(v, str) or not v.strip():
                        continue
                    try:
                        n = float(v)
                    except ValueError:
                        continue
                    if math.isfinite(n):
                        totals[k] = totals.get(k, 0) + n
                        counts[k] = counts.get(k, 0) + 1
            return {
                "rows": rows,
                "columns": reader.fieldnames,
                "numeric_totals": totals,
                "numeric_cell_counts": counts,
                "note": "Only plain numeric cells are summed; blank/text/currency-formatted cells are excluded.",
            }
        if name == "create_file":
            if not approved:
                raise ValueError("User approval is required before saving.")
            return self.save(thread, args.get("name"), args.get("content"))
        if name == "update_plan":
            steps = args.get("steps")
            if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
                raise ValueError("Plan requires 1–12 steps.")
            return {"steps": [text(s, 300) for s in steps]}
        raise ValueError("This tool is not allowed.")

    def start(self, thread, prompt, model, agent=True):
        self.thread(thread)
        prompt = text(prompt, 12000)
        model = text(model, 120)
        with self.lock:
            if any(r.status in ("running", "approval") for r in self.runs.values()):
                raise ValueError("Finish or stop the current run first.")
            # Retain completed results only up to a bounded count; messages/audit remain on disk.
            if len(self.runs) > 100:
                self.runs = {
                    k: r for k, r in self.runs.items() if r.status in ("running", "approval")
                }
            self.message(thread, "user", prompt)
            r = Run(ident(), thread, model)
            self.runs[r.id] = r
        threading.Thread(target=self.run, args=(r, agent), daemon=True).start()
        return self.run_state(r)

    def decide(self, id, approval_id, approve):
        r = self.runs.get(id)
        if not r:
            raise ValueError("Run not found.")
        with r.lock:
            if (
                r.status != "approval"
                or not r.pending
                or r.pending["id"] != approval_id
                or r.decision.is_set()
            ):
                raise ValueError("Approval is no longer pending.")
            r.approved = approve is True
            r.decision.set()
            self.log(
                r.thread,
                "approval_granted" if r.approved else "approval_denied",
                {"approval": approval_id, "name": r.pending["name"]},
            )

    def stop(self, id):
        r = self.runs.get(id)
        if not r:
            raise ValueError("Run not found.")
        r.cancel.set()
        r.decision.set()
        with r.lock:
            r.detail = "Stopping after the current local inference request…"

    def run(self, r, agent):
        try:
            caps = self.ollama.validate(r.model)
            if agent and caps and "tools" not in caps:
                raise ValueError(
                    "This model does not advertise tool support. Select Qwen or use Chat mode."
                )
            t = self.thread(r.thread)
            instructions = ""
            if t["project"]:
                p = self.rows("SELECT instructions FROM projects WHERE id=?", (t["project"],))
                instructions = p[0]["instructions"] if p else ""
            history = self.rows(
                "SELECT role,content FROM messages WHERE thread=? AND role IN ('user','assistant') ORDER BY created,rowid",
                (r.thread,),
            )
            chosen = []
            chars = len(SYSTEM) + len(instructions)
            for m in reversed(history):
                if chars + len(m["content"]) > MAX_CONTEXT_CHARS:
                    break
                chosen.append(m)
                chars += len(m["content"])
            if not chosen:
                raise ValueError("Your prompt is too long for this local configuration.")
            messages = [
                {
                    "role": "system",
                    "content": SYSTEM + "\nProject context: " + instructions,
                }
            ] + list(reversed(chosen))
            for step in range(8):
                if r.cancel.is_set():
                    break
                with r.lock:
                    r.status = "running"
                    r.detail = f"Local model working · step {step + 1}/8"
                result = self.ollama.chat(r.model, messages, agent)
                msg = result.get("message", {})
                if r.cancel.is_set():
                    break
                if not isinstance(msg, dict):
                    raise ValueError("The model returned an invalid message.")
                calls = msg.get("tool_calls") or []
                if not calls:
                    answer = msg.get("content", "").strip()
                    if not answer:
                        raise ValueError(
                            "The model returned no answer. Try a different local model."
                        )
                    self.message(r.thread, "assistant", answer)
                    with r.lock:
                        r.status = "complete"
                        r.detail = "Finished locally."
                    return
                if not agent:
                    raise ValueError("Tool use is disabled in Chat mode.")
                if len(calls) > 8:
                    raise ValueError("The model requested too many actions at once.")
                messages.append(msg)
                for call in calls:
                    if r.cancel.is_set():
                        break
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})
                    approved = False
                    try:
                        if isinstance(args, str):
                            args = json.loads(args)
                        if not isinstance(args, dict):
                            raise ValueError("Invalid arguments.")
                        if name == "create_file":
                            safe_name(args.get("name"))
                            if (
                                not isinstance(args.get("content"), str)
                                or len(args["content"].encode()) > MAX_FILE
                            ):
                                raise ValueError("Proposed output is too large.")
                            with r.lock:
                                r.decision.clear()
                                r.approved = False
                                r.pending = {
                                    "id": ident(),
                                    "name": args["name"],
                                    "content": args["content"],
                                }
                                r.status = "approval"
                                r.detail = "Review the proposed file before saving."
                            r.decision.wait(300)
                            with r.lock:
                                approved = r.approved and not r.cancel.is_set()
                                r.pending = None
                                r.status = "running"
                            if not approved:
                                output = {
                                    "error": "User did not approve this file. Do not retry the same write unless asked."
                                }
                            else:
                                output = self.tool(r.thread, name, args, approved=True)
                        else:
                            output = self.tool(r.thread, name, args)
                    except (ValueError, TypeError, KeyError) as e:
                        output = {"error": str(e)}
                    if r.cancel.is_set():
                        break
                    self.log(
                        r.thread,
                        "tool_result",
                        {
                            "tool": name,
                            "ok": not (isinstance(output, dict) and "error" in output),
                        },
                    )
                    activity = {
                        "tool": name,
                        "result": (
                            output
                            if name in ("update_plan", "create_file", "csv_summary")
                            else {
                                "message": (
                                    "Action completed"
                                    if not (isinstance(output, dict) and "error" in output)
                                    else output["error"]
                                )
                            }
                        ),
                    }
                    self.message(r.thread, "activity", json.dumps(activity))
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": name,
                            "content": json.dumps(output),
                        }
                    )
                if sum(len(json.dumps(m)) for m in messages) > 60000:
                    raise ValueError(
                        "Task context reached the local limit. Start a smaller task; saved work is preserved."
                    )
            with r.lock:
                r.status = "stopped" if r.cancel.is_set() else "limited"
                r.detail = (
                    "Stopped. Saved work is preserved."
                    if r.cancel.is_set()
                    else "Eight-step limit reached. Send a follow-up to continue."
                )
        except Exception as e:
            with r.lock:
                r.status = "error"
                r.detail = str(e)[:400]
            self.log(r.thread, "run_error", {"message": str(e)[:400]})
        finally:
            with r.lock:
                r.pending = None
            self.log(r.thread, "run_finished", {"status": r.status, "model": r.model})
