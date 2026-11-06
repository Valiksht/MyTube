from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MyTube"
    database_url: str = "postgresql+asyncpg://mytube:mytube@localhost:5432/mytube"
    db_echo: bool = False

    jwt_secret_key: str = Field(
        default="dev-only-mytube-jwt-secret-change-me",
        min_length=32,
    )
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1)

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "mytube"
    minio_secure: bool = False
    minio_public_endpoint: str = "localhost:9000"
    max_upload_bytes: int = Field(default=2_147_483_648, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
