"""Workhorse Control Centre: persistent preferences, approved project inventory, staged appearance.

All project inspection is read-only and limited to existing approved workspace roots.
Agent tools can propose a theme, but CANNOT apply it or modify Workhorse source.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from uuid import uuid4

from .safety import redact, sensitive

PALETTE = {
    "brand": "#365b38",
    "background": "#fafbf8",
    "surface": "#ffffff",
    "text": "#29312a",
    "radius": 12,
}
IGNORE = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    "build",
    "venv",
    ".turbo",
    ".idea",
    ".vscode",
}
MANIFESTS = {
    "package.json": "Node / JavaScript",
    "composer.json": "PHP / Composer",
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "Gemfile": "Ruby",
    "pom.xml": "Java",
    "index.html": "Static website",
    "vite.config.ts": "Vite / React",
    "artisan": "Laravel",
    "manage.py": "Django",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker",
}


def _contrast(a, b):
    def luminance(h):
        q = [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        q = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in q]
        return q[0] * 0.2126 + q[1] * 0.7152 + q[2] * 0.0722

    x, y = sorted((luminance(a), luminance(b)))
    return (y + 0.05) / (x + 0.05)


def clean_theme(obj):
    if not isinstance(obj, dict):
        raise ValueError("Theme must be an object.")
    out = {}
    for key in ("brand", "background", "surface", "text"):
        value = obj.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(f"{key} must be a six-digit hexadecimal colour.")
        out[key] = value.lower()
    radius = obj.get("radius")
    if type(radius) is not int or not 2 <= radius <= 24:
        raise ValueError("Border radius must be an integer from 2 to 24.")
    out["radius"] = radius
    if (
        min(
            _contrast(out["text"], out["background"]),
            _contrast(out["text"], out["surface"]),
        )
        < 4.5
    ):
        raise ValueError(
            "Text colour must meet a minimum 4.5:1 contrast ratio against backgrounds."
        )
    return out


class ControlCentre:
    def control_init(self):
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS cc_preferences(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS cc_projects(workspace TEXT NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL, stack TEXT NOT NULL, description TEXT NOT NULL, scanned INTEGER NOT NULL, PRIMARY KEY(workspace,path));
            CREATE TABLE IF NOT EXISTS cc_themes(id TEXT PRIMARY KEY, title TEXT NOT NULL, note TEXT NOT NULL, palette TEXT NOT NULL, status TEXT NOT NULL, created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS cc_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cc_theme_history(id TEXT PRIMARY KEY, palette TEXT NOT NULL, created INTEGER NOT NULL);
            """)

    def control_preferences(self):
        return {
            r["key"]: r["value"]
            for r in self.rows("SELECT key,value FROM cc_preferences ORDER BY key LIMIT 40")
        }

    def control_preference_prompt(self):
        values = self.control_preferences()
        if not values:
            return ""
        return (
            "\nPersistent user-approved response preferences (user may override per task): "
            + json.dumps(values, ensure_ascii=False)[:3200]
            + "\nOnly save a preference if the user explicitly asks you to remember or use it going forward. Do not store passwords, API keys or other secrets."
        )

    def control_set_preference(self, key, value):
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}", key):
            raise ValueError(
                "Preference key must be 2-40 lowercase characters, numbers, dash or underscore."
            )
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 600:
            raise ValueError("Preference text must contain 1-600 characters.")
        if redact(value) != value or re.search(
            r"(?i)password|private.key|bearer\s+\S+|api.?key|secret\s*[:=]",
            key + " " + value,
        ):
            raise ValueError("Do not store credentials or secrets in preferences.")
        if len(self.control_preferences()) >= 40 and key not in self.control_preferences():
            raise ValueError("Maximum 40 saved preferences.")
        self.write(
            "INSERT OR REPLACE INTO cc_preferences VALUES(?,?,?)",
            (key, value.strip(), int(time.time())),
        )
        return {"saved": key, "value": value.strip()}

    def control_delete_preference(self, key):
        if not isinstance(key, str):
            raise ValueError("Invalid preference key.")
        self.write("DELETE FROM cc_preferences WHERE key=?", (key,))
        return {"deleted": key}

    def control_theme(self):
        rows = self.rows("SELECT value FROM cc_meta WHERE key='theme'")
        return json.loads(rows[0]["value"]) if rows else PALETTE.copy()

    def control_propose_theme(self, title, note, palette):
        if not isinstance(title, str) or not 3 <= len(title.strip()) <= 80:
            raise ValueError("Title must be 3-80 characters.")
        if not isinstance(note, str) or len(note) > 800:
            raise ValueError("Note too long.")
        validated = clean_theme(palette)
        identifier = uuid4().hex
        self.write(
            "INSERT INTO cc_themes VALUES(?,?,?,?,?,?)",
            (
                identifier,
                title.strip(),
                note.strip(),
                json.dumps(validated),
                "pending",
                int(time.time()),
            ),
        )
        return {
            "proposal_id": identifier,
            "status": "pending",
            "message": "The user must inspect and approve this appearance change in Control Centre. No UI changes have been applied.",
        }

    def control_change_theme(self, proposal_id, action):
        if action not in ("apply_theme", "reject_theme", "rollback_theme"):
            raise ValueError("Unsupported theme action.")
        if action == "rollback_theme":
            past = self.rows(
                "SELECT * FROM cc_theme_history ORDER BY created DESC,rowid DESC LIMIT 1"
            )
            if not past:
                raise ValueError("There is no previous appearance to restore.")
            old = json.loads(past[0]["palette"])
            self.write("INSERT OR REPLACE INTO cc_meta VALUES('theme',?)", (json.dumps(old),))
            self.write("DELETE FROM cc_theme_history WHERE id=?", (past[0]["id"],))
            return {"theme": old, "restored": True}
        p = self.rows("SELECT * FROM cc_themes WHERE id=? AND status='pending'", (proposal_id,))
        if not p:
            raise ValueError("Pending proposal not found.")
        self.write(
            "UPDATE cc_themes SET status=? WHERE id=?",
            ("applied" if action == "apply_theme" else "rejected", proposal_id),
        )
        if action == "reject_theme":
            return {"rejected": proposal_id}
        current = self.control_theme()
        self.write(
            "INSERT INTO cc_theme_history VALUES(?,?,?)",
            (uuid4().hex, json.dumps(current), int(time.time())),
        )
        selected = json.loads(p[0]["palette"])
        self.write("INSERT OR REPLACE INTO cc_meta VALUES('theme',?)", (json.dumps(selected),))
        return {"theme": selected, "applied": proposal_id}

    def control_theme_css(self, preview=None):
        if preview is None and not self.rows("SELECT value FROM cc_meta WHERE key='theme'"):
            return ""
        p = clean_theme(preview or self.control_theme())
        # Only validated values from our strictly typed colour-token schema ever reach CSS.
        return (
            ":root {"
            + f"--green:{p['brand']};--workhorse-accent:{p['brand']};"
            + f"--workhorse-bg:{p['background']};--workhorse-surface:{p['surface']};"
            + f"--workhorse-fg:{p['text']};--workhorse-radius:{p['radius']}px;"
            + "} body {background:var(--workhorse-bg);color:var(--workhorse-fg)} "
            + "main,aside,.file-panel {background-color:var(--workhorse-bg)} "
            + "dialog,#composer,.suggestions button,.file,.car-card {border-radius:var(--workhorse-radius);}"
            + "a,.model-badge {accent-color:var(--workhorse-accent)} "
        )

    def control_scan_projects(self, workspace_id):
        w = self.workspace(workspace_id)
        root = Path(w["path"]).resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Approved workspace is not an ordinary directory.")
        results, seen = [], set()
        # Only the approved root and subdirectories at depth <= 2. Avoid recursive walks.
        dirs = [(root, 0)]
        while dirs and len(results) < 100:
            path, depth = dirs.pop(0)
            if path.is_symlink() or sensitive(path.relative_to(root)):
                continue
            try:
                entries = sorted(list(path.iterdir()), key=lambda e: e.name.lower())[:300]
            except (OSError, PermissionError):
                continue
            manifest_names = [
                p.name
                for p in entries
                if p.is_file() and not p.is_symlink() and p.name in MANIFESTS
            ]
            is_project = bool(manifest_names) or (
                depth == 1 and not any(e.is_dir() and not e.is_symlink() for e in entries)
            )
            if is_project:
                desc = ""
                for filename in ("README.md", "README.txt"):
                    readme = path / filename
                    if (
                        readme.is_file()
                        and not readme.is_symlink()
                        and readme.stat().st_size < 60000
                    ):
                        desc = " ".join(
                            readme.read_text(encoding="utf-8", errors="replace")[:650].split()
                        )[:260]
                        break
                relative = "." if path == root else path.relative_to(root).as_posix()
                if relative not in seen:
                    results.append(
                        {
                            "workspace_id": workspace_id,
                            "path": relative,
                            "name": path.name,
                            "stack": ", ".join(
                                dict.fromkeys(MANIFESTS[n] for n in manifest_names)
                            )
                            or "Unclassified",
                            "description": desc,
                        }
                    )
                    seen.add(relative)
            if depth < 2:
                children = [
                    p
                    for p in entries
                    if p.is_dir()
                    and not p.is_symlink()
                    and p.name not in IGNORE
                    and not sensitive(p.relative_to(root))
                ]
                dirs.extend((p, depth + 1) for p in children)
        self.write("DELETE FROM cc_projects WHERE workspace=?", (workspace_id,))
        for p in results:
            self.write(
                "INSERT INTO cc_projects VALUES(?,?,?,?,?,?)",
                (
                    workspace_id,
                    p["path"],
                    p["name"],
                    p["stack"],
                    p["description"],
                    int(time.time()),
                ),
            )
        return {
            "workspace": w["name"],
            "projects": results,
            "limit": 100,
            "note": "Only this approved directory and subfolders up to 2 levels deep were indexed. These are filesystem discoveries, not evidence of completed tasks.",
        }

    def control_snapshot(self):
        settings = self.settings()
        projects = [
            json.loads(r["detail"])
            for r in self.rows("SELECT detail FROM cc_project_evidence LIMIT 200")
        ]
        for p in projects:
            notes = self.rows(
                "SELECT note FROM cc_project_notes WHERE workspace=? AND path=?",
                (p["workspace"], p["path"]),
            )
            p["note"] = notes[0]["note"] if notes else ""
        themes = self.rows(
            "SELECT id,title,note,palette,status,created FROM cc_themes ORDER BY created DESC,rowid DESC LIMIT 30"
        )
        for theme in themes:
            theme["palette"] = json.loads(theme["palette"])
        spaces = self.rows(
            "SELECT id,name,path,permissions FROM workspaces ORDER BY created DESC"
        )
        for space in spaces:
            space["permissions"] = json.loads(space["permissions"])
        return {
            "preferences": self.control_preferences(),
            "scoped_preferences": self.rows("SELECT * FROM cc_scoped_preferences"),
            "theme": self.control_theme(),
            "theme_proposals": themes,
            "projects": projects,
            "workspaces": spaces,
            "runtime": self.runtime_facts(),
            "models": {
                k: settings[k]
                for k in (
                    "model",
                    "coding_model",
                    "design_model",
                    "vision_model",
                    "context",
                    "iterations",
                )
            },
            "scope": "Only approved workspaces. No access to the Workhorse installation as an agent development workspace.",
            "capabilities": {
                "persistent_preferences": True,
                "project_index": True,
                "appearance_proposals": True,
                "source_code_self_editing": False,
            },
        }

    def control_action(self, b):
        action = b.get("action")
        if action == "save_preference":
            return self.preference_change(
                b.get("key"), b.get("value"), b.get("workspace") or None
            )
        if action == "delete_preference":
            return self.preference_change(
                b.get("key"), workspace=b.get("workspace") or None, delete=True
            )
        if action == "project_note":
            self.workspace(b.get("workspace"))
            if not self.rows(
                "SELECT path FROM cc_projects WHERE workspace=? AND path=?",
                (b.get("workspace"), b.get("path")),
            ):
                raise ValueError("Indexed project not found.")
            note = b.get("note", "")
            if not isinstance(note, str) or len(note) > 1200 or redact(note) != note:
                raise ValueError("Use a note up to 1200 characters without credentials.")
            self.write(
                "INSERT OR REPLACE INTO cc_project_notes VALUES(?,?,?)",
                (b["workspace"], b["path"], note),
            )
            return {"saved": True}
        if action == "scan_projects":
            return self.control_scan_projects(b.get("workspace_id"))
        if action == "propose_theme":
            return self.control_propose_theme(
                b.get("title"), b.get("note", ""), b.get("palette")
            )
        if action in ("apply_theme", "reject_theme", "rollback_theme"):
            return self.control_change_theme(b.get("proposal_id"), action)
        raise ValueError("Unknown Control Centre action.")
