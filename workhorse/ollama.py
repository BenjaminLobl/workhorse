"""HTTP client restricted to the local Ollama inference service."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .common import text
from .prompts import TOOL_SCHEMAS


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Ollama redirects are disabled.")


class Ollama:
    """Only the local Ollama service is reachable. Proxy env vars are ignored."""

    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, payload=None, timeout=180):
        if path not in ("/api/tags", "/api/show", "/api/chat", "/api/ps"):
            raise ValueError("Unsupported local endpoint.")
        body = None if payload is None else json.dumps(payload).encode()
        req = Request(
            "http://127.0.0.1:11434" + path,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=timeout) as r:
                raw = r.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Model response exceeded the size limit.")
                result = json.loads(raw)
                if result.get("error"):
                    raise ValueError(str(result["error"])[:300])
                return result
        except HTTPError as e:
            raise ValueError(
                f"Ollama returned HTTP {e.code}. Check that the selected model supports tools and is installed."
            ) from None
        except (URLError, TimeoutError, OSError):
            raise ValueError(
                "Cannot reach local Ollama, or inference timed out. Start Ollama and check the selected model fits your computer."
            ) from None

    def models(self):
        rows = self.request("/api/tags", timeout=8).get("models", [])
        return [r["name"] for r in rows if r.get("name") and not self.cloud(r)]

    @staticmethod
    def cloud(info):
        name = str(info.get("name", info.get("model", ""))).lower()
        return "cloud" in name or bool(info.get("remote_host") or info.get("remote_model"))

    def validate(self, model):
        model = text(model, 120)
        if model not in self.models():
            raise ValueError("Choose an installed local model. Cloud models are disabled.")
        details = self.request("/api/show", {"model": model}, timeout=15)
        if self.cloud(details):
            raise ValueError("Remote/cloud models are disabled.")
        return details.get("capabilities", [])

    def chat(self, model, messages, agent=True):
        return self.request(
            "/api/chat",
            {
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "tools": TOOL_SCHEMAS if agent else [],
                "options": {"num_ctx": 8192, "num_predict": 4096, "temperature": 0.2},
                "keep_alive": "5m",
            },
        )
