"""Anthropic client plumbing shared by the generators.

Everything sent from here is text. The document was turned into Markdown before it
reached this module, so no PDF — and therefore no rendered page — ever goes over the
wire.
"""

from functools import lru_cache
from typing import Any, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class Refused(Exception):
    """A safety classifier declined the request."""

    def __init__(self, category: str | None, explanation: str | None) -> None:
        self.category = category
        super().__init__(explanation or "The model declined this request.")


class NotConfigured(Exception):
    """No Anthropic credentials could be resolved."""


NO_CREDENTIALS = (
    "No Anthropic credentials. Set ANTHROPIC_API_KEY in bookademy-ai/.env, "
    "or run `ant auth login`."
)

# The SDK reports missing credentials as a bare TypeError raised while building the
# request headers — not at construction, and not as an AnthropicError. It is matched
# on its message so that a genuine TypeError is still allowed to surface as a bug.
_CREDENTIAL_FAILURE = "Could not resolve authentication method"


def raise_for_credentials(exc: TypeError) -> None:
    """Re-raise a credential TypeError as something a caller can act on."""
    if _CREDENTIAL_FAILURE not in str(exc):
        raise exc
    raise NotConfigured(NO_CREDENTIALS) from exc


@lru_cache
def get_client() -> AsyncAnthropic:
    """One client for the process.

    An unset api_key is normal: the SDK then falls back to ANTHROPIC_API_KEY,
    ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile on disk. Whether any of
    those resolved is only discovered on the first request.
    """
    settings = get_settings()
    headers = (
        {"anthropic-workspace-id": settings.anthropic_workspace_id}
        if settings.anthropic_workspace_id
        else None
    )
    return AsyncAnthropic(api_key=settings.anthropic_api_key, default_headers=headers)


def source_block(text: str, *, cache: bool) -> dict[str, Any]:
    """The chapter's text, optionally written to the prompt cache.

    Caching is worth it when the same chapter is about to be sent once per topic,
    and a loss on a single call, where the write costs more than the read saves.
    """
    block: dict[str, Any] = {"type": "text", "text": text}
    if cache:
        block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return block


async def parse_structured(
    *,
    model: str,
    system: str,
    source_text: str,
    user_text: str,
    output_format: type[T],
    effort: str,
    cache_source: bool,
    max_tokens: int = 16000,
) -> T:
    """One structured-output call over already-extracted text.

    The source text comes first and the instruction last, so the cached prefix stays
    byte-identical across every topic in a chapter.
    """
    client = get_client()
    try:
        response = await client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            output_config={"effort": effort},
            output_format=output_format,
            messages=[
                {
                    "role": "user",
                    "content": [
                        source_block(source_text, cache=cache_source),
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
    except TypeError as exc:
        raise_for_credentials(exc)
        raise

    if response.stop_reason == "refusal":
        details = response.stop_details
        raise Refused(
            category=getattr(details, "category", None),
            explanation=getattr(details, "explanation", None),
        )
    if response.stop_reason == "max_tokens":
        raise ValueError(
            f"{model} hit the {max_tokens} token ceiling before finishing; raise max_tokens"
        )

    parsed = response.parsed_output
    if parsed is None:
        raise ValueError(f"{model} returned no parsable {output_format.__name__} block")
    return parsed
