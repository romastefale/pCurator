from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    openai_key: str | None = None
    linkpreview_key: str | None = None
    owner_id: int
    channel_1_id: int | None = None
    channel_2_id: int | None = None
    mira_group_id: int | None = None
    mira_timeout_seconds: int = 90
    database_path: str = "./data/pcurator.db"
    timezone: str = "America/Sao_Paulo"

    gnews_key: str | None = None
    discovery_enabled: bool = False
    discovery_daily_cap: int = 20
    discovery_quiet_start: int = 1
    discovery_quiet_end: int = 5
    discovery_topics: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def discovery_topics_list(self) -> list[str] | None:
        if not self.discovery_topics.strip():
            return None
        return [t.strip() for t in self.discovery_topics.split(",") if t.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
