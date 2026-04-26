import os
from pydantic_settings import BaseSettings
from functools import lru_cache

# Calculate absolute path for the database
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "floodsentry.db")

class Settings(BaseSettings):
    """FloodSentry application settings."""

    # Application
    APP_NAME: str = "FloodSentry"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = f"sqlite:///{DB_PATH}"

    # Copernicus / Sentinel Hub
    SENTINEL_HUB_CLIENT_ID: str = ""
    SENTINEL_HUB_CLIENT_SECRET: str = ""

    # Frontend
    VITE_API_URL: str = "http://localhost:8001"

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
