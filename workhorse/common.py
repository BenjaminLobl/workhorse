"""Identifiers, timestamps and input validation shared by the local app."""

from __future__ import annotations

import time
import uuid


def now():
    return int(time.time() * 1000)


def ident():
    return uuid.uuid4().hex


def text(value, limit=10000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Enter text between 1 and {limit:,} characters.")
    return value.strip()


def safe_name(value):
    value = text(value, 120)
    if any(c in value for c in "\\/:\x00\r\n") or value in (".", ".."):
        raise ValueError("Use a filename, without folders or special path characters.")
    return value
