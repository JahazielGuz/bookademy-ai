from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The model server: llama.cpp behind its OpenAI-compatible API, reached through the
    # OpenAI SDK. Both are required. Left unset, the SDK would quietly fall back to
    # api.openai.com, which this service no longer talks to.
    openai_base_url: str | None = None
    openai_api_key: str | None = None

    service_token: str = "dev-only-change-me"

    # One local model serves every call, so the two tiers are the same model by
    # default. They are kept apart because the calls still differ in what they need:
    # the outline call groups headings it is handed, the content call writes the
    # product — and a second server could serve a bigger model for the latter.
    outline_model: str = "qwen3.8-27b"
    content_model: str = "qwen3.8-27b"

    # Whether the model thinks before it answers. On a local model thinking is paid in
    # minutes and in context rather than dollars: every reasoning token shares one
    # slot's window with the source text and the answer, at about twenty tokens a
    # second. The outline call only groups headings, so it does not get to. The
    # content call writes every lesson and exercise, and that is the one place the
    # time is worth spending.
    outline_thinking: bool = False
    content_thinking: bool = True

    # Context per server slot: llama.cpp's --ctx-size, per --parallel slot. Source text
    # that would not fit beside the answer is cut to fit rather than refused.
    context_window: int = 32768


@lru_cache
def get_settings() -> Settings:
    return Settings()
