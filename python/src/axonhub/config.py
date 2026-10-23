from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AXON_", env_file=".env", extra="ignore")

    admin_token: SecretStr = SecretStr("")
    database_url: str = "sqlite+aiosqlite:///./data/axonhub.db"
    connect_timeout: float = 5
    read_timeout: float = 60
