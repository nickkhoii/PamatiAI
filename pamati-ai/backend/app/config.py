from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    environment: str = "development"
    public_registration_enabled: bool = False
    institutional_domains: list[str] = []
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    session_days: int = Field(default=7, ge=1, le=30)
    auth_delivery_key: str = Field(default="", repr=False)
    auth_public_url: str = "http://localhost:3000"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_from: str = ""
    allow_raw_media_storage: bool = False
    database_url: str = Field(default="mysql+pymysql://pamati:local-only@localhost:3306/pamati?charset=utf8mb4", repr=False)
    cors_origins: list[str] = ["http://localhost:3000"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "backend", "testserver"]

    @field_validator("database_url")
    @classmethod
    def require_mysql(cls, value: str) -> str:
        from sqlalchemy.engine import make_url
        url = make_url(value)
        if url.drivername != "mysql+pymysql" or url.query.get("charset") != "utf8mb4":
            raise ValueError("Use mysql+pymysql with charset=utf8mb4")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
