from __future__ import annotations

import difflib
import hashlib
import os
import re
import tempfile
from pathlib import Path

SKIP = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".ssh",
    ".aws",
    ".azure",
    ".gcloud",
}
SECRET_NAMES = {".env", ".npmrc", ".pypirc", "credentials", "id_rsa", "id_ed25519"}


def sensitive(path):
    p = Path(path)
    return any(
        x.lower() in SKIP
        or x.lower() in SECRET_NAMES
        or x.lower().startswith(".env.")
        or x.lower().endswith((".pem", ".key", ".p12", ".pfx"))
        for x in p.parts
    )


def redact(value, known=()):
    if isinstance(value, dict):
        return {
            k: (
                "[REDACTED]"
                if re.search(r"password|secret|api.?key|authorization|access.?token", k, re.I)
                else redact(v, known)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, known) for v in value]
    if not isinstance(value, str):
        return value
    for secret in known:
        if len(secret) >= 6:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(
        r"(?im)((?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]",
        value,
    )
    return re.sub(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b",
        "[REDACTED]",
        value,
    )


class Files:
    def __init__(self, root, record):
        self.root = Path(root).resolve(strict=True)
        self.record = record
        if not self.root.is_dir() or self.root == Path(self.root.anchor):
            raise ValueError("Choose a project directory, not a drive root.")

    def path(self, relative=".", exists=False):
        if (
            not isinstance(relative, str)
            or not relative
            or "\x00" in relative
            or ":" in relative
            or "\\" in relative
        ):
            raise ValueError("Use a relative path with forward slashes.")
        p = Path(relative)
        if p.is_absolute() or ".." in p.parts or sensitive(p):
            raise PermissionError("Path is outside the approved project or is protected.")
        target = self.root / p
        for item in [target, *target.parents]:
            if item == self.root:
                break
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise PermissionError("Symlinks and junctions are not allowed.")
        resolved = target.resolve(strict=exists)
        if not resolved.is_relative_to(self.root):
            raise PermissionError("Path escapes approved project.")
        if resolved.is_file() and resolved.stat().st_nlink > 1:
            raise PermissionError("Hard-linked files are not editable through workspace tools.")
        return resolved

    def list(self, path="."):
        root = self.path(path, True)
        out = []
        for p in sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            rel = p.relative_to(self.root).as_posix()
            if sensitive(rel) or p.is_symlink():
                continue
            out.append(
                {
                    "path": rel,
                    "type": "directory" if p.is_dir() else "file",
                    "bytes": p.stat().st_size if p.is_file() else None,
                }
            )
            if len(out) >= 300:
                break
        return {"entries": out, "limit": 300}

    def read(self, path, start=1, lines=200):
        p = self.path(path, True)
        if p.stat().st_size > 1_000_000:
            raise ValueError("File larger than 1 MB; use a smaller input.")
        content = p.read_text(encoding="utf-8")
        rows = content.splitlines()
        start = max(1, start)
        lines = min(300, lines)
        return {
            "path": path,
            "start": start,
            "total_lines": len(rows),
            "content": "\n".join(
                f"{i + 1}: {x}"
                for i, x in enumerate(rows)
                if start - 1 <= i < start - 1 + lines
            )[:18000],
            "excerpt_limit": 18000,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }

    def write(self, path, content, reason, expected_hash=None):
        p = self.path(path)
        if len(content.encode()) > 500_000:
            raise ValueError("Write is limited to 500 KB.")
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        if p.exists() and expected_hash != hashlib.sha256(old.encode()).hexdigest():
            raise ValueError(
                "Read the file first and pass its current sha256; refusing a stale overwrite."
            )
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".workhorse-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return self.change(path, old, content, reason)

    def edit(self, path, old, new, reason):
        p = self.path(path, True)
        content = p.read_text(encoding="utf-8")
        if not old or content.count(old) != 1:
            raise ValueError(
                "old_text must match exactly once. Read the relevant section again."
            )
        return self.write(
            path,
            content.replace(old, new, 1),
            reason,
            hashlib.sha256(content.encode()).hexdigest(),
        )

    def change(self, path, old, new, reason):
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), fromfile=path, tofile=path
            )
        )
        row = {
            "path": path,
            "reason": reason,
            "diff": redact(diff)[:40000],
            "added": sum(
                x.startswith("+") and not x.startswith("+++") for x in diff.splitlines()
            ),
            "removed": sum(
                x.startswith("-") and not x.startswith("---") for x in diff.splitlines()
            ),
        }
        self.record(row)
        return row

    def delete(self, path, reason):
        p = self.path(path, True)
        if not p.is_file():
            raise ValueError(
                "Only individual files can be deleted; directory deletion is blocked."
            )
        old = p.read_text(encoding="utf-8")
        p.unlink()
        return self.change(path, old, "", reason)

    def rename(self, path, destination, reason):
        p = self.path(path, True)
        q = self.path(destination)
        if not p.is_file() or q.exists():
            raise ValueError("Rename one file to a new, unused path.")
        q.parent.mkdir(parents=True, exist_ok=True)
        p.rename(q)
        row = {
            "path": path,
            "destination": destination,
            "reason": reason,
            "diff": "Renamed " + path + " → " + destination,
        }
        self.record(row)
        return row

    def search(self, query):
        matches = []
        scanned = 0
        for base, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = [
                d
                for d in dirs
                if not sensitive(Path(base, d).relative_to(self.root))
                and not Path(base, d).is_symlink()
            ]
            for name in names:
                scanned += 1
                if scanned > 5000:
                    return {"matches": matches, "truncated": True}
                rel = Path(base, name).relative_to(self.root).as_posix()
                try:
                    p = self.path(rel, True)
                    if p.stat().st_size > 500000:
                        continue
                    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
                        if query.casefold() in line.casefold():
                            matches.append(
                                {"path": rel, "line": i + 1, "text": redact(line[:500])}
                            )
                        if len(matches) >= 60:
                            return {"matches": matches, "truncated": True}
                except (OSError, UnicodeError, ValueError, PermissionError):
                    continue
        return {"matches": matches, "truncated": False}
