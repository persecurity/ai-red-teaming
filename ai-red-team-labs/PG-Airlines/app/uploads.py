import io
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from pypdf import PdfReader

from .db import get_db
from .security.pipeline import apply_input_controls


bp = Blueprint("uploads", __name__)


@bp.post("/api/upload/boarding-pass")
@login_required
def upload_boarding_pass():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(success=False, error="Choose a PDF file."), 400
    if not uploaded.filename.lower().endswith(".pdf") or uploaded.mimetype not in {"application/pdf", "application/x-pdf"}:
        return jsonify(success=False, error="Only PDF boarding passes are accepted."), 400
    raw = uploaded.read()
    if len(raw) > current_app.config["MAX_CONTENT_LENGTH"]:
        return jsonify(success=False, error="File is too large."), 413
    try:
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)[:12000]
    except Exception:
        return jsonify(success=False, error="The PDF could not be parsed."), 400
    if not text.strip():
        return jsonify(success=False, error="No extractable text was found in the PDF."), 400
    checked, error = apply_input_controls(text, current_app.config["SECURITY_LEVEL"], is_upload=True)
    if error:
        return jsonify(success=False, error=error, input_blocked=True), 400
    filename = uploaded.filename[:120]
    db = get_db()
    db.execute(
        "INSERT INTO boarding_passes(user_id,filename,extracted_text) VALUES(?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET filename=excluded.filename,extracted_text=excluded.extracted_text,uploaded_at=CURRENT_TIMESTAMP",
        (current_user.id, filename, checked),
    )
    db.commit()
    return jsonify(success=True, filename=filename, characters=len(checked), guard_scanned=bool(current_app.config["SCAN_UPLOADS_WITH_GUARD"] and current_app.config["SECURITY_LEVEL"] >= 4))
