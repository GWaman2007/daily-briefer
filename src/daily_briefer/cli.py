"""CLI entry point for DailyBriefer."""
from __future__ import annotations

import asyncio
import sys
from typing import Literal

import click
from rich.console import Console

from daily_briefer.config import load_config
from daily_briefer.agent import DailyBrieferAgent

console = Console()


def _run_async(coro):
    """Run an async coroutine from synchronous click command."""
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("[red]Interrupted by user.[/red]")
        sys.exit(1)


@click.group()
@click.option("--config", "-c", default=None, help="Path to config file")
@click.pass_context
def cli(ctx, config):
    """DailyBriefer — AI-powered, self-improving email news briefer."""
    ctx.ensure_object(dict)
    if config:
        import os
        os.environ["CONFIG_PATH"] = config


@cli.command()
@click.pass_context
def brief(ctx):
    """Run the daily briefing loop."""
    config = load_config()
    agent = DailyBrieferAgent(config)
    result = _run_async(agent.run(mode="brief"))
    if result:
        click.echo(f"Daily brief completed. Preferences: {result.get('preferences_count', 0)}, Events: {result.get('events_count', 0)}")


@cli.command()
@click.pass_context
def reply(ctx):
    """Check for and process new email replies."""
    config = load_config()
    agent = DailyBrieferAgent(config)
    _run_async(agent.run(mode="reply"))


@cli.command()
@click.option("--once", is_flag=True, default=False, help="Check once and exit (no infinite loop).")
@click.pass_context
def poll(ctx, once):
    """Poll for new email replies (always-on mode)."""
    config = load_config()
    agent = DailyBrieferAgent(config)
    console.print("[green]Polling for emails... (Ctrl+C to stop)[/green]")
    if once:
        _run_async(agent.run(mode="once"))
    else:
        _run_async(agent.run(mode="poll"))


@cli.command()
@click.pass_context
def run(ctx):
    """Run auto mode (check replies, then brief if none)."""
    config = load_config()
    agent = DailyBrieferAgent(config)
    _run_async(agent.run(mode="auto"))


@cli.command(name="list-prefs")
def list_prefs():
    """List current user preferences."""
    from daily_briefer.db import get_preferences, init_db
    config = load_config()
    init_db(config)
    prefs = get_preferences(config)
    if not prefs:
        click.echo("No preferences set yet.")
    else:
        click.echo("Your preferences:")
        for p in prefs:
            click.echo(f"  • {p['keyword']} (weight: {p['weight']})")


@cli.command()
@click.pass_context
def status(ctx):
    """Show system status."""
    from daily_briefer.db import get_recent_briefs, get_recent_replies, get_upcoming_events, init_db
    config = load_config()
    init_db(config)

    console.print("[bold]DailyBriefer Status[/bold]")
    console.print(f"  Gmail: {'✓' if config.gmail_address else '✗'} {config.gmail_address or '(not configured)'}")
    console.print(f"  Tavily: {'✓' if config.tavily_api_key else '✗'} {'configured' if config.tavily_api_key else '(not configured)'}")
    console.print(f"  Gemini: {'✓' if config.gemini_api_key else '✗'} {'configured' if config.gemini_api_key else '(not configured)'}")

    # Recent briefs
    briefs = get_recent_briefs(config)
    if briefs:
        console.print("\n[bold]Recent Briefs[/bold]")
        for b in briefs:
            sent = b.get('email_sent_at', 'pending')
            console.print(f"  • {b['date']} - {'sent' if sent != 'pending' else 'not sent'}")
    else:
        console.print("\nNo briefs sent yet.")

    # Upcoming events
    events = get_upcoming_events(config)
    if events:
        console.print("\n[bold]Upcoming Events[/bold]")
        for e in events:
            console.print(f"  • {e['date']}: {e['description']}")
    else:
        console.print("\nNo upcoming events.")


if __name__ == "__main__":
    cli()
