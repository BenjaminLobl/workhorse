#!/usr/bin/env python3
"""Start Workhorse on loopback. Its existing command-line flags remain supported."""

import argparse
import threading
import webbrowser
from pathlib import Path

# Kept for existing local scripts that import these names from server.
from workhorse.common import ident, now
from workhorse.http import ROOT, Server
from workhorse.ollama import Ollama
from workhorse.runtime import Workbench
from workhorse.workspace import Run, Workspace

__all__ = ["main", "ident", "now", "Server", "Ollama", "Run", "Workspace"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--no-browser", action="store_true")
    a = parser.parse_args()

    w = Workbench(a.data)
    try:
        s = Server(a.port, w)
    except OSError:
        raise SystemExit(
            "Workhorse could not start. Port in use? Close the previous instance or use --port 8766."
        )
    print(
        f"Workhorse Local: {s.origin}\nStorage: {w.data}\nLoopback-only evaluation build. Press Ctrl+C to stop.\n",
        flush=True,
    )
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(s.origin)).start()
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for r in list(w.runs.values()):
            r.cancel.set()
            r.decision.set()
        w.close()
        s.server_close()


if __name__ == "__main__":
    main()
