import logging
import requests
from flask import current_app

from ..observability import observation


logger = logging.getLogger(__name__)


def analyze_input_with_llama_guard(user_input):
    model = current_app.config["GUARD_MODEL"]
    model_parameters = {"temperature": 0.0, "num_predict": 20, "num_ctx": 2048}
    with observation(
        "classify-input-safety",
        as_type="generation",
        input=[{"role": "user", "content": user_input}],
        model=model,
        model_parameters=model_parameters,
        metadata={"provider": "ollama", "purpose": "input-guardrail"},
    ) as generation:
        try:
            response = requests.post(
                f"{current_app.config['OLLAMA_BASE_URL']}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": user_input}],
                    "stream": False,
                    "keep_alive": current_app.config["OLLAMA_KEEP_ALIVE"],
                    "options": model_parameters,
                },
                timeout=(5, 30),
            )
            if response.status_code != 200:
                logger.error("Llama Guard request failed: %s", response.status_code)
                generation.update(
                    output={"verdict": "unavailable"},
                    level="ERROR",
                    status_message=f"HTTP {response.status_code}",
                )
                return None, None, None
            payload = response.json()
            raw = payload.get("message", {}).get("content", "").strip()
            logger.info("Llama Guard raw response: %r", raw)
            generation.update(
                output=raw,
                model=payload.get("model", model),
                usage_details={
                    "input": payload.get("prompt_eval_count", 0),
                    "output": payload.get("eval_count", 0),
                },
            )
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
            generation.update(
                output={"verdict": "unavailable"},
                level="ERROR",
                status_message=str(exc),
            )
            return None, None, None
        except Exception as exc:
            logger.exception("Llama Guard error: %s", exc)
            generation.update(
                output={"verdict": "error"},
                level="ERROR",
                status_message=str(exc),
            )
            return None, None, None
