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
    outline_model: str = "gpt-5-nano"
    content_model: str = "gpt-5-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
