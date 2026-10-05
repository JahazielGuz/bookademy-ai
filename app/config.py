from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = None

    service_token: str = "dev-only-change-me"

    # Topic merging is structural work over a chapter's own headings; content
    # authoring is the part that carries the product. Both are mid-tier on purpose —
    # a nano-class model is built for classification and routing, not for writing
    # cumulative exercises where every step has to compile and build on the last.
    outline_model: str = "gpt-5-mini"
    content_model: str = "gpt-5-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
