from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = ""
    admin_telegram_id: int | None = None
    db_path: str = "/app/data/diary.db"
    tz: str = "Europe/Moscow"
    snooze_minutes: int = 20
    bp_morning: str = "09:00"
    bp_evening: str = "20:00"

    @field_validator("admin_telegram_id", mode="before")
    @classmethod
    def empty_admin_id(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value


settings = Settings()
