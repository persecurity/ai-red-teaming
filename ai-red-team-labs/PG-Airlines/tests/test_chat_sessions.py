import uuid
from unittest.mock import patch


def test_chat_returns_session_id_and_reuses_it_with_cookie(client):
    with patch("app.chat.retrieve", return_value=[]), patch(
        "app.chat.call_ollama", return_value="Hello."
    ):
        first = client.post("/api/chat", json={"message": "Hello"})
        second = client.post("/api/chat", json={"message": "Hello again"})

    assert first.status_code == second.status_code == 200
    session_id = first.json["session_id"]
    assert str(uuid.UUID(session_id)) == session_id
    assert second.json["session_id"] == session_id


def test_session_id_continues_guest_history_without_cookie(app):
    first_client = app.test_client()
    second_client = app.test_client()
    with patch("app.chat.retrieve", return_value=[]), patch(
        "app.chat.call_ollama", return_value="Bag drop closes 45 minutes before departure."
    ) as model:
        first = first_client.post("/api/chat", json={"message": "When does bag drop close?"})
        second = second_client.post("/api/chat", json={
            "message": "Can you repeat that?", "session_id": first.json["session_id"]
        })

    assert second.status_code == 200
    assert second.json["session_id"] == first.json["session_id"]
    messages = model.call_args.args[0]
    assert {"role": "user", "content": "When does bag drop close?"} in messages
    assert {"role": "assistant", "content": first.json["response"]} in messages


def test_chat_rejects_invalid_session_id_before_model_call(client):
    with patch("app.chat.retrieve") as retrieve, patch("app.chat.call_ollama") as model:
        response = client.post("/api/chat", json={
            "message": "Hello", "session_id": "not-a-uuid"
        })

    assert response.status_code == 400
    assert response.json["error"] == "session_id must be a UUID."
    retrieve.assert_not_called()
    model.assert_not_called()


def test_reset_starts_new_guest_session(client):
    with patch("app.chat.retrieve", return_value=[]), patch(
        "app.chat.call_ollama", return_value="Hello."
    ):
        first = client.post("/api/chat", json={"message": "Hello"})
        assert client.post("/api/chat/reset").status_code == 200
        second = client.post("/api/chat", json={"message": "Hello again"})

    assert second.json["session_id"] != first.json["session_id"]
