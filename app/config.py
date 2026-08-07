from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(default="sqlite+aiosqlite:///./plagiai.db", alias="DATABASE_URL")
    admin_ids: str = Field(default="", alias="ADMIN_IDS")
    max_file_mb: int = Field(default=20, alias="MAX_FILE_MB", ge=1, le=50)
    max_text_chars: int = Field(default=200_000, alias="MAX_TEXT_CHARS", ge=1_000, le=1_000_000)
    quetext_api_key: str | None = Field(default=None, alias="QUETEXT_API_KEY")
    quetext_poll_seconds: float = Field(
        default=3.0,
        alias="QUETEXT_POLL_SECONDS",
        ge=2.0,
        le=30.0,
    )
    quetext_timeout_seconds: int = Field(
        default=900,
        alias="QUETEXT_TIMEOUT_SECONDS",
        ge=30,
        le=3600,
    )
    public_base_url: str | None = Field(default=None, alias="PUBLIC_BASE_URL")
    railway_public_domain: str | None = Field(default=None, alias="RAILWAY_PUBLIC_DOMAIN")
    port: int = Field(default=8080, alias="PORT", ge=1, le=65535)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        # Railway/Supabase sometimes expose SQLAlchemy-incompatible schemes.
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().rstrip("/")
        return cleaned or None

    @property
    def admin_id_set(self) -> set[int]:
        result: set[int] = set()
        for item in self.admin_ids.split(","):
            item = item.strip()
            if item.isdigit():
                result.add(int(item))
        return result

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def quetext_ready(self) -> bool:
        return bool(self.quetext_api_key and self.quetext_api_key.strip())

    @property
    def verification_base_url(self) -> str:
        if self.public_base_url:
            return self.public_base_url
        if self.railway_public_domain:
            domain = self.railway_public_domain.strip().rstrip("/")
            if domain.startswith(("http://", "https://")):
                return domain
            return f"https://{domain}"
        return f"http://localhost:{self.port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
