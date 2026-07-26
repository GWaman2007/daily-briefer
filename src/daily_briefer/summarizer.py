from __future__ import annotations

import textwrap

from openai import AsyncOpenAI

from daily_briefer.config import Settings


class Summarizer:
    """Wraps an OpenAI-compatible API to summarize articles."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.openai_base_url, api_key=settings.openai_api_key
        )
        self._model = settings.summarizer_model
        self._max_tokens = settings.max_summary_tokens

    async def summarize_articles(
        self, title: str, descriptions: list[str]
    ) -> str:
        """Summarize multiple article descriptions into a short briefing."""
        joined = "\n".join(f"- {d}" for d in descriptions)
        prompt = textwrap.dedent(
            f"""\
            You are a news editor preparing a daily briefing for a technical professional.
            Summarize the following articles about "{title}" concisely in 2-4 bullet points.
            Each bullet should be one sentence, capturing the key insight.

            Articles:
            {joined}

            Return ONLY the bullet points, nothing else."""
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self._max_tokens,
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            return f"[Summarization failed: {exc}]"
