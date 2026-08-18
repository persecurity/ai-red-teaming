import logging
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required

from .config import Config, security_level
from .db import get_db, init_app as init_db


login_manager = LoginManager()
login_manager.login_view = "auth.login"


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    login_manager.init_app(app)
    init_db(app)

    from .auth import bp as auth_bp
    from .chat import bp as chat_bp
    from .uploads import bp as uploads_bp
    from .agents import bp as agents_bp
    from .ctf.scoring import bp as ctf_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(ctf_bp)

    @app.context_processor
    def globals_for_templates():
        return {"active_level": app.config["SECURITY_LEVEL"]}

    @app.get("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.get("/dashboard")
    @login_required
    def dashboard():
        complaints = []
        promotions = []
        if current_user.role == "client":
            complaints = get_db().execute(
                "SELECT * FROM complaints WHERE user_id=? ORDER BY id DESC", (current_user.id,)
            ).fetchall()
        else:
            complaints = get_db().execute(
                "SELECT * FROM complaints ORDER BY id DESC LIMIT 5"
            ).fetchall()
            promotions = get_db().execute("SELECT * FROM promotions ORDER BY id DESC").fetchall()
        return render_template("dashboard.html", complaints=complaints, promotions=promotions)

    @app.post("/api/config/level")
    @login_required
    def set_level():
        if current_user.role != "admin":
            return jsonify(error="Admin access required"), 403
        value = (request.get_json(silent=True) or request.form).get("level")
        try:
            level = int(value)
        except (TypeError, ValueError):
            return jsonify(error="Level must be an integer from 1 to 5"), 400
        if not 1 <= level <= 5:
            return jsonify(error="Level must be from 1 to 5"), 400
        app.config["SECURITY_LEVEL"] = security_level(level)
        return jsonify(success=True, level=level)

    @app.get("/health")
    def health():
        return jsonify(status="ok", level=app.config["SECURITY_LEVEL"])

    return app
