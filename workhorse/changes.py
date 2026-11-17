"""Bounded source snapshots for changes made by approved commands.

This supplements exact file-tool diffs. Dependencies, secrets, binaries and large
files are excluded; the tool result reports when the snapshot was incomplete.
"""

import os
from pathlib import Path

from .safety import sensitive


def capture(files):
    contents = {}
    used = 0
    truncated = False
    for base, dirs, names in os.walk(files.root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if not sensitive(Path(base, d).relative_to(files.root))
            and not Path(base, d).is_symlink()
        )
        for name in sorted(names):
            relative = Path(base, name).relative_to(files.root).as_posix()
            try:
                path = files.path(relative, True)
                size = path.stat().st_size
                if size > 500_000:
                    truncated = True
                    continue
                if len(contents) >= 2000 or used + size > 8_000_000:
                    return contents, True
                content = path.read_text(encoding="utf-8")
                if "\x00" in content:
                    continue
                contents[relative] = content
                used += size
            except (OSError, ValueError, UnicodeError):
                continue
    return contents, truncated


def record_command_changes(files, before, after, reason):
    previous, old_limit = before
    current, new_limit = after
    changes = []
    for path in sorted(previous.keys() | current.keys()):
        if path not in current:
            # A limit must never turn an unscanned file into a false deletion.
            try:
                if files.path(path).exists():
                    continue
            except (OSError, ValueError):
                continue
        old, new = previous.get(path, ""), current.get(path, "")
        if old != new:
            changes.append(files.change(path, old, new, reason))
        if len(changes) >= 100:
            new_limit = True
            break
    return {
        "changed_files": [c["path"] for c in changes],
        "change_tracking_limited": old_limit or new_limit,
    }
