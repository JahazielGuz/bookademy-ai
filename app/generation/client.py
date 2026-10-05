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

from openai import BadRequestError, OpenAI, OpenAIError
from pydantic import BaseModel

from app.config import get_settings
from app.schemas import Usage

T = TypeVar("T", bound=BaseModel)


class Refused(Exception):
    """The model declined the request."""


class NotConfigured(Exception):
    """No OpenAI credentials could be resolved."""


class Truncated(Exception):
    """The model ran out of output budget before answering."""


NO_CREDENTIALS = "No OpenAI credentials. Set OPENAI_API_KEY in bookademy-ai/.env."

# Only reasoning models accept a reasoning effort; the rest reject the parameter
# outright with a 400. Matched on name because the API offers no capability lookup,
# and backed up by retrying without it if the guess is ever wrong — a rejected
# request is refused before inference, so the retry costs nothing.
REASONING_MODEL_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")
UNSUPPORTED_REASONING = "'reasoning.effort' is not supported"


def takes_reasoning_effort(model: str) -> bool:
    return model.startswith(REASONING_MODEL_PREFIXES)


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
    reasoning_effort: str,
    max_output_tokens: int = 16000,
) -> tuple[T, Usage]:
    """One structured-output call, with what it cost to make.

    Usage comes back with the content because the alternative is estimating it, and
    estimating it is how this project once predicted $5 and spent $20.

    The source text is a separate leading message so the cached prefix stays
    byte-identical across every topic in a chapter.
    """
    client = get_client()
    request = {
        "model": model,
        "instructions": system,
        "input": [
            {"role": "user", "content": source_text},
            {"role": "user", "content": user_text},
        ],
        "text_format": output_format,
        "max_output_tokens": max_output_tokens,
    }
    if takes_reasoning_effort(model):
        request["reasoning"] = {"effort": reasoning_effort}

    try:
        response = client.responses.parse(**request)
    except BadRequestError as exc:
        if UNSUPPORTED_REASONING not in str(exc):
            raise
        # The prefix list is behind a model it does not know about. Drop the
        # parameter and carry on rather than failing the whole run over a name.
        request.pop("reasoning", None)
        response = client.responses.parse(**request)

    # A reasoning model can spend the entire output budget thinking and return
    # nothing. Saying so beats "no parsable output", which is the symptom.
    if getattr(response, "status", None) == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
        raise Truncated(
            f"{model} stopped early ({reason}). It used "
            f"{getattr(response.usage, 'output_tokens', 0)} output tokens, of which "
            f"{_reasoning_tokens(response)} were reasoning, and had none left for an "
            f"answer. Raise max_output_tokens or lower the reasoning effort."
        )

    refusal = _refusal_of(response)
    if refusal is not None:
        raise Refused(refusal)

    parsed = response.output_parsed
    if parsed is None:
        raise ValueError(f"{model} returned no parsable {output_format.__name__}")

    return parsed, _usage_of(response, model)


def _reasoning_tokens(response) -> int:
    details = getattr(getattr(response, "usage", None), "output_tokens_details", None)
    return getattr(details, "reasoning_tokens", 0) or 0


def _usage_of(response, model: str) -> Usage:
    usage = getattr(response, "usage", None)
    details = getattr(usage, "input_tokens_details", None)
    return Usage(
        model=model,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        cached_input_tokens=getattr(details, "cached_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )


def _refusal_of(response) -> str | None:
    """A declined request comes back as a refusal block rather than content."""
    for item in getattr(response, "output", []) or []:
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", None) == "refusal":
                return getattr(block, "refusal", "The model declined this request.")
    return None
