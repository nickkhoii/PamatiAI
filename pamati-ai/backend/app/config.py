from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore", hide_input_in_errors=True)
    environment: Literal["development", "test", "production"] = "development"
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
    safety_policy: dict = {}
    safety_resources: list[dict] = []
    longitudinal_algorithm: str = "descriptive-personal-trends"
    longitudinal_configuration: dict = {}
    multimodal_fusion_enabled: bool = True
    multimodal_fusion_strategy: str = "late-fusion"
    multimodal_fusion_weights: dict[str, float] = {"text": 1.0, "audio": 1.0, "visual": 1.0}
    multimodal_fusion_minimum_confidence: float = Field(default=0.0, ge=0, le=1)
    multimodal_fusion_maximum_source_span_seconds: float = Field(default=300.0, ge=0, le=3600)
    visual_analysis_enabled: bool = False
    visual_feature_extractor: str = Field(default="no-expression", min_length=1, max_length=180)
    visual_analysis_model: str = Field(default="no-expression", min_length=1, max_length=180)
    visual_analysis_minimum_confidence: float = Field(default=0.0, ge=0, le=1)
    visual_max_bytes: int = Field(default=3_000_000, ge=1024, le=3_000_000)
    visual_max_pixels: int = Field(default=262_144, ge=1, le=262_144)
    visual_max_input_frames: int = Field(default=32, ge=1, le=32)
    visual_sample_count: int = Field(default=8, ge=1, le=8)
    visual_max_seconds: float = Field(default=30.0, ge=0.0, le=30.0)
    visual_temporary_directory: str = ""
    audio_analysis_enabled: bool = False
    audio_analysis_model: str = Field(default="acoustic-features", min_length=1, max_length=180)
    audio_analysis_minimum_confidence: float = Field(default=0.0, ge=0, le=1)
    audio_max_bytes: int = Field(default=3_000_000, ge=1024, le=3_000_000)
    audio_max_seconds: float = Field(default=30.0, ge=0.04, le=30.0)
    audio_temporary_directory: str = ""
    audio_storage_directory: str = "../private-audio"
    text_analysis_models: list[str] = []
    text_analysis_minimum_confidence: float = Field(default=0.0, ge=0, le=1)

    @field_validator("text_analysis_models")
    @classmethod
    def distinct_text_models(cls, value):
        if len(value) > 8 or len(value) != len(set(value)) or any(not name for name in value):
            raise ValueError("Select up to eight distinct registered text models")
        return value

    conversation_provider: Literal["local-support", "compatible-http"] = "local-support"
    conversation_endpoint: str = Field(default="", max_length=2048)
    conversation_model: str = Field(default="", max_length=160)
    conversation_model_version: str = Field(default="deployment-unspecified", max_length=120)
    conversation_api_key: str = Field(default="", repr=False)
    database_url: str = Field(default="mysql+pymysql://pamati:local-only@localhost:3306/pamati?charset=utf8mb4", repr=False)
    cors_origins: list[str] = ["http://localhost:3000"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "backend", "testserver"]

    @model_validator(mode="after")
    def production_boundaries(self):
        if self.environment != "production":
            return self
        from urllib.parse import urlsplit

        from sqlalchemy.engine import make_url

        url = urlsplit(self.auth_public_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Production authentication requires a clean HTTPS public URL")
        for origin in self.cors_origins:
            parsed = urlsplit(origin)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("Production CORS requires explicit HTTPS origins")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            raise ValueError("Production requires explicit allowed hosts")
        database = make_url(self.database_url)
        if not database.password or database.password in {"local-only", "pamati", "password"}:
            raise ValueError("Replace the development database password before production")
        return self

    @field_validator("conversation_endpoint")
    @classmethod
    def secure_conversation_endpoint(cls, value: str) -> str:
        from urllib.parse import urlsplit

        if value:
            url = urlsplit(value)
            local = url.hostname in {"localhost", "127.0.0.1", "::1"}
            if not url.hostname or url.username or url.password or url.query or url.fragment or not (
                url.scheme == "https" or (url.scheme == "http" and local)
            ):
                raise ValueError("Use HTTPS or loopback HTTP, without URL credentials or query secrets")
        return value

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
