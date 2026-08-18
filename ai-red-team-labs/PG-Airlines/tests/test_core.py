from unittest.mock import patch

import pytest
import requests

from app.config import env_bool, security_level
from app.ctf.flags import FLAGS, validate_flag
from app.db import get_db
from app.security.judge import check_output_moderation
from app.security.llama_guard import analyze_input_with_llama_guard
from app.security.prompts import OUTPUT_REFUSAL, build_messages


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 1), ("bad", 1), (-4, 1), (1, 1), (3, 3), (99, 5)],
)
def test_security_level_is_always_between_one_and_five(monkeypatch, value, expected):
    monkeypatch.setenv("SECURITY_LEVEL", "1")
    assert security_level(value) == expected


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_env_bool_accepts_supported_true_values(monkeypatch, value):
    monkeypatch.setenv("FEATURE_ENABLED", value)
    assert env_bool("FEATURE_ENABLED") is True


def test_build_messages_keeps_only_safe_recent_history_and_limits_content():
    history = [
        {"role": "system", "content": "must not be copied"},
        *({"role": "user", "content": f"turn-{index}"} for index in range(7)),
        {"role": "tool", "content": "must not be copied"},
        {"role": "assistant", "content": "x" * 2500},
    ]

    messages = build_messages("Where is check-in?", 2, history=history)

    assert messages[0]["role"] == "system"
    assert all(item["role"] in {"system", "user", "assistant"} for item in messages)
    assert "must not be copied" not in str(messages)
    assert len(messages[-2]["content"]) == 2000
    assert messages[-1]["role"] == "user"
    assert "Stay in role and on topic" in messages[-1]["content"]


@pytest.mark.parametrize("flag_id", FLAGS)
def test_every_configured_flag_validates_exactly(flag_id):
    value = FLAGS[flag_id]["value"]
    assert validate_flag(f"  {value}\n")[0] == flag_id
    assert validate_flag(value + "x") == (None, None)


def test_output_judge_blocks_unsafe_content(app):
    with app.app_context(), patch(
        "app.security.judge.analyze_output_with_ai", return_value=("unsafe", None)
    ):
        assert check_output_moderation("secret response") == (None, OUTPUT_REFUSAL)


def test_output_judge_fails_open_when_no_verdict_is_available(app):
    with app.app_context(), patch(
        "app.security.judge.analyze_output_with_ai", return_value=(None, None)
    ):
        assert check_output_moderation("ordinary response") == ("ordinary response", None)


@pytest.mark.parametrize(
    ("model_text", "expected"),
    [("safe", ("safe", None, None)), ("unsafe\nS2", ("unsafe", "S2", None)), ("unexpected", (None, None, None))],
)
def test_llama_guard_parses_supported_verdicts(app, model_text, expected):
    response = type(
        "Response",
        (),
        {"status_code": 200, "json": lambda self: {"message": {"content": model_text}}},
    )()
    with app.app_context(), patch("app.security.llama_guard.requests.post", return_value=response):
        assert analyze_input_with_llama_guard("input") == expected


def test_llama_guard_fails_open_on_network_error(app):
    with app.app_context(), patch(
        "app.security.llama_guard.requests.post",
        side_effect=requests.ConnectionError("offline"),
    ):
        assert analyze_input_with_llama_guard("input") == (None, None, None)


def test_database_seeds_both_expected_roles(app):
    with app.app_context():
        users = get_db().execute(
            "SELECT username, role FROM users ORDER BY username"
        ).fetchall()
    assert [tuple(row) for row in users] == [("admin", "admin"), ("client", "client")]


def test_reset_db_command_clears_records_and_restores_seeded_accounts(app):
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO complaints(user_id,text,requested_percent) VALUES(?,?,?)",
            (1, "A delayed flight", 20),
        )
        db.execute(
            "INSERT INTO users(username,password_hash,role,player_name) VALUES(?,?,?,?)",
            ("extra", "unused", "client", "Extra Player"),
        )
        db.commit()

    result = app.test_cli_runner().invoke(args=["reset-db", "--yes"])

    assert result.exit_code == 0
    assert "Database reset complete." in result.output
    with app.app_context():
        db = get_db()
        users = db.execute(
            "SELECT username, role FROM users ORDER BY username"
        ).fetchall()
        complaint_count = db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    assert [tuple(row) for row in users] == [("admin", "admin"), ("client", "client")]
    assert complaint_count == 0
