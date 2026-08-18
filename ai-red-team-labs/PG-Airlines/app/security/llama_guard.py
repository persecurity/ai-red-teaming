import logging
import requests
from flask import current_app


logger = logging.getLogger(__name__)


def analyze_input_with_llama_guard(user_input):
    try:
        response = requests.post(
            f"{current_app.config['OLLAMA_BASE_URL']}/api/chat",
            json={
                "model": current_app.config["GUARD_MODEL"],
                "messages": [{"role": "user", "content": user_input}],
                "stream": False,
                "keep_alive": current_app.config["OLLAMA_KEEP_ALIVE"],
                "options": {"temperature": 0.0, "num_predict": 20, "num_ctx": 2048},
            }, timeout=(5, 30),
        )
        if response.status_code != 200:
            logger.error("Llama Guard request failed: %s", response.status_code)
            return None, None, None
        raw = response.json().get("message", {}).get("content", "").strip()
        logger.info("Llama Guard raw response: %r", raw)
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            return None, None, None
        verdict = lines[0].lower()
        if verdict == "safe":
            return "safe", None, None
        if verdict == "unsafe":
            return "unsafe", lines[1] if len(lines) > 1 else "unknown", None
        return None, None, None
    except requests.exceptions.RequestException as exc:
        logger.error("Llama Guard unavailable: %s", exc)
        return None, None, None
    except Exception as exc:
        logger.exception("Llama Guard error: %s", exc)
        return None, None, None

