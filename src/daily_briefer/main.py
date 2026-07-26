from __future__ import annotations

import sys
from datetime import datetime

import typer

from daily_briefer.config import Settings, get_settings
from daily_briefer.fetcher import Fetcher
from daily_briefer.formatter import format_brief
from daily_briefer.models import BriefItem, DailyBrief
from daily_briefer.summarizer import Summarizer

app = typer.Typer(
    name="daily-briefer",
    help="Daily news briefing aggregator with AI summarization.",
)

settings = get_settings()


async def _build_brief(fetcher: Fetcher, summarizer: Summarizer) -> DailyBrief:
    """Run the full pipeline: fetch → summarize → format."""
    raw = await fetcher.fetch_all()
    items: list[BriefItem] = []
    for source_name, articles in raw.items():
        descriptions = [a.description or a.title for a in articles if a.description]
        if not descriptions:
            descriptions = [a.title for a in articles]
        summary = await summarizer.summarize_articles(source_name, descriptions)
        items.append(BriefItem(source=source_name, articles=articles, summary=summary))
    return DailyBrief(date=datetime.now(), items=items, master=settings.brief_name)


@app.command()
def brief() -> None:
    """Generate and display today's briefing."""
    import asyncio

    typer.echo("Fetching articles...")
    fetcher = Fetcher(settings)
    summarizer = Summarizer(settings)
    brief = asyncio.run(_build_brief(fetcher, summarizer))
    output = format_brief(brief, fmt="markdown")
    typer.echo(output)


@app.command()
def fetch() -> None:
    """Fetch articles without summarization."""
    import asyncio

    typer.echo("Fetching articles...")
    fetcher = Fetcher(settings)
    raw = asyncio.run(fetcher.fetch_all())
    for source, articles in raw.items():
        typer.echo(f"\n## {source}")
        for a in articles:
            typer.echo(f"  - {a.title} ({a.url})")


@app.command()
def list_sources() -> None:
    """List available sources."""
    from daily_briefer.sources import SOURCE_MAP
    typer.echo("Available sources:")
    for name, cls in SOURCE_MAP.items():
        typer.echo(f"  {name:20s} → {cls.display_name}")


if __name__ == "__main__":
    app()
