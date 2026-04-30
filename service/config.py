"""Configuration from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    gcs_bucket_prefix: str = "haderach-media"
    vertex_project: str = "haderach-ai"
    vertex_location: str = "us-central1"
    dev_auth_email: str | None = None
    local_storage_mode: bool = False
    local_storage_path: str = "./local-storage"

    class Config:
        env_file = ".env"
        extra = "ignore"

    def get_local_storage_dir(self) -> Path:
        """Return the local storage directory, creating it if needed."""
        path = Path(self.local_storage_path)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
