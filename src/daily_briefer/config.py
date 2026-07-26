"""Configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default) or default


@dataclass
class Config:
    gmail_address: str = ""
    gmail_app_password: str = ""

    tavily_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    brief_name: str = "Master"

    brief_retention_days: int = 30
    brief_time: str = "07:00"
    brief_timezone: str = "UTC"

    gmail_poll_interval: int = 60

    articles_per_source: int = 10

    @property
    def db_path(self) -> str:
        return os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "daily_briefer.db"))


def load_config() -> Config:
    return Config()
