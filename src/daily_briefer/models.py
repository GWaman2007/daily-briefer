from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Article:
    """A single news article from any source."""

    title: str
    url: str
    source: str
    published: datetime | None = None
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class BriefItem:
    """A summarized article grouped by source."""

    source: str
    articles: list[Article] = field(default_factory=list)
    summary: str = ""


@dataclass
class DailyBrief:
    """A full daily brief — collection of summarized articles."""

    date: datetime
    items: list[BriefItem] = field(default_factory=list)
    master: str = "Master"
