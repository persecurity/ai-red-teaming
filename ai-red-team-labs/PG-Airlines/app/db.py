import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash


def get_db():
    if "db" not in g:
        current_app.config["DATABASE"].parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL, player_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS complaints (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, text TEXT NOT NULL,
          requested_percent INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'filed',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS promotions (
          id INTEGER PRIMARY KEY, flight_id TEXT NOT NULL, discount_percent INTEGER NOT NULL,
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS boarding_passes (
          user_id INTEGER PRIMARY KEY, filename TEXT NOT NULL, extracted_text TEXT NOT NULL,
          uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, role TEXT NOT NULL,
          content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS guest_chat_messages (
          id INTEGER PRIMARY KEY, guest_id TEXT NOT NULL, role TEXT NOT NULL,
          content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS captures (
          id INTEGER PRIMARY KEY, player TEXT NOT NULL, flag_id TEXT NOT NULL,
          level_at_capture INTEGER NOT NULL, points INTEGER NOT NULL,
          captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(player, flag_id)
        );
        """
    )
    for username, password, role, player in (
        ("client", "flysafe123", "client", "Client Player"),
        ("admin", "toweradmin123", "admin", "Admin Player"),
    ):
        db.execute(
            "INSERT OR IGNORE INTO users(username,password_hash,role,player_name) VALUES(?,?,?,?)",
            (username, generate_password_hash(password), role, player),
        )
    db.commit()


def reset_db():
    """Remove all application data and restore the initial database state."""
    db = get_db()
    tables = db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for table in tables:
        name = table[0].replace('"', '""')
        db.execute(f'DROP TABLE "{name}"')
    db.commit()
    init_db()


@click.command("reset-db")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@with_appcontext
def reset_db_command(yes):
    """Clear the database and restore its seeded accounts."""
    if not yes:
        click.confirm(
            "This will permanently delete all PG-Airlines database records. Continue?",
            abort=True,
        )
    reset_db()
    click.echo("Database reset complete.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(reset_db_command)
    with app.app_context():
        init_db()
