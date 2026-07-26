"""Configuration loader with environment variable support."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Optional


# Map of type names to actual types (handles `from __future__ import annotations`)
_TYPE_MAP = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict, "Optional": None}


def _env(key: str, default, cast):
    """Get environment variable with optional cast."""
    # With `from __future__ import annotations`, f.type is a string like "int"
    if isinstance(cast, str):
        cast = _TYPE_MAP.get(cast)

    value = os.environ.get(key)
    if value is None:
        return default
    if cast:
        value = cast(value)
    return value


@dataclass
class Config:
    """Application configuration, loaded from environment variables."""

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_model_fallback: str = "gemini-3.1-flash-lite"
    tavily_api_key: str = ""
    gmail_address: str = ""
    gmail_app_password: str = ""
    brief_name: str = "User"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # Email polling
    gmail_poll_interval: int = 60

    # Database
    db_path: str = "daily_briefer.db"

    # Brief settings
    brief_retention_days: int = 30

    # Reply history
    reply_retention_days: int = 30

    def __post_init__(self):
        """Load config from environment variables."""
        for f in fields(self):
            val = _env(f.name.upper(), f.default, f.type)
            if val is not None:
                setattr(self, f.name, val)


def load_config() -> Config:
    """Load configuration from environment variables."""
    return Config()
