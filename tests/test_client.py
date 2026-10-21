"""The model client: what it sends, what it makes of what comes back, and the cut it
makes so a chapter fits the window. The server is faked; nothing here needs a model."""

import asyncio
from types import SimpleNamespace

import pytest
from openai import LengthFinishReasonError
from pydantic import BaseModel

from app.config import Settings
from app.generation import client as client_module
from app.generation.client import (
    CHARS_PER_TOKEN,
    OVERHEAD_TOKENS,
    NotConfigured,
    Refused,
    Truncated,
    fit_to_window,
    get_client,
    parse_structured,
)


class Answer(BaseModel):
    text: str


def completion(*, parsed=None, refusal=None, cached=5):
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=30,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
    )
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class FakeServer:
    """Records the one request it is sent and answers with whatever it was built with."""

    def __init__(self, result):
        self.result = result
        self.request = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self.parse))

    def parse(self, **request):
        self.request = request
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def settings(monkeypatch):
    configured = Settings(openai_base_url="http://model.test/v1", openai_api_key="k")
    monkeypatch.setattr(client_module, "get_settings", lambda: configured)
    get_client.cache_clear()
    return configured


def serve(monkeypatch, result) -> FakeServer:
    server = FakeServer(result)
    monkeypatch.setattr(client_module, "get_client", lambda: server)
    return server


def call(**overrides):
    request = {
        "model": "qwen",
        "system": "sys",
        "source_text": "source",
        "user_text": "ask",
        "output_format": Answer,
        "thinking": True,
        "max_output_tokens": 1000,
    }
    request.update(overrides)
    return asyncio.run(parse_structured(**request))


def test_the_request_is_a_chat_completion_with_the_schema_and_the_thinking_switch(monkeypatch, settings):
    server = serve(monkeypatch, completion(parsed=Answer(text="hi")))

    parsed, _ = call(thinking=False)

    assert parsed == Answer(text="hi")
    sent = server.request
    assert sent["response_format"] is Answer
    assert sent["max_tokens"] == 1000
    assert sent["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    # Source first, request last: the repeated prefix is what the server caches.
    assert [m["role"] for m in sent["messages"]] == ["system", "user", "user"]
    assert [m["content"] for m in sent["messages"]] == ["sys", "source", "ask"]


def test_usage_is_read_from_the_chat_completion_fields(monkeypatch, settings):
    serve(monkeypatch, completion(parsed=Answer(text="hi"), cached=7))

    _, usage = call()

    assert (usage.model, usage.input_tokens, usage.cached_input_tokens, usage.output_tokens) == (
        "qwen", 120, 7, 30
    )


def test_a_refusal_is_raised_as_such(monkeypatch, settings):
    serve(monkeypatch, completion(refusal="No."))

    with pytest.raises(Refused, match="No."):
        call()


def test_running_out_of_tokens_is_reported_as_truncation(monkeypatch, settings):
    serve(monkeypatch, LengthFinishReasonError(completion=completion()))

    with pytest.raises(Truncated, match="thinking included"):
        call(thinking=True)


def test_source_text_is_cut_to_what_fits_beside_the_answer(settings):
    settings.context_window = 4000
    budget_chars = int((4000 - 1000 - OVERHEAD_TOKENS) * CHARS_PER_TOKEN)

    assert fit_to_window("x" * budget_chars, 1000) == "x" * budget_chars
    assert fit_to_window("x" * (budget_chars + 1), 1000) == "x" * budget_chars


def test_a_server_must_be_configured(monkeypatch):
    monkeypatch.setattr(client_module, "get_settings", lambda: Settings(openai_api_key="k"))
    get_client.cache_clear()

    with pytest.raises(NotConfigured, match="OPENAI_BASE_URL"):
        get_client()
