"""Service-level behaviour: the auth gate, and what a misconfigured service says."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.generation.client import NotConfigured
from app.main import app

client = TestClient(app)


@pytest.fixture
def token() -> str:
    return get_settings().service_token


def test_health_needs_no_token():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generation_is_closed_without_the_service_token():
    response = client.post("/v1/chapter-topics", json={"language": "python", "chapter_number": 1, "chapter_title": "Scope", "text": "body"})

    assert response.status_code == 401


def test_a_wrong_service_token_is_rejected():
    response = client.post(
        "/v1/chapter-topics", json={"language": "python", "chapter_number": 1, "chapter_title": "Scope", "text": "body"}, headers={"X-Service-Token": "guessed"}
    )

    assert response.status_code == 401


def test_missing_credentials_answer_with_a_readable_503(monkeypatch, token):
    """The SDK reports missing credentials as a bare TypeError raised while building
    the request headers, not at construction. An operator should get a sentence they
    can act on, not a stack trace."""

    class Messages:
        async def parse(self, **kwargs):
            raise TypeError(
                "Could not resolve authentication method. Expected one of api_key, "
                "auth_token, or credentials to be set."
            )

    class FakeClient:
        messages = Messages()

    monkeypatch.setattr("app.generation.client.get_client", lambda: FakeClient())

    response = client.post(
        "/v1/chapter-topics", json={"language": "python", "chapter_number": 1, "chapter_title": "Scope", "text": "body"}, headers={"X-Service-Token": token}
    )

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_an_unrelated_type_error_is_not_disguised_as_a_config_problem():
    """Matching on the message keeps a real bug visible instead of reporting it as
    missing credentials."""
    from app.generation.client import raise_for_credentials

    bug = TypeError("unsupported operand type(s) for +: 'int' and 'str'")

    with pytest.raises(TypeError) as raised:
        raise_for_credentials(bug)

    assert raised.value is bug
