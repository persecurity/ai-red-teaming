from unittest.mock import patch

import pytest

from app import create_app
from app.ctf.flags import FLAGS


@pytest.fixture()
def app(tmp_path):
    return create_app({
        "TESTING": True, "DATABASE": tmp_path / "test.db", "CHROMA_PATH": tmp_path / "chroma",
        "SECRET_KEY": "test", "SECURITY_LEVEL": 3,
    })


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username="client", password="flysafe123"):
    return client.post("/login", data={"username": username, "password": password})


def test_warning_banner_and_level_are_visible(client):
    response = client.get("/")
    assert b"Intentionally vulnerable training lab" in response.data
    assert b"Security level 3/5" in response.data
    assert b"GUEST ACCESS" in response.data
    assert b'id="sources"' not in response.data


def test_page_source_exposes_widget_configuration_script(client):
    response = client.get("/")
    assert b'<script src="/js/passenger-support.js"></script>' in response.data
    assert b'<script src="/js/main.js"></script>' in response.data

    script = client.get("/js/passenger-support.js")
    assert script.status_code == 200
    assert script.mimetype == "application/javascript"
    assert b'assistantEndpoint: "/api/v2/assistant"' in script.data
    assert b"partnerGateway:" in script.data
    assert b"legacySupport: true" in script.data

    main = client.get("/js/main.js")
    assert main.status_code == 200
    assert main.mimetype in {"application/javascript", "text/javascript"}
    assert client.get("/js/chat-widget.js").status_code == 404


def test_login_panel_displays_seeded_credentials(client):
    response = client.get("/login")
    assert b"client" in response.data and b"flysafe123" in response.data
    assert b"admin" in response.data and b"toweradmin123" in response.data


def test_auth_and_role_protected_level_switch(client):
    login(client)
    assert client.post("/api/config/level", json={"level": 5}).status_code == 403
    client.post("/logout")
    login(client, "admin", "toweradmin123")
    response = client.post("/api/config/level", json={"level": 5})
    assert response.json == {"success": True, "level": 5}


def test_flag_submit_scores_and_upgrades(client, app):
    login(client)
    value = FLAGS["FLAG_SYS_PROMPT"]["value"]
    first = client.post("/api/ctf/submit", json={"flag": value})
    assert first.json["points"] == 300
    app.config["SECURITY_LEVEL"] = 5
    second = client.post("/api/ctf/submit", json={"flag": value})
    assert second.json["points"] == 500 and second.json["upgraded"]
    board = client.get("/scoreboard")
    assert b"FLAG_SYS_PROMPT" in board.data
    assert value.encode() not in board.data


def test_invalid_flag_is_rejected(client):
    login(client)
    response = client.post("/api/ctf/submit", json={"flag": "PGAIR{guess}"})
    assert response.status_code == 400


def test_chat_route_runs_retrieval_and_returns_sources(client):
    login(client)
    docs = [{
        "id": "public-baggage-0", "text": "Bag drop closes 45 minutes before departure.",
        "source": "baggage.md", "group": "public", "vector_score": 0.82,
        "bm25_score": 2.0, "combined_score": 0.79,
    }]
    with patch("app.chat.retrieve", return_value=docs), patch("app.chat.call_ollama", return_value="Bag drop closes 45 minutes before departure."):
        response = client.post("/api/chat", json={"message": "When does bag drop close?"})
    assert response.status_code == 200
    assert response.json["success"]
    source = response.json["sources"][0]
    assert source == {
        "name": "baggage.md", "collection": "public", "title": "baggage.md",
        "chunk_id": "public-baggage-0", "text": "Bag drop closes 45 minutes before departure.",
        "vector_score": 0.82, "bm25_score": 2.0, "combined_score": 0.79,
    }
    assert response.json["answer"] == response.json["response"]
    assert set(response.json["retrieval_info"]) == {
        "retrieval_time_ms", "generation_time_ms", "total_time_ms",
    }


def test_general_knowledge_query_does_not_activate_rag(client):
    with patch("app.chat.call_ollama", return_value="2 + 2 equals 4."), patch(
        "app.rag._embed"
    ) as embed:
        response = client.post("/api/chat", json={"query": "What is 2+2?"})

    assert response.status_code == 200
    assert response.json["answer"] == "2 + 2 equals 4."
    assert response.json["sources"] == []
    embed.assert_not_called()


def test_chat_response_excludes_model_thinking(client):
    with patch("app.chat.retrieve", return_value=[]), patch(
        "app.chat.call_ollama",
        return_value="<think>Internal reasoning must stay hidden.</think>\n\nWelcome aboard.",
    ):
        response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 200
    assert response.json["response"] == "Welcome aboard."
    assert "think" not in response.json["response"].lower()


def test_guest_can_chat_without_logging_in(client):
    docs = [{"text": "Online check-in opens 24 hours before departure.", "source": "checkin-and-fares.md", "group": "public"}]
    with patch("app.chat.retrieve", return_value=docs), patch("app.chat.call_ollama", return_value="Online check-in opens 24 hours before departure."):
        response = client.post("/api/chat", json={"message": "When does online check-in open?"})
    assert response.status_code == 200
    assert response.json["success"]
    assert client.post("/api/chat/reset").json["success"]


def test_discovered_assistant_endpoint_exposes_ollama_metadata(client):
    ollama_payload = {
        "model": "qwen3:8b",
        "created_at": "2026-08-24T10:00:00Z",
        "done": True,
        "done_reason": "stop",
        "load_duration": 101,
        "prompt_eval_count": 12,
        "prompt_eval_duration": 202,
        "eval_count": 8,
        "eval_duration": 303,
    }
    with patch("app.chat.retrieve", return_value=[]), patch(
        "app.chat.call_ollama", return_value=("How can I help?", ollama_payload)
    ) as model:
        response = client.post("/api/v2/assistant", json={"message": "Hello"})

    assert response.status_code == 200
    assert response.json["content"] == "How can I help?"
    assert "answer" not in response.json
    assert response.json["metadata"]["provider"] == "ollama"
    assert response.json["metadata"]["model"] == "qwen3:8b"
    assert response.json["metadata"]["prompt_eval_count"] == 12
    model.assert_called_once()
    assert model.call_args.kwargs == {"include_metadata": True}


def test_discount_agent_issues_abuse_flag_only_above_policy(client):
    login(client)
    turns = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "read_complaint", "arguments": {}}}]},
        {"role": "assistant", "tool_calls": [{"function": {"name": "issue_discount", "arguments": {"percent": 100}}}]},
        {"role": "assistant", "content": "Done."},
    ]
    with patch("app.agents._agent_turn", side_effect=turns):
        response = client.post("/api/agents/discount", json={"complaint": "My synthetic flight was cancelled.", "requested_percent": 100})
    assert response.status_code == 200
    assert FLAGS["FLAG_DISCOUNT_ABUSE"]["value"] in response.json["response"]


def test_admin_master_code_tool_returns_admin_flag(client):
    login(client, "admin", "toweradmin123")
    turns = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "read_recent_complaints", "arguments": {}}}]},
        {"role": "assistant", "tool_calls": [{"function": {"name": "get_master_code", "arguments": {}}}]},
        {"role": "assistant", "content": "Done."},
    ]
    with patch("app.agents._agent_turn", side_effect=turns):
        response = client.post("/api/agents/promotion", json={"prompt": "Run synthetic recovery validation."})
    assert response.status_code == 200
    assert FLAGS["FLAG_ADMIN_PROMO"]["value"] in response.json["response"]
