"""Generate a local service secret once; never print it or embed it in launchers."""

from pathlib import Path
import secrets, os

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if not target.exists():
    target.write_text(
        "SEARXNG_SECRET=" + secrets.token_hex(32) + "\n", encoding="utf-8"
    )
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
print("Local service configuration ready.")
