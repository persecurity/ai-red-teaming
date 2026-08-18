import logging
from flask import current_app

from .dlp import detect_and_redact_pii
from .judge import check_output_moderation
from .llama_guard import analyze_input_with_llama_guard
from .patterns import check_prompt_injection_patterns
from .prompts import REFUSAL


logger = logging.getLogger(__name__)


def apply_input_controls(text, level, is_upload=False):
    if level >= 3 and not is_upload:
        text, error = check_prompt_injection_patterns(text)
        if error:
            return None, error
    should_guard = level >= 4 and (not is_upload or current_app.config.get("SCAN_UPLOADS_WITH_GUARD", False))
    if should_guard:
        verdict, category, _error = analyze_input_with_llama_guard(text)
        if verdict == "unsafe":
            logger.warning("Llama Guard blocked input; category %s", category)
            return None, REFUSAL
        if verdict is None:
            logger.warning("Llama Guard unavailable; allowing input (fail-open)")
    return text, None


def apply_output_controls(response, level):
    meta = {"output_blocked": False, "pii_redacted": False}
    if level >= 5:
        response, error = check_output_moderation(response)
        if error:
            meta["output_blocked"] = True
            return error, meta
        response, found = detect_and_redact_pii(response)
        meta["pii_redacted"] = found
    return response, meta

