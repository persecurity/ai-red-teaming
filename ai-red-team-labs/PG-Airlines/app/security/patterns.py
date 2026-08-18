import logging
import re

from .prompts import REFUSAL


logger = logging.getLogger(__name__)

JAILBREAK_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
    r"forget\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
    r"act\s+as\s+(if\s+you\s+are\s+)?a\s+(different|new|other)",
    r"pretend\s+(you\s+are|to\s+be)\s+(a\s+)?(different|unrestricted|unfiltered)",
    r"roleplay\s+as", r"simulate\s+(being\s+)?a\s+(different|unrestricted)",
    r"\bdan\b", r"do\s+anything\s+now",
    r"ignore\s+your\s+(programming|guidelines|restrictions)",
    r"break\s+(free|out)\s+(of|from)\s+your\s+(constraints|limitations)",
    r"new\s+instructions?:", r"system\s+(override|prompt|message):",
    r"developer\s+mode", r"admin\s+mode",
    r"show\s+me\s+your\s+(instructions?|prompt|system\s+message)",
    r"what\s+(are\s+)?your\s+(instructions?|guidelines|rules)",
    r"reveal\s+your\s+(prompt|system\s+message)",
    r"output\s+in\s+code\s+block", r"respond\s+only\s+with", r"answer\s+as\s+if",
    r"</system>", r"<system>", r"\[system\]", r"\[/system\]",
]
SUSPICIOUS_PHRASES = [
    "break character", "exit character", "ignore safety", "override safety",
    "without restrictions", "unfiltered response", "uncensored", "jailbreak", "prompt injection",
]


def check_prompt_injection_patterns(text):
    lowered = text.lower()
    for pattern in JAILBREAK_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            logger.warning("Pattern filter blocked input; matched %s", pattern)
            return None, REFUSAL
    for phrase in SUSPICIOUS_PHRASES:
        if phrase in lowered:
            logger.warning("Pattern filter blocked input; suspicious phrase %s", phrase)
            return None, REFUSAL
    return text, None

