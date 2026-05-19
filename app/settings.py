from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    openai_key: str | None = None
    linkpreview_key: str | None = None
    owner_id: int
    channel_1_id: int | None = None
    channel_2_id: int | None = None
    database_path: str = "./data/pcurator.db"
    timezone: str = "America/Sao_Paulo"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
