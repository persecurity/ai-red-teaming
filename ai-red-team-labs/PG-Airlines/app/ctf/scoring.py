from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user, login_required

from app.db import get_db
from .flags import FLAGS, validate_flag


bp = Blueprint("ctf", __name__)


@bp.post("/api/ctf/submit")
@login_required
def submit():
    flag_id, spec = validate_flag((request.get_json(silent=True) or request.form).get("flag"))
    if not flag_id:
        return jsonify(success=False, error="That flag is not valid."), 400
    level = current_app.config["SECURITY_LEVEL"]
    points = spec["points"] * level
    db = get_db()
    existing = db.execute(
        "SELECT * FROM captures WHERE player=? AND flag_id=?", (current_user.player_name, flag_id)
    ).fetchone()
    upgraded = False
    if existing is None:
        db.execute(
            "INSERT INTO captures(player,flag_id,level_at_capture,points) VALUES(?,?,?,?)",
            (current_user.player_name, flag_id, level, points),
        )
    elif points > existing["points"]:
        db.execute(
            "UPDATE captures SET level_at_capture=?,points=?,captured_at=CURRENT_TIMESTAMP WHERE id=?",
            (level, points, existing["id"]),
        )
        upgraded = True
    else:
        return jsonify(success=True, flag_id=flag_id, points=existing["points"], message="Already captured at this or a higher level.")
    db.commit()
    return jsonify(success=True, flag_id=flag_id, points=points, upgraded=upgraded)


@bp.get("/api/ctf/scoreboard")
@login_required
def scoreboard_data():
    rows = get_db().execute(
        "SELECT player,COUNT(*) captures,SUM(points) total_points,MAX(captured_at) last_capture FROM captures GROUP BY player ORDER BY total_points DESC"
    ).fetchall()
    return jsonify(players=[dict(row) for row in rows])


@bp.get("/scoreboard")
@login_required
def scoreboard():
    db = get_db()
    players = db.execute(
        "SELECT player,COUNT(*) captures,SUM(points) total_points,MAX(captured_at) last_capture FROM captures GROUP BY player ORDER BY total_points DESC"
    ).fetchall()
    own = db.execute(
        "SELECT flag_id,level_at_capture,points,captured_at FROM captures WHERE player=? ORDER BY captured_at DESC",
        (current_user.player_name,),
    ).fetchall()
    hints = {key: value["hint"] for key, value in FLAGS.items()}
    return render_template("scoreboard.html", players=players, own=own, hints=hints)
