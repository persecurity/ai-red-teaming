from dataclasses import dataclass
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import UserMixin, current_user, login_user, logout_user
from werkzeug.security import check_password_hash

from . import login_manager
from .db import get_db


bp = Blueprint("auth", __name__)


@dataclass
class User(UserMixin):
    id: int
    username: str
    role: str
    player_name: str


@login_manager.user_loader
def load_user(user_id):
    row = get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return User(row["id"], row["username"], row["role"], row["player_name"]) if row else None


@bp.route("/login", methods=("GET", "POST"))
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        row = get_db().execute("SELECT * FROM users WHERE username=?", (request.form.get("username", ""),)).fetchone()
        if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
            login_user(User(row["id"], row["username"], row["role"], row["player_name"]))
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))

