"""The main agent that orchestrates Tavily search, Gemini, and email."""
from __future__ import annotations

import json
import asyncio
import httpx
from bs4 import BeautifulSoup
from typing import Any

from daily_briefer.config import Config, load_config
from daily_briefer.db import (
    init_db,
    get_preferences,
    get_all_events,
    add_preference,
    remove_preference,
    add_event,
    remove_event,
    save_brief_record,
    save_reply,
    cleanup_old_briefs,
    cleanup_old_events,
    mark_event_delivered,
    get_pending_events,
    get_brief_by_date,
    set_brief_sent,
)
from daily_briefer.news import TavilyFetcher
from daily_briefer.gemini import GeminiClient
from daily_briefer.gmail import GmailClient


class DailyBrieferAgent:
    """The main agent that runs the daily briefing loop."""

    def __init__(self, config: Config | None = None):
        self.config = config or load_config()
        init_db(self.config)
        self.tavily = TavilyFetcher(self.config.tavily_api_key)
        self.gemini = GeminiClient(
            self.config.gemini_api_key,
            self.config.gemini_model,
            self.config.gemini_model_fallback,
        )
        self.gmail = GmailClient(self.config)

    async def scrape_url(self, url: str, max_words: int = 2000) -> str:
        """Fetch and scrape a URL, returning truncated text content."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")

                # Remove script/style elements
                for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                    tag.decompose()

                # Get text content
                text = soup.get_text(separator="\n", strip=True)

                # Truncate to max_words
                words = text.split()
                if len(words) > max_words:
                    text = " ".join(words[:max_words]) + "\n\n... [truncated]"

                return text.strip()
        except Exception as e:
            return f"[Failed to fetch {url}: {e}]"

    async def run_briefing_loop(self, context: dict) -> str:
        """Run the Tavily search loop until the briefing is complete.

        This is the core agentic loop:
        1. Model reviews preferences + events
        2. Model generates search queries
        3. Tavily returns results
        4. Model decides: more searches, fetch URLs, or generate brief
        """
        max_iterations = 10
        iteration = 0
        all_articles = context.get("articles", [])
        fetched_urls = set()
        pending_finds = []
        search_queries = []
        model_memory = []

        system_prompt = self._build_system_prompt(context)

        while iteration < max_iterations:
            iteration += 1
            model_memory.append({
                "role": "user",
                "content": f"\n\nSearch iteration {iteration}:\n"
                          f"Articles so far: {len(all_articles)}\n"
                          f"URLs already fetched: {len(fetched_urls)}\n"
                          f"Pending URL fetches: {len(pending_finds)}\n"
                          f"Search queries used: {', '.join(search_queries) if search_queries else 'none yet'}\n"
                          f"Latest Tavily results: {json.dumps(all_articles[-10:], indent=2) if all_articles else 'None yet'}"
            })

            # Send to Gemini with tools for searching and fetching
            tools = [
                {
                    "function_declarations": [
                        {
                            "name": "search_tavily",
                            "description": "Search Tavily for news articles. Use this when you need more information on a topic.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "queries": {
                                        "type": "ARRAY",
                                        "items": {"type": "STRING"},
                                        "description": "List of 1-3 search queries to run on Tavily"
                                    }
                                },
                                "required": ["queries"]
                            }
                        },
                        {
                            "name": "fetch_url",
                            "description": "Fetch and scrape a specific URL to read its full content. Returns up to 2000 words of text.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "urls": {
                                        "type": "ARRAY",
                                        "items": {"type": "STRING"},
                                        "description": "List of URLs to fetch"
                                    }
                                },
                                "required": ["urls"]
                            }
                        },
                        {
                            "name": "generate_brief",
                            "description": "Generate the final daily news briefing. Call this when you have enough information to write a complete brief.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "brief": {
                                        "type": "STRING",
                                        "description": "The complete markdown briefing text"
                                    }
                                },
                                "required": ["brief"]
                            }
                        }
                    ]
                }
            ]

            response = await self.gemini._chat([], system_prompt=system_prompt, tools=tools)

            # Check for function calls
            candidates = response.get("candidates", [])
            if not candidates:
                break

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            model_memory.append({"role": "model", "content": ""})

            # Process tool calls
            for part in parts:
                if "function_call" in part:
                    func = part["function_call"]
                    args = func.get("args", {})

                    if func["name"] == "search_tavily":
                        queries = args.get("queries", [])
                        search_results = []
                        for q in queries:
                            search_queries.append(q)
                            results = await self.tavily.search(q, max_results=10)
                            search_results.extend(results)

                        all_articles.extend(search_results)
                        # Deduplicate
                        seen = set()
                        unique = []
                        for a in all_articles:
                            if a.get("url") not in seen:
                                seen.add(a.get("url"))
                                unique.append(a)
                        all_articles = unique

                        model_memory[-1]["content"] += f"[Searched: {', '.join(queries)}]\n"
                        model_memory[-1]["content"] += f"[Results: {len(search_results)} new articles found]"

                    elif func["name"] == "fetch_url":
                        urls = args.get("urls", [])
                        model_memory[-1]["content"] += f"[Fetched: {len(urls)} URLs]\n"
                        for url in urls:
                            if url not in fetched_urls:
                                fetched_urls.add(url)
                                content = await self.scrape_url(url)
                                model_memory[-1]["content"] += f"\n\n--- {url} ---\n{content[:500]}...\n"

                    elif func["name"] == "generate_brief":
                        brief = args.get("brief", "")
                        if brief:
                            model_memory[-1]["content"] += f"\n[Brief generated: {len(brief)} characters]"
                            return brief

                elif "text" in part:
                    model_memory[-1]["content"] += part["text"]

        # If we exhausted iterations without generating a brief, make one
        return self._fallback_brief(context, all_articles)

    def _build_system_prompt(self, context: dict) -> str:
        """Build the system prompt for the briefing loop."""
        preferences = context.get("preferences", [])
        events = context.get("events", [])

        return f"""You are an AI news briefer called DailyBriefer. Your job is to gather enough information to write a comprehensive daily news briefing for {context.get('user_name', 'the user')}.

CURRENT USER PREFERENCES:
{json.dumps(preferences, indent=2) if preferences else "No specific preferences yet."}

UPCOMING EVENTS/REMINDERS:
{json.dumps(events, indent=2) if events else "No upcoming events."}

YOUR CAPABILITIES:
1. search_tavily(queries: string[]) — Search Tavily for news articles
2. fetch_url(urls: string[]) — Scrape specific URLs for full article content
3. generate_brief(brief: string) — Generate the final briefing

RULES:
- You MUST use search_tavily to gather news based on user preferences
- Generate 1-3 specific queries per search (e.g., "AI breakthroughs today", "startup funding news")
- If an article looks important but you need more detail, use fetch_url
- You can search multiple rounds if needed — up to 10 iterations
- You MUST call generate_brief when you have enough information
- Be thorough but efficient — don't waste iterations
- The final brief should be in markdown, engaging, and personalized"""

    def _fallback_brief(self, context: dict, articles: list[dict]) -> str:
        """Generate a brief even if the loop didn't complete normally."""
        preferences = context.get("preferences", [])
        events = context.get("events", [])

        text = f"# Daily News Briefing — {context.get('date', 'Today')}\n\n"
        text += f"*Generated by DailyBriefer AI*\n\n"

        if articles:
            text += "## Today's Top Stories\n\n"
            for i, article in enumerate(articles[:10], 1):
                title = article.get("title", "Untitled")
                url = article.get("url", "#")
                text += f"{i}. [{title}]({url})\n"

        if events:
            text += "\n## Upcoming Events\n\n"
            for event in events[:5]:
                text += f"- **{event['date']}**: {event['description']}\n"

        return text

    async def process_user_reply(self, email: dict) -> tuple[str, dict]:
        """Process a user reply and apply changes.

        Returns (reply_text, changes_applied).
        """
        current_prefs = get_preferences(self.config)
        current_events = get_all_events(self.config)

        # Let Gemini analyze the reply
        result = await self.gemini.process_reply(
            email["subject"],
            email["body"],
            current_prefs,
            current_events,
        )

        action = result.get("action", "ack")
        changes = {}

        if action == "add_pref":
            keyword = result.get("keyword", "")
            if keyword:
                add_preference(self.config, keyword)
                changes["added"] = keyword

        elif action == "remove_pref":
            keyword = result.get("keyword", "")
            if keyword:
                remove_preference(self.config, keyword)
                changes["removed"] = keyword

        elif action == "add_event":
            date = result.get("event_date", "")
            desc = result.get("event_description", "")
            if date and desc:
                event_id = add_event(self.config, date, desc)
                changes["added_event"] = {"id": event_id, "date": date, "description": desc}

        elif action == "remove_event":
            event_id = result.get("event_id")
            if event_id:
                remove_event(self.config, event_id)
                changes["removed_event"] = event_id

        # Save reply to history
        save_reply(
            self.config,
            email["subject"],
            email["body"],
            json.dumps(changes),
        )

        reply_text = result.get("reply_text", "Got it!")
        return reply_text, changes

    async def run_daily_briefing(self) -> dict:
        """Run the full daily briefing process."""
        from datetime import datetime, timezone

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Get preferences and events
        preferences = get_preferences(self.config)
        events = get_all_events(self.config)

        # Prepare context for the agent
        context = {
            "date": date,
            "user_name": self.config.brief_name,
            "preferences": preferences,
            "events": events,
            "articles": [],
        }

        # Run the briefing loop
        print("[Briefing] Starting Tavily search loop...")
        brief_content = await self.run_briefing_loop(context)

        # Save brief to DB
        save_brief_record(
            self.config,
            date,
            brief_content,
            preferences,
            email_sent_at=datetime.now(timezone.utc).isoformat(),
        )

        # Deliver any pending events
        pending = get_pending_events(self.config)
        delivered_events = []
        for event in pending:
            mark_event_delivered(self.config, event["id"])
            delivered_events.append(event)

        result = {
            "date": date,
            "brief_saved": True,
            "preferences_count": len(preferences),
            "events_count": len(events),
            "delivered_events": delivered_events,
        }

        # Cleanup
        cleanup_old_briefs(self.config)
        cleanup_old_events(self.config)

        return result

    async def run(self, mode: str = "auto") -> None:
        """Run the main agent loop.

        Modes:
        - "auto": Check for replies first, then run daily brief
        - "brief": Only run the daily briefing
        - "reply": Only check for and process new replies
        - "poll": Continuously poll for new replies (for always-on mode)
        """
        print("[DailyBriefer] Starting...")

        if mode == "brief":
            print("[Briefing] Running daily briefing...")
            result = await self.run_daily_briefing()
            brief_content = get_brief_by_date(self.config, result['date'])
            if not brief_content:
                brief_content = "Brief not generated."
            success = await self.send_brief_email(brief_content)
            print(f"[Briefing] Brief {'sent' if success else 'failed to send'} with {result['preferences_count']} preferences and {result['events_count']} events")
            return

        if mode == "reply":
            email = await self.gmail.fetch_unread_email()
            if email:
                print(f"[Reply] Found unread email: {email['subject']}")
                reply_text, changes = await self.process_user_reply(email)
                await self.gmail.send_email(
                    to=email["from"],
                    subject=f"Re: {email['subject']}",
                    body=reply_text,
                )
                email_id = email.get("id", "")
                if email_id:
                    await self.gmail.mark_as_read(email_id)
                print(f"[Reply] Sent: {reply_text}")
            return

        if mode == "once":
            # Single pass: check for new emails, process if found, then exit
            email = await self.gmail.fetch_unread_email()
            if email:
                print(f"[Reply] Found unread email: {email['subject']}")
                reply_text, changes = await self.process_user_reply(email)
                await self.gmail.send_email(
                    to=email["from"],
                    subject=f"Re: {email['subject']}",
                    body=reply_text,
                )
                email_id = email.get("id", "")
                if email_id:
                    await self.gmail.mark_as_read(email_id)
                print(f"[Reply] Sent: {reply_text}")
            else:
                print("[Poll] No new emails. Exiting.")
            return

        if mode == "poll":
            import asyncio
            while True:
                email = await self.gmail.fetch_unread_email()
                if email:
                    print(f"[Reply] Found unread email: {email['subject']}")
                    reply_text, changes = await self.process_user_reply(email)
                    await self.gmail.send_email(
                        to=email["from"],
                        subject=f"Re: {email['subject']}",
                        body=reply_text,
                    )
                    email_id = email.get("id", "")
                    if email_id:
                        await self.gmail.mark_as_read(email_id)
                    print(f"[Reply] Sent: {reply_text}")
                else:
                    print(f"[Poll] No new emails. Sleeping for {self.config.gmail_poll_interval}s...")
                await asyncio.sleep(self.config.gmail_poll_interval)
            return

        # Default "auto" mode
        email = await self.gmail.fetch_unread_email()
        if email:
            print(f"[Reply] Found unread email: {email['subject']}")
            reply_text, changes = await self.process_user_reply(email)
            await self.gmail.send_email(
                to=email["from"],
                subject=f"Re: {email['subject']}",
                body=reply_text,
            )
            email_id = email.get("id", "")
            if email_id:
                await self.gmail.mark_as_read(email_id)
            print(f"[Reply] Sent: {reply_text}")
        else:
            print("[Briefing] Running daily briefing...")
            result = await self.run_daily_briefing()
            await self.send_brief_email()
            print(f"[Briefing] Brief sent with {result['preferences_count']} preferences and {result['events_count']} events")

    async def send_brief_email(self, brief_content: str | None = None) -> bool:
        """Send the latest brief via email."""
        from datetime import datetime, timezone

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if brief_content is None:
            # Read from Supabase
            brief_content = get_brief_by_date(self.config, date)
            if not brief_content:
                brief_content = f"# Daily Briefing — {date}\n\nNo brief available."

        success = await self.gmail.send_email(
            to=self.config.gmail_address,
            subject=f"Daily Brief — {date}",
            body=brief_content,
        )

        if success:
            # Mark email as sent in Supabase
            set_brief_sent(self.config, date)

        return success

