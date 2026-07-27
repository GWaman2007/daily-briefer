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
    get_user_profile,
    update_user_profile,
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
        """Run the agentic search & synthesis loop.

        Operational constraints:
        - Max 5 passes / iterations total.
        - Initial pass performs Tavily search based on user profile preferences.
        - Strict daily quota of max 10 Tavily searches per run.
        - Live search budget feedback to the model.
        - Forces brief synthesis on pass 5.
        """
        max_iterations = 5
        iteration = 0
        tavily_searches_used = 0
        max_tavily_searches = 6


        all_articles = context.get("articles", [])
        user_profile = context.get("user_profile") or get_user_profile(self.config)
        fetched_urls = set()
        search_queries = []
        model_memory = []

        # Perform initial search based on user_preferences summary
        pref_summary = user_profile.get("preferences_summary", "")
        initial_queries = []

        if pref_summary:
            import re
            # Extract key topic phrases by splitting on clauses, commas, and conjunctions
            raw_parts = [p.strip() for p in re.split(r'[,.;]|\b(?:and|also|focus on|with|including|prefers|tone|style)\b', pref_summary, flags=re.IGNORECASE) if p.strip()]
            for part in raw_parts:
                part_clean = part.strip()
                if len(part_clean) >= 3 and not any(w in part_clean.lower() for w in ["clear", "engaging", "tone", "style", "slang", "bullet", "format"]):
                    initial_queries.append(f"{part_clean} news today")
                if len(initial_queries) >= 3:
                    break

        if not initial_queries:
            initial_queries = ["top technology news today", "breaking news today"]

        print(f"[Briefing] Performing initial Tavily search for: {', '.join(initial_queries)}...")
        for q in initial_queries:
            if tavily_searches_used < max_tavily_searches:
                search_queries.append(q)
                tavily_searches_used += 1
                try:
                    results = await self.tavily.search(q, max_results=10)
                    all_articles.extend(results)
                except Exception as e:
                    print(f"[WARN] Tavily search error for '{q}': {e}")


        # Deduplicate by URL
        seen = set()
        unique = []
        for a in all_articles:
            if a.get("url") and a.get("url") not in seen:
                seen.add(a.get("url"))
                unique.append(a)
        all_articles = unique

        system_prompt = self._build_system_prompt(context, all_articles, user_profile)

        while iteration < max_iterations:
            iteration += 1
            searches_remaining = max_tavily_searches - tavily_searches_used

            status_msg = (
                f"Pass {iteration} of {max_iterations}:\n"
                f"- Tavily searches used so far: {tavily_searches_used}/{max_tavily_searches} "
                f"(Remaining budget: {searches_remaining})\n"
                f"- Total articles gathered so far: {len(all_articles)}\n"
                f"- URLs already fetched: {len(fetched_urls)}\n"
                f"- Previous search queries: {', '.join(search_queries)}\n"
            )

            if iteration == max_iterations:
                status_msg += "\n[FINAL PASS WARNING]: This is iteration 5 of 5. You MUST now call generate_brief with the complete, beautifully formatted markdown briefing based on all the articles provided and adopting the requested user persona/tone."

            model_memory.append({"role": "user", "content": status_msg})

            tools = [
                {
                    "function_declarations": [
                        {
                            "name": "search_tavily",
                            "description": f"Search Tavily for additional news articles. Maximum search budget is {max_tavily_searches} total searches per run.",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "queries": {
                                        "type": "ARRAY",
                                        "items": {"type": "STRING"},
                                        "description": "List of search queries to run on Tavily"
                                    }
                                },
                                "required": ["queries"]
                            }
                        },
                        {
                            "name": "fetch_url",
                            "description": "Fetch and scrape a specific URL to read its full content (up to 2000 words).",
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

            response = await self.gemini._chat(model_memory, system_prompt=system_prompt, tools=tools)

            candidates = response.get("candidates", [])
            if not candidates:
                break

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            model_memory.append({"role": "model", "content": ""})

            for part in parts:
                if "function_call" in part:
                    func = part["function_call"]
                    args = func.get("args", {})

                    if func["name"] == "search_tavily":
                        queries = args.get("queries", [])
                        search_results = []
                        quota_exceeded = False

                        for q in queries:
                            if tavily_searches_used >= max_tavily_searches:
                                quota_exceeded = True
                                break

                            search_queries.append(q)
                            tavily_searches_used += 1
                            results = await self.tavily.search(q, max_results=10)
                            search_results.extend(results)

                        all_articles.extend(search_results)
                        # Deduplicate by URL
                        seen = set()
                        unique = []
                        for a in all_articles:
                            if a.get("url") and a.get("url") not in seen:
                                seen.add(a.get("url"))
                                unique.append(a)
                        all_articles = unique

                        model_memory[-1]["content"] += f"[Searched queries ({len(queries)}): {', '.join(queries)}]\n"
                        model_memory[-1]["content"] += f"[Tavily quota used: {tavily_searches_used}/{max_tavily_searches}. New articles found: {len(search_results)}]\n"
                        if quota_exceeded:
                            model_memory[-1]["content"] += f"[NOTICE: Daily Tavily search limit of {max_tavily_searches} reached! No further search calls allowed.]\n"

                    elif func["name"] == "fetch_url":
                        urls = args.get("urls", [])
                        model_memory[-1]["content"] += f"[Fetched: {len(urls)} URLs]\n"
                        for url in urls:
                            if url not in fetched_urls:
                                fetched_urls.add(url)
                                scraped = await self.scrape_url(url)
                                model_memory[-1]["content"] += f"\n--- {url} ---\n{scraped[:500]}...\n"

                    elif func["name"] == "generate_brief":
                        brief = args.get("brief", "")
                        if brief and len(brief.strip()) > 100:
                            model_memory[-1]["content"] += f"\n[Brief generated successfully: {len(brief)} characters]"
                            return brief

                elif "text" in part:
                    text_content = part.get("text", "")
                    model_memory[-1]["content"] += text_content
                    if len(text_content.strip()) > 200 and "# Daily" in text_content:
                        return text_content.strip()

        if all_articles:
            prompt_context = context.copy()
            prompt_context["articles"] = all_articles
            prompt_context["user_profile"] = user_profile
            return await self.gemini.generate_brief(prompt_context)


        return self._fallback_brief(context, all_articles)

    def _build_system_prompt(self, context: dict, articles: list[dict] | None = None,
                             user_profile: dict | None = None) -> str:
        """Build the system prompt for the briefing loop with IST datetime and profile context."""
        from datetime import datetime, timezone, timedelta

        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_tz)
        ist_time_str = now_ist.strftime("%Y-%m-%d (%A) %H:%M IST")

        profile = user_profile or context.get("user_profile") or get_user_profile(self.config)
        events = context.get("events", [])
        articles_list = articles or []

        formatted_articles = ""
        if articles_list:
            formatted_articles = "ARTICLES FETCHED SO FAR:\n"
            for i, a in enumerate(articles_list[:15], 1):
                title = a.get("title", "Untitled")
                url = a.get("url", "")
                snippet = a.get("content", "")[:250]
                formatted_articles += f"{i}. [{title}]({url})\n   Snippet: {snippet}\n\n"

        return f"""You are an AI daily news briefer called DailyBriefer. Your job is to synthesize an engaging, informative daily news briefing for {context.get('user_name', 'the user')}.

CURRENT IST TIME & DATE:
{ist_time_str}

ABOUT THE USER:
{profile.get('about_user', 'No data recorded yet.')}

USER PREFERENCES & STYLE SUMMARY (MAX 200 WORDS):
{profile.get('preferences_summary', 'Focus on general world news, technology, AI breakthroughs, and major global events. Clear, engaging tone.')}

UPCOMING EVENTS & REMINDERS:
{json.dumps(events, indent=2) if events else "No upcoming events registered."}

{formatted_articles}

OPERATIONAL CONSTRAINTS & INSTRUCTIONS:
1. Review the articles and user preferences/style provided above. Strictly adopt the user's requested persona, tone, and style (e.g. GenZ slang, grumpy old man, formal executive, concise bullet points) when writing the briefing!
2. If you need more specific details on a URL, call `fetch_url`. If you need more search results on a specific topic, call `search_tavily`.
3. Tavily Search Quota: You have a strict limit of MAX 6 Tavily searches total per briefing run. Manage your query count carefully.
4. Max 5 Iterations: You have at most 5 turns/passes. Call `generate_brief(brief=...)` with the full markdown text.
5. Brief Formatting: Write a rich, engaging Markdown brief with sections, bullet points, headers, clickable article links `[Title](url)`, and emojis. Always include an "Upcoming Events / Reminders" section if there are events for today or nearby."""

    def _fallback_brief(self, context: dict, articles: list[dict]) -> str:
        """Generate a brief even if the loop didn't complete normally."""
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
        """Process a user reply email and update living memory profile per sender email.

        Returns (reply_text, changes_applied).
        """
        import re
        raw_from = email.get("from", "")
        match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', raw_from)
        sender_email = match.group(0).lower() if match else self.config.gmail_address

        current_profile = get_user_profile(self.config, user_email=sender_email)
        current_events = get_all_events(self.config)

        # Let Gemini process the reply and update memory summaries
        result = await self.gemini.process_reply(
            email["subject"],
            email["body"],
            current_profile,
            current_events,
        )

        updated_prefs = result.get("updated_user_preferences")
        updated_about = result.get("updated_about_user")
        if updated_prefs or updated_about:
            update_user_profile(
                self.config,
                updated_prefs or current_profile["preferences_summary"],
                updated_about or current_profile["about_user"],
                user_email=sender_email,
            )

        event_action = result.get("event_action")
        if isinstance(event_action, dict):
            action_type = event_action.get("action")
            if action_type in ("add", "add_event"):
                add_event(self.config, event_action.get("date", ""), event_action.get("description", ""))
            elif action_type in ("remove", "remove_event") and event_action.get("event_id"):
                remove_event(self.config, event_action["event_id"])

        save_reply(
            self.config,
            email["subject"],

            email["body"],
            json.dumps(result),
        )

        reply_text = result.get("reply_text", "Got it! Updated your briefing preferences.")
        return reply_text, result

    async def run_daily_briefing(self) -> dict:
        """Run the full daily briefing process for all registered users."""
        from datetime import datetime, timezone

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        user_profiles = get_all_user_profiles(self.config)
        events = get_all_events(self.config)

        delivered_count = 0
        for profile in user_profiles:
            target_email = profile.get("user_email", self.config.gmail_address)
            context = {
                "date": date,
                "user_name": self.config.brief_name,
                "user_profile": profile,
                "events": events,
                "articles": [],
            }

            print(f"[Briefing] Generating brief for user: {target_email}...")
            brief_content = await self.run_briefing_loop(context)

            # Save brief to DB
            save_brief_record(
                self.config,
                date,
                brief_content,
                [{"preferences_summary": profile["preferences_summary"], "about_user": profile["about_user"]}],
                email_sent_at=datetime.now(timezone.utc).isoformat(),
            )

            success = await self.send_brief_email(brief_content, to_email=target_email)
            if success:
                delivered_count += 1

        # Deliver any pending events
        pending = get_pending_events(self.config)
        delivered_events = []
        for event in pending:
            mark_event_delivered(self.config, event["id"])
            delivered_events.append(event)

        result = {
            "date": date,
            "brief_saved": True,
            "users_count": len(user_profiles),
            "delivered_count": delivered_count,
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
            print(f"[Briefing] Brief process completed for {result.get('users_count', 1)} users")
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
                print(f"[Reply] Sent to {email['from']}: {reply_text}")
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
                print(f"[Reply] Sent to {email['from']}: {reply_text}")
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
                    print(f"[Reply] Sent to {email['from']}: {reply_text}")
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
            print(f"[Reply] Sent to {email['from']}: {reply_text}")
        else:
            print("[Briefing] Running daily briefing...")
            result = await self.run_daily_briefing()
            print(f"[Briefing] Daily brief process completed for {result.get('users_count', 1)} users")

    async def send_brief_email(self, brief_content: str | None = None, to_email: str | None = None) -> bool:
        """Send the latest brief via HTML email."""
        from datetime import datetime, timezone
        from daily_briefer.formatter import format_brief_html

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        target_recipient = (to_email or self.config.gmail_address).strip().lower()

        if brief_content is None:
            # Read from Supabase
            brief_content = get_brief_by_date(self.config, date)
            if not brief_content:
                brief_content = f"# Daily Briefing — {date}\n\nNo brief available."

        html_body = format_brief_html(brief_content)

        success = await self.gmail.send_email(
            to=target_recipient,
            subject=f"Daily Brief — {date}",
            body=html_body,
        )

        if success:
            # Mark email as sent in Supabase
            set_brief_sent(self.config, date)

        return success



