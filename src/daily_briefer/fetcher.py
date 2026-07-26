from __future__ import annotations

import httpx

from daily_briefer.config import Settings
from daily_briefer.models import Article
from daily_briefer.sources import get_source


class Fetcher:
    """Fetches articles from configured sources."""

    def __init__(self, settings: Settings, session: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._session = session

    async def fetch_all(self) -> dict[str, list[Article]]:
        """Fetch articles from all configured sources.

        Returns dict mapping source name -> list of articles.
        """
        source_names = [s.strip() for s in self._settings.sources.split(",")]
        results: dict[str, list[Article]] = {}
        async with httpx.AsyncClient(timeout=60) as session:
            for name in source_names:
                src = get_source(name)
                if src is None:
                    print(f"  [WARN] Unknown source '{name}', skipping.")
                    continue
                src._session = session
                try:
                    articles = await src.fetch(self._settings.articles_per_source)
                    results[name] = articles
                    print(f"  [OK] {src.display_name}: {len(articles)} articles")
                except Exception as exc:
                    print(f"  [ERR] {src.display_name}: {exc}")
                    results[name] = []
        return results
