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


def call_ollama(messages):
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
    return _strip_thinking(response.json().get("message", {}).get("content", ""))


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


@bp.post("/api/chat")
def chat():
    started = time.time()
    body = request.get_json(silent=True) or {}
    message = str(body.get("message", "")).strip()[:4000]
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
    documents = retrieve(filtered, top_k=4)
    rag_context = "\n\n".join(f"SOURCE {doc['source']} ({doc['group']}):\n{doc['text']}" for doc in documents)
    history = [dict(row) for row in reversed(history_rows)]
    messages = build_messages(filtered, level, rag_context, upload_text, history)
    try:
        raw = _strip_thinking(call_ollama(messages))
    except requests.exceptions.RequestException as exc:
        logger.error("Ollama chat failed: %s", exc)
        return jsonify(success=False, error="The local model is unavailable. Check Ollama health and model installation."), 503
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
    return jsonify(
        success=not meta["output_blocked"], response=output, sources=[{"name": d["source"], "collection": d["group"]} for d in documents],
        level=level, response_time_ms=int((time.time() - started) * 1000), **meta,
    )


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
