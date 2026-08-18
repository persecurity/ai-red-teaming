import logging
import re


logger = logging.getLogger(__name__)

PATTERNS = [
    ("openai_key", r"sk-[a-zA-Z0-9_-]{20,}", "[REDACTED_API_KEY]"),
    ("aws_key", r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]"),
    ("stripe_key", r"sk_live_[a-zA-Z0-9]{20,}", "[REDACTED_STRIPE_KEY]"),
    ("generic_token", r"(?:token|key|secret|password)\s*[:=]\s*[\"']?[a-zA-Z0-9_\-.]{20,}[\"']?", "[REDACTED_CREDENTIAL]"),
    ("email", r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[REDACTED_EMAIL]"),
    ("credit_card", r"\b(?:\d[ -]*?){13,16}\b", "[REDACTED_CARD]"),
    ("phone", r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", "[REDACTED_PHONE]"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
    ("public_ip", r"\b(?!10\.)(?!127\.)(?!172\.(?:1[6-9]|2\d|3[01])\.)(?!192\.168\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[REDACTED_IP]"),
    ("connection_string", r"(?:postgres|postgresql|mysql|mongodb|redis)://\S+", "[REDACTED_CONNECTION]"),
    ("private_key", r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |OPENSSH )?PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
    ("hex_secret", r"(?:secret|jwt|hmac)\s*[:=]\s*[\"']?[a-fA-F0-9]{32,}[\"']?", "[REDACTED_SECRET]"),
]


def detect_and_redact_pii(text):
    found = False
    for name, pattern, replacement in PATTERNS:
        flags = re.IGNORECASE | re.DOTALL if name == "private_key" else re.IGNORECASE
        matches = re.findall(pattern, text, flags)
        if name == "email":
            matches = [m for m in matches if m.lower() != "support@pg-airlines.local"]
            for match in matches:
                text = text.replace(match, replacement)
        elif matches:
            text = re.sub(pattern, replacement, text, flags=flags)
        if matches:
            found = True
            logger.warning("DLP redacted %s match(es) for %s", len(matches), name)
    return text, found

