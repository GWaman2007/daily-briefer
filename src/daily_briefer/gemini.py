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

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    async def _chat(self, messages: list[dict], system_prompt: str = "",
                    tools: list[dict] | None = None, max_retries: int = 3) -> dict:
        """Send a chat message to Gemini and return the response."""
        for attempt in range(max_retries):
            try:
                contents = []
                if system_prompt:
                    contents.append({
                        "role": "user",
                        "parts": [{"text": system_prompt}],
                    })
                for msg in messages:
                    contents.append({
                        "role": msg.get("role", "user"),
                        "parts": [{"text": msg.get("content", "")}],
                    })

                payload = {
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "top_k": 40,
                    },
                }
                if tools:
                    payload["tools"] = tools

                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        self.base_url,
                        params={"key": self.api_key},
                        json=payload,
                    )
                    resp.raise_for_status()
                    return resp.json()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await httpx.AsyncClient().aclose()
                await httpx.AsyncClient().aclose()
                import asyncio
                await asyncio.sleep(2 ** attempt)

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
                            current_prefs: list[dict],
                            current_events: list[dict]) -> dict:
        """Process a user reply email and determine what changes to make.

        Returns a dict with keys:
        - action: 'add_pref', 'remove_pref', 'add_event', 'remove_event', or 'ack'
        - details: dict with additional info
        - reply_text: what to send back to the user
        """
        system_prompt = f"""You are analyzing a user's reply to their daily news briefing email.
The user wants you to extract actions to update their news preferences and reminders.

Current preferences:
{json.dumps(current_prefs, indent=2)}

Current events/reminders:
{json.dumps(current_events, indent=2) if current_events else "None"}

Email subject: {email_subject}
Email body: {email_body}

Your task:
1. Analyze the email content for:
   - New topics/interests the user wants to follow (add to preferences)
   - Topics to remove from preferences
   - New events/reminders (with dates)
   - Events/reminders to cancel
   - Or just a simple acknowledgment

2. Respond with EXACTLY a JSON object (no markdown, no explanations, just raw JSON):
{{
    "action": "add_pref" | "remove_pref" | "add_event" | "remove_event" | "ack",
    "keyword": "the topic keyword",
    "event_id": 123,
    "event_date": "YYYY-MM-DD",
    "event_description": "what to watch for",
    "reply_text": "a friendly, conversational reply to the user"
}}

Examples:
- User says "I love AI news" → {{"action": "add_pref", "keyword": "AI", "reply_text": "Got it! I'll add AI to your interests. Expect more AI news in future briefings!"}}
- User says "Stop sending crypto news" → {{"action": "remove_pref", "keyword": "crypto", "reply_text": "Understood. I've removed crypto from your interests."}}
- User says "Watch for World Cup final on 2025-06-25, send me highlights" → {{"action": "add_event", "event_date": "2025-06-25", "event_description": "World Cup final highlights", "reply_text": "I'll keep an eye on the World Cup final on June 25th and send you highlights!"}}
- User says "Cancel the World Cup reminder" → {{"action": "remove_event", "event_id": 42, "reply_text": "Reminder cancelled."}}
- User says "Thanks!" → {{"action": "ack", "reply_text": "Happy to help! Enjoy the rest of your day."}}

Respond with ONLY valid JSON. Nothing else."""

        user_message = {
            "role": "user",
            "content": "Analyze this email and determine what action to take."
        }

        context = f"""Current preferences:
{json.dumps(current_prefs)}

Current events:
{json.dumps(current_events)}"""

        response = await self._chat([user_message], system_prompt=system_prompt + "\n\n" + context)

        # Extract and parse JSON from response
        candidates = response.get("candidates", [])
        if not candidates:
            return {"action": "ack", "reply_text": "I didn't understand that. Could you clarify?"}

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        text = ""
        for part in parts:
            text += part.get("text", "")

        # Try to extract JSON from the response
        try:
            # Gemini might wrap JSON in markdown code blocks
            text = text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                text = "\n".join(lines)

            result = json.loads(text)
            return result
        except json.JSONDecodeError:
            return {"action": "ack", "reply_text": "I'm sorry, I had trouble understanding that. Could you try rephrasing?"}
