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
        """Generate a daily news brief based on context with strict persona and style enforcement."""
        profile = context.get("user_profile") or {}
        events = context.get("events", [])
        date = context.get("date", "")

        pref_summary = profile.get("preferences_summary", "Focus on general world news and tech.")
        about_user = profile.get("about_user", "No data recorded yet.")

        system_prompt = f"""You are DailyBriefer AI, a personalized news briefer. Generate a daily news briefing for {context.get('user_name', 'the user')} for date {date}.

CRITICAL PERSONA & TONE REQUIREMENT:
You MUST write the ENTIRE news briefing strictly adhering to the persona, tone, writing style, and slang specified in USER PREFERENCES & STYLE SUMMARY below. 
- If the user requested GenZ tone/slang, use heavy GenZ slang throughout (e.g. "no cap", "fr fr", "bet", "cooked", "slays", "bussin", "vibe check", "main character energy", "real ones know").
- If the user requested a grumpy old man tone, adopt a crusty, opinionated old-school voice.
- Whatever style is requested in USER PREFERENCES & STYLE SUMMARY, apply it 100% committed from start to finish!

ABOUT THE USER:
{about_user}

USER PREFERENCES & STYLE SUMMARY (MAX 200 WORDS):
{pref_summary}

UPCOMING EVENTS & REMINDERS:
{json.dumps(events, indent=2) if events else "None"}

SEARCH RESULTS / ARTICLES FETCHED TODAY:
{json.dumps(context.get('articles', []), indent=2)}

BRIEFING FORMAT INSTRUCTIONS:
1. Write a rich, engaging Markdown brief with sections, bullet points, headers, clickable article links `[Title](url)`, and emojis.
2. Maintain the requested persona consistently across all section titles, summaries, and commentary.
3. Include an "Upcoming Events / Reminders" section if there are events."""


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

    async def analyze_email_intent(self, email_subject: str, email_body: str) -> dict:
        """Analyze email subject and body to classify intent and filter spam/junk."""
        system_prompt = """You are an email intent classifier and spam filter for an AI daily news briefer.
Your job is to determine whether an incoming email is a legitimate user request/reply vs. spam, automated junk, or irrelevant system notifications.

LEGITIMATE REQUESTS (is_valid_request = true):
- User giving news topic feedback ("show me tech news", "no politics", "add PC building").
- User specifying writing style/persona ("explain like GenZ", "grumpy old man", "formal executive").
- User asking for a news briefing or replying to a daily brief.
- User adding or removing event reminders.
- Human user sending a genuine message, greeting, or question.

SPAM / AUTOMATED JUNK / IRRELEVANT (is_valid_request = false):
- Automated marketing emails, promotional blasts, cold sales emails.
- Security login alerts (Google, GitHub, etc.), verification codes, password reset emails.
- Bounce notifications, delivery failure alerts, out-of-office auto-replies.
- Phishing, financial scams, crypto spam, random non-human system alerts.

Respond ONLY with raw JSON:
{
    "is_valid_request": true | false,
    "reason": "brief explanation"
}"""

        user_message = {
            "role": "user",
            "content": f"Subject: {email_subject}\nBody: {email_body[:1000]}"
        }

        try:
            response = await self._chat([user_message], system_prompt=system_prompt)
            candidates = response.get("candidates", [])
            if not candidates:
                return {"is_valid_request": True, "reason": "Default allow"}

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()

            if text.startswith("```"):
                lines = [l for l in text.split("\n") if not l.startswith("```")]
                text = "\n".join(lines).strip()

            return json.loads(text)
        except Exception as e:
            print(f"[WARN] Intent classification error: {e}")
            return {"is_valid_request": True, "reason": "Fallback allow"}


