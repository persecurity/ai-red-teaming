import logging
from flask import current_app

from ..observability import observation
from .dlp import detect_and_redact_pii
from .judge import check_output_moderation
from .llama_guard import analyze_input_with_llama_guard
from .patterns import check_prompt_injection_patterns
from .prompts import REFUSAL


logger = logging.getLogger(__name__)


def apply_input_controls(text, level, is_upload=False):
    with observation(
        "screen-input",
        as_type="guardrail",
        input={"text": text, "is_upload": is_upload},
        metadata={"security_level": level},
    ) as guardrail:
        if level >= 3 and not is_upload:
            text, error = check_prompt_injection_patterns(text)
            if error:
                guardrail.update(
                    output={"blocked": True, "control": "pattern-filter"},
                    level="WARNING",
                )
                return None, error
        should_guard = level >= 4 and (
            not is_upload or current_app.config.get("SCAN_UPLOADS_WITH_GUARD", False)
        )
        if should_guard:
            verdict, category, _error = analyze_input_with_llama_guard(text)
            if verdict == "unsafe":
                logger.warning("Llama Guard blocked input; category %s", category)
                guardrail.update(
                    output={"blocked": True, "verdict": verdict, "category": category},
                    level="WARNING",
                )
                return None, REFUSAL
            if verdict is None:
                logger.warning("Llama Guard unavailable; allowing input (fail-open)")
                guardrail.update(
                    output={"blocked": False, "verdict": "unavailable"},
                    level="WARNING",
                )
                return text, None
        guardrail.update(output={"blocked": False, "verdict": "safe"})
        return text, None


def apply_output_controls(response, level):
    with observation(
        "screen-output",
        as_type="guardrail",
        input={"response": response},
        metadata={"security_level": level},
    ) as guardrail:
        meta = {"output_blocked": False, "pii_redacted": False}
        if level >= 5:
            response, error = check_output_moderation(response)
            if error:
                meta["output_blocked"] = True
                guardrail.update(output={**meta, "response": error}, level="WARNING")
                return error, meta
            response, found = detect_and_redact_pii(response)
            meta["pii_redacted"] = found
        guardrail.update(output={**meta, "response": response})
        return response, meta
