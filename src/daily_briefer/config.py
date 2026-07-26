"""Configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default) or default


def _env_int(key: str, default: int) -> int:
    value = _env(key, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def _load_env() -> None:
    config_path = _env("CONFIG_PATH")
    if config_path:
        load_dotenv(config_path, override=True)
        return
    load_dotenv()


@dataclass
class Config:
    gmail_address: str = field(default_factory=lambda: _env("GMAIL_ADDRESS"))
    gmail_app_password: str = field(default_factory=lambda: _env("GMAIL_APP_PASSWORD"))

    tavily_api_key: str = field(default_factory=lambda: _env("TAVILY_API_KEY"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.0-flash"))

    brief_name: str = field(default_factory=lambda: _env("BRIEF_NAME", "Master"))

    brief_retention_days: int = field(default_factory=lambda: _env_int("BRIEF_RETENTION_DAYS", 30))
    brief_time: str = field(default_factory=lambda: _env("BRIEF_TIME", "07:00"))
    brief_timezone: str = field(default_factory=lambda: _env("BRIEF_TIMEZONE", "UTC"))

    gmail_poll_interval: int = field(default_factory=lambda: _env_int("GMAIL_POLL_INTERVAL", 60))

    articles_per_source: int = field(default_factory=lambda: _env_int("ARTICLES_PER_SOURCE", 10))

    @property
    def db_path(self) -> str:
        return os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "daily_briefer.db"))


def load_config() -> Config:
    _load_env()
    return Config()
