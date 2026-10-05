from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = None

    service_token: str = "dev-only-change-me"

    # Two tiers, because the two calls are not the same kind of work.
    #
    # The outline call is given the chapter's own headings and asked to group them:
    # constrained, mechanical, and no longer the high-stakes call it was when it had
    # to invent the chapter structure from the whole book. A small model suits it.
    #
    # The content call writes the lessons and the exercises. It is the product, it is
    # 92% of the spend, and it is the one place where a cheaper model shows.
    outline_model: str = "gpt-4o-mini"
    content_model: str = "gpt-4o-mini"

    # Only applied to models that accept it. Reasoning models bill their thinking as
    # output tokens while never showing it in the content: measured on one small call,
    # effort "low" spent 905 output tokens where "medium" spent 7,961 — 8.8x for 144
    # more tokens of answer. Ignored entirely on a model like gpt-4o-mini, which does
    # not reason and spent 81 output tokens on the same call.
    outline_reasoning: str = "low"
    content_reasoning: str = "low"


@lru_cache
def get_settings() -> Settings:
    return Settings()
