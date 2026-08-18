import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "DATABASE": tmp_path / "test.db",
            "CHROMA_PATH": tmp_path / "chroma",
            "SECRET_KEY": "test-secret",
            "SECURITY_LEVEL": 3,
        }
    )


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def login():
    def log_in(client, username="client", password="flysafe123"):
        return client.post(
            "/login",
            data={"username": username, "password": password},
        )

    return log_in
