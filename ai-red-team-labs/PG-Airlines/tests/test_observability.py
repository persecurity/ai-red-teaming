from app.observability import _redact, tracing_enabled


def test_langfuse_export_redacts_credentials_pii_and_ctf_flags():
    value = (
        "keys pk-lf-publicexample123 and sk-lf-secretexample123; "
        "email pilot@example.com; flag PGAIR{do_not_export_me}; "
        "db postgresql://user:pass@db.example/airline; ip 203.0.113.42"
    )

    redacted = _redact(value)

    assert "pk-lf-publicexample123" not in redacted
    assert "sk-lf-secretexample123" not in redacted
    assert "pilot@example.com" not in redacted
    assert "PGAIR{do_not_export_me}" not in redacted
    assert "postgresql://user:pass@db.example/airline" not in redacted
    assert "203.0.113.42" not in redacted
    assert redacted.count("[REDACTED_LANGFUSE_KEY]") == 2
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_CTF_FLAG]" in redacted
    assert "[REDACTED_CONNECTION]" in redacted
    assert "[REDACTED_IP]" in redacted


def test_tracing_is_disabled_during_tests(app):
    with app.app_context():
        assert tracing_enabled() is False
