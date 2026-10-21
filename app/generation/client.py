"""Model client plumbing shared by the generators.

Everything sent from here is text. The document was turned into Markdown before it
reached this module, so no PDF — and therefore no rendered page — ever goes over the
wire.

The server is llama.cpp behind its OpenAI-compatible API. Its /v1/responses endpoint
accepts a JSON schema and then ignores it, so every call goes through chat
completions, where the schema becomes a grammar the sampler cannot step outside of.
Prompt caching is per slot and automatic; what still matters is prompt *order*: the
source text goes first and the per-topic instruction last, so the repeated prefix is
identical across every call that shares a source.
"""

import logging
from functools import lru_cache

from openai import LengthFinishReasonError, OpenAI
from pydantic import BaseModel

from app.config import get_settings
from app.schemas import Usage

logger = logging.getLogger(__name__)


class Refused(Exception):
    """The model declined the request."""


class NotConfigured(Exception):
    """No model server could be resolved, or it does not serve the configured models."""


class Truncated(Exception):
    """The model ran out of output budget before answering."""


NO_CREDENTIALS = (
    "No model server configured. Set OPENAI_BASE_URL and OPENAI_API_KEY in "
    "bookademy-ai/.env."
)

# A topic on a local model is minutes of work, and the SDK's default of ten would cut
# off a long one with every slot busy.
TIMEOUT_SECONDS = 3600

# Qwen's tokenizer averages about four characters per token on English prose and
# fewer on code; 3.5 errs towards cutting a little too much rather than failing the
# call.
CHARS_PER_TOKEN = 3.5

# The instructions, the per-call request and the chat template, all of which sit in
# the window beside the source text and the answer.
OVERHEAD_TOKENS = 1500


@lru_cache
def get_client() -> OpenAI:
    """One client for the process, checked once against what the server serves.

    llama.cpp answers any model name with whatever it has loaded, so a stale name in
    .env would not fail here — the tokens would be recorded, and priced, under it.
    """
    settings = get_settings()
    if not settings.openai_base_url or not settings.openai_api_key:
        raise NotConfigured(NO_CREDENTIALS)
    client = OpenAI(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=TIMEOUT_SECONDS,
    )
    served = {served_model.id for served_model in client.models.list()}
    missing = {settings.outline_model, settings.content_model} - served
    if missing:
        raise NotConfigured(
            f"The model server does not serve {', '.join(sorted(missing))}; it serves "
            f"{', '.join(sorted(served))}. Set OUTLINE_MODEL and CONTENT_MODEL in "
            "bookademy-ai/.env."
        )
    return client


async def parse_structured[T: BaseModel](
    *,
    model: str,
    system: str,
    source_text: str,
    user_text: str,
    output_format: type[T],
    thinking: bool,
    max_output_tokens: int = 16000,
) -> tuple[T, Usage]:
    """One structured-output call, with what it cost to make.

    Usage comes back with the content because the alternative is estimating it, and
    estimating it is how this project once predicted $5 and spent $20. The dollars
    are gone now; the minutes are not.

    The source text is a separate leading message so the cached prefix stays
    byte-identical across every call that shares it.
    """
    client = get_client()
    source_text = fit_to_window(source_text, max_output_tokens)
    try:
        # Streamed for the connection, not for the tokens. A topic is minutes of work,
        # and a plain call carries nothing on the socket until the answer is complete
        # — long enough for whatever sits between here and the server, an ngrok edge
        # or a router's NAT table, to close it as idle. Measured: 900 seconds exactly,
        # with the model still generating. On a stream, bytes move every token. The
        # chunks are assembled here into the completion the plain call would have
        # returned.
        with client.chat.completions.stream(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": source_text},
                {"role": "user", "content": user_text},
            ],
            response_format=output_format,
            max_tokens=max_output_tokens,
            # A stream only carries usage if asked; without this the final chunk
            # has none and every call would be recorded as free and empty.
            stream_options={"include_usage": True},
            # llama.cpp's switch for Qwen's thinking, read by the chat template.
            extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
        ) as stream:
            completion = stream.get_final_completion()
    except LengthFinishReasonError as exc:
        # Thinking shares the budget with the answer and is not reported apart from
        # it, so all that can be said is that the room ran out.
        raise Truncated(
            f"{model} ran out of room before finishing: {max_output_tokens} output "
            f"tokens{', thinking included,' if thinking else ''} or the context window. "
            "Raise max_output_tokens or turn thinking off for this call."
        ) from exc

    message = completion.choices[0].message
    if message.refusal:
        raise Refused(message.refusal)
    if message.parsed is None:
        raise ValueError(f"{model} returned no parsable {output_format.__name__}")

    return message.parsed, _usage_of(completion.usage, model)


def fit_to_window(source_text: str, max_output_tokens: int) -> str:
    """Cut the source so the prompt and the answer fit one slot's context.

    llama.cpp refuses a prompt that does not fit rather than trimming it, and the
    only text here that can be trimmed is the source: the instructions and the
    request are the call. A cut chapter loses its last pages, which costs it some
    topics; a refused call loses the whole chapter.
    """
    settings = get_settings()
    budget_tokens = settings.context_window - max_output_tokens - OVERHEAD_TOKENS
    budget_chars = int(budget_tokens * CHARS_PER_TOKEN)
    if len(source_text) <= budget_chars:
        return source_text
    logger.warning(
        "source text cut from %d to %d characters to fit the context window",
        len(source_text),
        budget_chars,
    )
    return source_text[:budget_chars]


def _usage_of(usage, model: str) -> Usage:
    details = getattr(usage, "prompt_tokens_details", None)
    return Usage(
        model=model,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        cached_input_tokens=getattr(details, "cached_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )
