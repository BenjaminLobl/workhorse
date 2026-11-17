"""Persisted local model, generation and workplace preferences."""

import json

from .workplace import PROFILES

DEFAULTS = {
    "model": "qwen3.8:27b",
    "coding_model": "qwen3.8:27b",
    "design_model": "qwen3.8:27b",
    "vision_model": "gemma4:12b",
    "context": 16384,
    "output": 4096,
    "iterations": 24,
    "work_profile": "general",
    "progress_preview": True,
}
TOKEN_AND_ROUND_LIMITS = {
    "context": (4096, 32768),
    "output": (512, 8192),
    "iterations": (4, 40),
}


def validate_setting(key, value):
    if key in TOKEN_AND_ROUND_LIMITS:
        low, high = TOKEN_AND_ROUND_LIMITS[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Setting outside supported bounds.")
    elif key == "work_profile":
        if not isinstance(value, str) or value not in PROFILES:
            raise ValueError("Choose a supported workplace profile.")
    elif key == "progress_preview":
        if type(value) is not bool:
            raise ValueError("Progress preview must be true or false.")
    elif not isinstance(value, str) or len(value) > 120 or "cloud" in value.lower():
        raise ValueError("Choose a local model name.")


class ModelSettings:
    def settings(self):
        return DEFAULTS | {
            row["key"]: json.loads(row["value"]) for row in self.rows("SELECT * FROM config")
        }

    def set_settings(self, changes):
        for key in DEFAULTS:
            if key in changes:
                value = changes[key]
                validate_setting(key, value)
                self.write(
                    "INSERT OR REPLACE INTO config VALUES(?,?)", (key, json.dumps(value))
                )
        return self.settings()
