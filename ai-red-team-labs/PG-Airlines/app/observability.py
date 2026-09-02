"""Langfuse tracing helpers with client-side redaction.

The application talks to Ollama over HTTP, so there is no framework integration
that can capture generations automatically.  These helpers keep the manual
instrumentation consistent and make tracing a no-op in tests or when disabled.
"""

import atexit
import logging
import os
import re
from contextlib import contextmanager
from functools import lru_cache

from flask import current_app, has_app_context
from langfuse import Langfuse, propagate_attributes
from langfuse.types import MaskOtelSpansResult, OtelSpanPatch


logger = logging.getLogger(__name__)


_SENSITIVE_PATTERNS = (
    (re.compile(r"\b(?:sk|pk)-lf-[A-Za-z0-9_-]+\b"), "[REDACTED_LANGFUSE_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bPGAIR\{[^}\r\n]+\}"), "[REDACTED_CTF_FLAG]"),
    (
        re.compile(
            r"(?:token|key|secret|password)\s*[:=]\s*[\"']?[A-Za-z0-9_.-]{12,}[\"']?",
            re.IGNORECASE,
        ),
        "[REDACTED_CREDENTIAL]",
    ),
    (
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "[REDACTED_EMAIL]",
    ),
    (
        re.compile(r"(?:postgres|postgresql|mysql|mongodb|redis)://[^\s\"']+"),
        "[REDACTED_CONNECTION]",
    ),
    (
        re.compile(
            r"\b(?!10\.)(?!127\.)(?!172\.(?:1[6-9]|2\d|3[01])\.)(?!192\.168\.)"
            r"(?:\d{1,3}\.){3}\d{1,3}\b"
        ),
        "[REDACTED_IP]",
    ),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (
        re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
        "[REDACTED_PHONE]",
    ),
    (
        re.compile(
            r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |OPENSSH )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
)


def _redact(value):
    if not isinstance(value, str):
        return value
    for pattern, replacement in _SENSITIVE_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _mask_otel_spans(*, params):
    """Redact sensitive strings from every span immediately before export."""
    patches = {}
    for identifier, span in params.spans.items():
        replacements = {}
        for key, value in span.attributes.items():
            if isinstance(value, str):
                masked = _redact(value)
            elif isinstance(value, (list, tuple)) and all(
                isinstance(item, str) for item in value
            ):
                masked_items = [_redact(item) for item in value]
                masked = tuple(masked_items) if isinstance(value, tuple) else masked_items
            else:
                continue
            if masked != value:
                replacements[key] = masked
        if replacements:
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)
    if not patches:
        return None
    return MaskOtelSpansResult(span_patches=patches)


def tracing_enabled():
    if has_app_context():
        if current_app.config.get("TESTING"):
            return False
        return bool(current_app.config.get("LANGFUSE_TRACING_ENABLED", True))
    return os.getenv("LANGFUSE_TRACING_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@lru_cache(maxsize=1)
def get_langfuse():
    """Return the process-wide Langfuse client after environment setup."""
    try:
        return Langfuse(
            tracing_enabled=tracing_enabled(),
            mask_otel_spans=_mask_otel_spans,
        )
    except Exception as exc:
        logger.warning("Langfuse initialization failed; tracing is disabled: %s", exc)
        return None


class _NoOpObservation:
    def update(self, **_kwargs):
        return self


@contextmanager
def observation(name, as_type="span", **attributes):
    """Create a correctly nested observation, or a cheap no-op when disabled."""
    if not tracing_enabled():
        yield _NoOpObservation()
        return
    client = get_langfuse()
    if client is None:
        yield _NoOpObservation()
        return
    with client.start_as_current_observation(
        name=name, as_type=as_type, **attributes
    ) as active_observation:
        yield active_observation


@contextmanager
def request_trace(
    *, name, input, user_id=None, session_id=None, tags=None, metadata=None, as_type="chain"
):
    """Create one root observation and propagate request-level dimensions."""
    if not tracing_enabled():
        yield _NoOpObservation()
        return

    client = get_langfuse()
    if client is None:
        yield _NoOpObservation()
        return
    with client.start_as_current_observation(
        name=name,
        as_type=as_type,
        input=input,
    ) as root:
        with propagate_attributes(
            user_id=user_id,
            session_id=session_id,
            tags=tags,
            metadata=metadata,
            trace_name=name,
        ):
            yield root


def shutdown_langfuse():
    """Flush the worker's queue on graceful process shutdown."""
    if get_langfuse.cache_info().currsize:
        try:
            client = get_langfuse()
            if client is not None:
                client.shutdown()
        except Exception as exc:  # tracing must never stop the training app
            logger.warning("Langfuse shutdown failed: %s", exc)


atexit.register(shutdown_langfuse)
