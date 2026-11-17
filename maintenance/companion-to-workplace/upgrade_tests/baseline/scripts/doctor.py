"""Check local prerequisites. Add --search to actually query SearXNG."""

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Ollama
from workhorse.research import service

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--search", action="store_true")
parser.add_argument("--crawl4ai", action="store_true")
args = parser.parse_args()
failed = False
print("Python:", platform.python_version(), "| OS:", platform.system())
for name in ("docker", "node", "npm", "git", "pwsh", "powershell", "php", "composer"):
    print(
        name + ":", "available" if shutil.which(name) else "not installed / not on PATH"
    )
try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        print(
            "Chromium:",
            (
                "installed"
                if Path(p.chromium.executable_path).exists()
                else "missing; run python -m playwright install chromium"
            ),
        )
except ImportError:
    print("Playwright: missing; install requirements.txt")
    failed = True
try:
    models = Ollama().models()
    print("Local Ollama models:", ", ".join(models) or "none installed")
except Exception as e:
    print("Ollama check failed:", str(e))
    failed = True
if args.search:
    try:
        result = service(
            "http://127.0.0.1:8080/search?q=Open-Meteo+weather&format=json"
        )
        print("SearXNG results:", len(result.get("results", [])))
        print("Unresponsive engines:", len(result.get("unresponsive_engines", [])))
        if not result.get("results"):
            failed = True
    except Exception as e:
        print("SearXNG check failed:", type(e).__name__)
        failed = True
if args.crawl4ai:
    try:
        service("http://127.0.0.1:11235/health")
        print("Crawl4AI: reachable")
    except Exception as e:
        print("Crawl4AI check failed:", type(e).__name__)
        failed = True
sys.exit(1 if failed else 0)
