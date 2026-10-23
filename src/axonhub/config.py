from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", env_file=".env", extra="ignore")

    admin_token: SecretStr = SecretStr("")
    encryption_key: SecretStr = SecretStr("")
    database_url: str = "sqlite+aiosqlite:///./data/axonhub.db"
    connect_timeout: float = Field(default=5, gt=0)
    read_timeout: float = Field(default=60, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=5)
    failure_threshold: int = Field(default=2, ge=1)
    cooldown_seconds: float = Field(default=30, gt=0)
