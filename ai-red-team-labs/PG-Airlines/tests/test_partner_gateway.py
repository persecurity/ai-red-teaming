from unittest.mock import Mock, patch

import pytest

from app.partner_gateway import create_gateway_app


@pytest.fixture()
def gateway_client():
    app = create_gateway_app(
        {
            "TESTING": True,
            "PARTNER_API_KEY": "test-partner-key",
            "UPSTREAM_ASSISTANT_URL": "http://app.test/api/v2/assistant",
        }
    )
    return app.test_client()


def test_gateway_headers_deliberately_expose_nginx_fingerprint(gateway_client):
    response = gateway_client.get("/v1/billing")

    assert response.status_code == 200
    assert response.headers["Server"] == "nginx/1.26.3"
    assert response.headers["X-Upstream-Response-Time"] == "0.010"
    assert response.headers["X-Request-Time"] == "0.037"
    assert "X-Kong-Upstream-Latency" not in response.headers
    assert "X-Kong-Proxy-Latency" not in response.headers
    assert "Via" not in response.headers


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/v1/auth", 200),
        ("/v1/billing", 200),
        ("/v1/chat/completions", 401),
        ("/v1/models", 404),
        ("/v1/users", 404),
    ],
)
def test_gateway_status_codes_enable_endpoint_enumeration(
    gateway_client, path, expected_status
):
    assert gateway_client.get(path).status_code == expected_status


def test_gateway_rejects_an_invalid_bearer_token(gateway_client):
    response = gateway_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer wrong"},
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 401
    assert response.get_data(as_text=True) == "Unauthorized\n"


def test_authorized_gateway_request_uses_openai_compatible_shape(gateway_client):
    upstream = Mock()
    upstream.raise_for_status.return_value = None
    upstream.json.return_value = {
        "content": "Welcome aboard.",
        "metadata": {"model": "qwen3:8b"},
    }
    with patch("app.partner_gateway.requests.post", return_value=upstream) as post:
        response = gateway_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-partner-key"},
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

    assert response.status_code == 200
    assert response.json["object"] == "chat.completion"
    assert response.json["model"] == "qwen3:8b"
    assert response.json["choices"][0]["message"]["content"] == "Welcome aboard."
    post.assert_called_once_with(
        "http://app.test/api/v2/assistant",
        json={"message": "Hello"},
        timeout=(5, 180),
    )
