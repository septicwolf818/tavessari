import json
import os
import urllib.request

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

class OllamaClient:
    """Minimal Ollama client using only stdlib urllib."""

    def __init__(self, host=OLLAMA_HOST):
        self.host = host

    def list_models(self, timeout=5):
        req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", []) if "name" in m]

    def generate(self, model, prompt, timeout=3600, check_cancelled=None):
        """Stream Ollama ``/api/generate`` line-by-line with instant cancellation.

        Each yielded line is NDJSON. We parse it and accumulate ``response`` fields
        until ``done` is true, or the user cancels.  Cancellation fires within one
        I/O timeout window (~2 s by default).
        """
        import time

        payload = json.dumps(
            {"model": model, "prompt": prompt, "stream": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        result_parts: list[str] = []
        start_time = time.time()
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            for line in resp:
                if (time.time() - start_time) > timeout:
                    raise InterruptedError("Timed out")

                if check_cancelled and check_cancelled():
                    raise InterruptedError("Cancelled by user")

                try:
                    obj = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if obj.get("done"):
                    return "".join(result_parts).strip()

                result_parts.append(obj.get("response", ""))

        raise InterruptedError("Timed out")
