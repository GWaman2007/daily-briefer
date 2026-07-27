"""Gemini API integration for self-improvement and brief generation."""
from __future__ import annotations

import json
import httpx
from typing import Any

from daily_briefer.config import Config
from daily_briefer.db import (
    get_preferences,
    add_preference,
    remove_preference,
    add_event,
    remove_event,
    list_all_preferences,
    get_all_events,
)


class GeminiClient:
    """Client for Google Gemini API."""

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash-lite",
                 fallback_model: str = "gemini-3.1-flash-lite"):
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model
        self.base_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )

    async def _chat(self, messages: list[dict], system_prompt: str = "",
                    tools: list[dict] | None = None, max_retries: int = 3,
                    use_fallback: bool = False) -> dict:
        """Send a chat message to Gemini and return the response.

        On HTTP 429 (rate limit) falls back to ``fallback_model`` after one
        attempt with the primary model.
        """
        import asyncio

        url = self.base_url
        attempts = 0
        did_fallback = False
        delay = 2

        while True:
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        url,
                        params={"key": self.api_key},
                        json={
                            "contents": (
                                [{"role": "user", "parts": [{"text": system_prompt}]}]
                                if system_prompt else []
                            )
                            + [
                                {"role": msg.get("role", "user"), "parts": [{"text": msg.get("content", "")}]}
                                for msg in messages
                            ],
                            "generationConfig": {"temperature": 0.7, "top_p": 0.9, "top_k": 40},
                            **({"tools": tools} if tools else {}),
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()

            except httpx.HTTPStatusError as exc:
                attempts += 1

                # 429 → fall back to the other model once
                if exc.response.status_code == 429 and not did_fallback and self.fallback_model:
                    did_fallback = True
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{self.fallback_model}:generateContent"
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue

                # Retry transient server errors (5xx)
                if exc.response.status_code >= 500 and attempts < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue

                raise

            except Exception:
                attempts += 1
                if attempts < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise

    async def generate_brief(self, context: dict) -> str:
        """Generate a daily news brief based on context."""
        preferences = context.get("preferences", [])
        events = context.get("events", [])
        date = context.get("date", "")

        system_prompt = f"""You are an AI news briefer. Generate a concise daily news briefing for {context.get('user_name', 'the user')} for {date}.

Current user preferences (topics they follow):
{json.dumps(preferences, indent=2)}

Upcoming events/reminders:
{json.dumps(events, indent=2) if events else "None"}

Search results from Tavily (already fetched):
{json.dumps(context.get('articles', []), indent=2)}

Instructions:
1. Write a clear, engaging news briefing in markdown format.
2. Include only the most relevant and interesting articles based on user preferences.
3. Add a section for any upcoming events/reminders for today.
4. Keep it concise — no more than 1000 words.
5. Use headings, bullet points, and emojis to make it readable."""

        user_message = {
            "role": "user",
            "content": "Please generate today's news briefing based on the context above."
        }

        response = await self._chat([user_message], system_prompt=system_prompt)

        # Extract text from response
        candidates = response.get("candidates", [])
        if not candidates:
            return "No brief generated. Please check your API key and try again."

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        text = ""
        for part in parts:
            text += part.get("text", "")

        return text.strip()

    async def process_reply(self, email_subject: str, email_body: str,
                            current_profile: dict,
                            current_events: list[dict]) -> dict:
        """Process a user reply email and self-update living memory summaries.

        Returns dict with keys:
        - updated_user_preferences: string (max 200 words)
        - updated_about_user: string (max 200 words)
        - event_action: dict or null (e.g. {"action": "add", "date": "YYYY-MM-DD", "description": "..."})
        - reply_text: friendly email confirmation text
        """
        current_prefs = current_profile.get("preferences_summary", "")
        current_about = current_profile.get("about_user", "")

        system_prompt = f"""You are an AI memory manager for DailyBriefer.
You analyze user email replies to update the user's living profile memory.

CURRENT USER PREFERENCES & STYLE SUMMARY (MAX 200 WORDS):
{current_prefs}

CURRENT ABOUT USER PROFILE (MAX 200 WORDS):
{current_about}

CURRENT EVENTS & REMINDERS:
{json.dumps(current_events, indent=2) if current_events else "None"}

INCOMING USER EMAIL:
Subject: {email_subject}
Body: {email_body}

YOUR TASK:
1. Analyze the email body for:
   - Topic interests, writing style, tone preferences (e.g., GenZ slang, grumpy old man, concise, formal).
   - Personal facts about the user (e.g., role, location, habits, background).
   - Event reminders to add or cancel (with target dates).
2. Update `updated_user_preferences` (string, MUST be <= 200 words). Add new topics/styles, prune/drop outdated choices if reaching length limits.
3. Update `updated_about_user` (string, MUST be <= 200 words). Add new background facts, keep concise.
4. Craft a warm, conversational `reply_text` written in the user's requested persona/tone.

Respond with EXACTLY a raw JSON object (no markdown formatting, no explanations):
{{
    "updated_user_preferences": "the full updated preferences & style summary string (max 200 words)",
    "updated_about_user": "the full updated about user summary string (max 200 words)",
    "event_action": null | {{"action": "add_event" | "remove_event", "date": "YYYY-MM-DD", "description": "...", "event_id": 123}},
    "reply_text": "friendly reply to send back to user in their requested persona/tone"
}}"""

        user_message = {
            "role": "user",
            "content": "Analyze the incoming email and output the updated memory JSON."
        }

        response = await self._chat([user_message], system_prompt=system_prompt)

        candidates = response.get("candidates", [])
        if not candidates:
            return {
                "updated_user_preferences": current_prefs,
                "updated_about_user": current_about,
                "event_action": None,
                "reply_text": "Got it! Thanks for your email.",
            }

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        text = ""
        for part in parts:
            text += part.get("text", "")

        try:
            text = text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                text = "\n".join(lines)

            result = json.loads(text)
            return result
        except json.JSONDecodeError:
            return {
                "updated_user_preferences": current_prefs,
                "updated_about_user": current_about,
                "event_action": None,
                "reply_text": "Understood! Updated your briefing preferences.",
            }

