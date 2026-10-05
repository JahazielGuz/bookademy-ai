"""OpenAI client plumbing shared by the generators.

Everything sent from here is text. The document was turned into Markdown before it
reached this module, so no PDF — and therefore no rendered page — ever goes over the
wire.

Prompt caching is automatic on OpenAI for long prompts and needs no annotation, so
unlike the previous provider there is no cache_control to place. What still matters
is prompt *order*: the source text goes first and the per-topic instruction last, so
the repeated prefix is identical across every topic in a chapter.
"""

from functools import lru_cache
from typing import TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class Refused(Exception):
    """The model declined the request."""


class NotConfigured(Exception):
    """No OpenAI credentials could be resolved."""


NO_CREDENTIALS = "No OpenAI credentials. Set OPENAI_API_KEY in bookademy-ai/.env."


@lru_cache
def get_client() -> OpenAI:
    """One client for the process.

    An unset key is not fatal here: the SDK falls back to OPENAI_API_KEY in the
    environment, and only a request discovers whether anything resolved.
    """
    settings = get_settings()
    try:
        return OpenAI(api_key=settings.openai_api_key)
    except OpenAIError as exc:
        # The SDK raises at construction when no key resolves anywhere. Turning it
        # into a configuration error here is what lets the service answer 503 with a
        # sentence rather than a stack trace.
        raise NotConfigured(NO_CREDENTIALS) from exc


async def parse_structured(
    *,
    model: str,
    system: str,
    source_text: str,
    user_text: str,
    output_format: type[T],
    max_output_tokens: int = 16000,
) -> T:
    """One structured-output call over already-extracted text.

    The source text is a separate leading message so the cached prefix stays
    byte-identical across every topic in a chapter.
    """
    client = get_client()
    response = client.responses.parse(
        model=model,
        instructions=system,
        input=[
            {"role": "user", "content": source_text},
            {"role": "user", "content": user_text},
        ],
        text_format=output_format,
        max_output_tokens=max_output_tokens,
    )

    refusal = _refusal_of(response)
    if refusal is not None:
        raise Refused(refusal)

    parsed = response.output_parsed
    if parsed is None:
        raise ValueError(f"{model} returned no parsable {output_format.__name__}")
    return parsed


def _refusal_of(response) -> str | None:
    """A declined request comes back as a refusal block rather than content."""
    for item in getattr(response, "output", []) or []:
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", None) == "refusal":
                return getattr(block, "refusal", "The model declined this request.")
    return None
