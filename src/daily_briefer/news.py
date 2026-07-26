"""Tavily-powered news fetching — the main news engine."""
from __future__ import annotations

import httpx


class TavilyFetcher:
    """Fetches news articles using Tavily search API."""

    def __init__(self, api_key: str, max_results: int = 15):
        self.api_key = api_key
        self.max_results = max_results
        self.base_url = "https://api.tavily.com/search"

    async def search(self, query: str, max_results: int | None = None) -> list[dict]:
        """Search Tavily for news articles.

        Returns list of dicts with keys: title, url, content, score.
        """
        limit = max_results or self.max_results
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.base_url,
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": limit,
                    "include_answer": True,
                    "topic": "news",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        articles = []
        for item in data.get("results", []):
            articles.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score", 0),
            })
        return articles

    async def fetch_top_news(self, keywords: list[str]) -> list[dict]:
        """Fetch top news for each keyword and combine."""
        all_articles: list[dict] = []

        if keywords:
            for kw in keywords:
                articles = await self.search(f"{kw} news today", max_results=10)
                all_articles.extend(articles)
        else:
            # No preferences — fetch general tech news
            articles = await self.search("top tech news today", max_results=10)
            all_articles.extend(articles)

        # Deduplicate by URL
        seen = set()
        unique = []
        for article in all_articles:
            if article["url"] not in seen:
                seen.add(article["url"])
                unique.append(article)

        return unique[:20]  # Cap at 20 articles
