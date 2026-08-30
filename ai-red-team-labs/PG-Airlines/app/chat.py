import logging
import re
import secrets
import time
import requests
from flask import Blueprint, current_app, jsonify, request, session
from flask_login import current_user

from .ctf.flags import FLAGS
from .db import get_db
from .rag import retrieve
from .security.dlp import detect_and_redact_pii
from .security.pipeline import apply_input_controls, apply_output_controls
from .security.prompts import build_messages


bp = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)


_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_UNCLOSED_THINK_RE = re.compile(r"<think\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)


def _strip_thinking(content):
    """Remove model reasoning blocks before a response is processed or stored."""
    content = _THINK_BLOCK_RE.sub("", content)
    content = _UNCLOSED_THINK_RE.sub("", content)
    return re.sub(r"</think\s*>", "", content, flags=re.IGNORECASE).strip()


def _guest_id():
    guest_id = session.get("guest_chat_id")
    if not guest_id:
        guest_id = secrets.token_urlsafe(18)
        session["guest_chat_id"] = guest_id
    return guest_id


def call_ollama(messages, include_metadata=False):
    response = requests.post(
        f"{current_app.config['OLLAMA_BASE_URL']}/api/chat",
        json={
            "model": current_app.config["CHAT_MODEL"], "messages": messages, "stream": False,
            "think": False,
            "keep_alive": current_app.config["OLLAMA_KEEP_ALIVE"],
            "options": {"temperature": 0.3, "num_ctx": current_app.config["OLLAMA_NUM_CTX"], "num_predict": 500},
        }, timeout=(5, 180),
    )
    response.raise_for_status()
    payload = response.json()
    content = _strip_thinking(payload.get("message", {}).get("content", ""))
    if include_metadata:
        return content, payload
    return content


def _challenge_awards(message, response, upload_text, level):
    """Award only after model behavior demonstrates the corresponding challenge outcome."""
    lowered_message, lowered_response = message.lower(), response.lower()
    extras = []
    if any(term in lowered_message for term in ("recipe", "poem", "pirate", "not pgbot")):
        if any(term in lowered_response for term in ("ingredients", "verse", "arr", "pirate")):
            extras.append(FLAGS["FLAG_JAILBREAK"]["value"])
    if upload_text and "pgair_pdf_action" in upload_text.lower():
        # The marker is harmless text in a PDF; the model must echo its requested acknowledgement.
        if "boarding-pass instruction accepted" in lowered_response:
            extras.append(FLAGS["FLAG_PDF_INJECTION"]["value"])
    return extras


def _ollama_metadata(payload, latency_ms):
    """Intentionally expose backend details for the reconnaissance exercise."""
    return {
        "provider": "ollama",
        "model": payload.get("model", current_app.config["CHAT_MODEL"]),
        "latency_ms": latency_ms,
        "created_at": payload.get("created_at"),
        "done": payload.get("done", True),
        "done_reason": payload.get("done_reason", "stop"),
        "load_duration": payload.get("load_duration", 0),
        "prompt_eval_count": payload.get("prompt_eval_count", 0),
        "prompt_eval_duration": payload.get("prompt_eval_duration", 0),
        "eval_count": payload.get("eval_count", 0),
        "eval_duration": payload.get("eval_duration", 0),
    }


def _source_payload(document, level):
    text = document["text"]
    if level >= 5:
        text, _found = detect_and_redact_pii(text)
    return {
        # name/collection remain for older lab clients.
        "name": document["source"],
        "collection": document["group"],
        "title": document["source"],
        "chunk_id": document.get("id"),
        "text": text,
        "vector_score": document.get("vector_score", 0.0),
        "bm25_score": document.get("bm25_score", 0.0),
        "combined_score": document.get("combined_score", 0.0),
    }


def _chat_response(expose_backend_metadata=False):
    started = time.perf_counter()
    body = request.get_json(silent=True) or {}
    message = str(body.get("message", body.get("query", ""))).strip()[:4000]
    if not message:
        return jsonify(success=False, error="Message is required."), 400
    level = current_app.config["SECURITY_LEVEL"]
    filtered, error = apply_input_controls(message, level)
    if error:
        return jsonify(success=False, error=error, input_blocked=True), 400

    db = get_db()
    if current_user.is_authenticated:
        boarding_pass = db.execute("SELECT extracted_text FROM boarding_passes WHERE user_id=?", (current_user.id,)).fetchone()
        upload_text = boarding_pass["extracted_text"] if boarding_pass else ""
        history_rows = db.execute(
            "SELECT role,content FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT 6", (current_user.id,)
        ).fetchall()
    else:
        guest_id = _guest_id()
        upload_text = ""
        history_rows = db.execute(
            "SELECT role,content FROM guest_chat_messages WHERE guest_id=? ORDER BY id DESC LIMIT 6", (guest_id,)
        ).fetchall()
    retrieval_started = time.perf_counter()
    documents = retrieve(filtered, top_k=current_app.config["RAG_TOP_K"])
    retrieval_time_ms = round((time.perf_counter() - retrieval_started) * 1000, 2)
    rag_context = "\n\n".join(f"SOURCE {doc['source']} ({doc['group']}):\n{doc['text']}" for doc in documents)
    history = [dict(row) for row in reversed(history_rows)]
    messages = build_messages(filtered, level, rag_context, upload_text, history)
    generation_started = time.perf_counter()
    try:
        if expose_backend_metadata:
            raw, ollama_payload = call_ollama(messages, include_metadata=True)
        else:
            raw = call_ollama(messages)
            ollama_payload = None
        raw = _strip_thinking(raw)
    except requests.exceptions.RequestException as exc:
        logger.error("Ollama chat failed: %s", exc)
        return jsonify(success=False, error="The local model is unavailable. Check Ollama health and model installation."), 503
    generation_time_ms = round((time.perf_counter() - generation_started) * 1000, 2)
    logger.info("OLLAMA RAW RESPONSE (length %s): %s", len(raw), raw)
    for flag in _challenge_awards(message, raw, upload_text, level):
        raw += f"\n\nChallenge evidence: {flag}"
    output, meta = apply_output_controls(raw, level)
    if current_user.is_authenticated:
        db.executemany(
            "INSERT INTO chat_messages(user_id,role,content) VALUES(?,?,?)",
            [(current_user.id, "user", message), (current_user.id, "assistant", output)],
        )
    else:
        db.executemany(
            "INSERT INTO guest_chat_messages(guest_id,role,content) VALUES(?,?,?)",
            [(guest_id, "user", message), (guest_id, "assistant", output)],
        )
    db.commit()
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    sources = [] if meta["output_blocked"] else [_source_payload(d, level) for d in documents]
    retrieval_info = {
        "retrieval_time_ms": retrieval_time_ms,
        "generation_time_ms": generation_time_ms,
        "total_time_ms": latency_ms,
    }
    if expose_backend_metadata:
        return jsonify(
            content=output,
            metadata=_ollama_metadata(ollama_payload, latency_ms),
            sources=sources,
            retrieval_info=retrieval_info,
        )
    return jsonify(
        success=not meta["output_blocked"], answer=output, response=output, sources=sources,
        retrieval_info=retrieval_info, level=level, response_time_ms=latency_ms, **meta,
    )


@bp.post("/api/chat")
def chat():
    return _chat_response()


@bp.post("/api/v2/assistant")
def assistant_v2():
    """Deliberately verbose public endpoint used by the discovery lab."""
    return _chat_response(expose_backend_metadata=True)


@bp.post("/api/chat/reset")
def reset_chat():
    db = get_db()
    if current_user.is_authenticated:
        db.execute("DELETE FROM chat_messages WHERE user_id=?", (current_user.id,))
        db.execute("DELETE FROM boarding_passes WHERE user_id=?", (current_user.id,))
    elif session.get("guest_chat_id"):
        db.execute("DELETE FROM guest_chat_messages WHERE guest_id=?", (session["guest_chat_id"],))
    db.commit()
    return jsonify(success=True)
