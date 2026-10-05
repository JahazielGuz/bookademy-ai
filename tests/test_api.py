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
    response = client.post("/v1/chapter-topics", json={
            "language": "python",
            "chapter_number": 1,
            "chapter_title": "Scope",
            "page_start": 1,
            "page_end": 4,
            "text": "body",
        })

    assert response.status_code == 401


def test_a_wrong_service_token_is_rejected():
    response = client.post(
        "/v1/chapter-topics", json={
            "language": "python",
            "chapter_number": 1,
            "chapter_title": "Scope",
            "page_start": 1,
            "page_end": 4,
            "text": "body",
        }, headers={"X-Service-Token": "guessed"}
    )

    assert response.status_code == 401


def test_missing_credentials_answer_with_a_readable_503(monkeypatch, token):
    """A misconfigured service should answer with a sentence an operator can act on,
    not a 500 and a stack trace."""

    from app.generation.client import NO_CREDENTIALS, NotConfigured

    def unconfigured():
        raise NotConfigured(NO_CREDENTIALS)

    monkeypatch.setattr("app.generation.client.get_client", unconfigured)

    response = client.post(
        "/v1/chapter-topics", json={
            "language": "python",
            "chapter_number": 1,
            "chapter_title": "Scope",
            "page_start": 1,
            "page_end": 4,
            "text": "body",
        }, headers={"X-Service-Token": token}
    )

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]
