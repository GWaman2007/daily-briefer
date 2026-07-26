# DailyBriefer 📰

An AI-powered, self-improving email-based daily news briefer. It learns your
interests from your replies, tracks your events/reminders, and delivers tailored
news briefings straight to your inbox.

## How It Works

1. **Daily brief** — fetched from multiple news sources, summarized by Gemini,
   emailed to you personalized to your interests
2. **Reply to improve** — just reply to the brief email:
   - _"I like AI news"_ → adds "AI" to your interests
   - _"Remove sports"_ → removes "sports" from your interests
3. **Set reminders** — the briefer watches for events you care about:
   - _"Watch for 25th June World Cup final, send me highlights"_
   - On that date, highlights are included in your brief
   - After the event, the reminder is auto-cleaned up
4. **Self-improving** — every reply updates your profile for tomorrow's brief

## Setup

```bash
# 1. Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -e .

# 3. Copy and edit the env file
cp .env.example .env
# Edit .env with your Gmail app password + Gemini API key
```

### Gmail Setup (App Password)

You need an **App Password**, not your regular password:
1. Go to https://myaccount.google.com/apppasswords
2. Create a new app password (name it "DailyBriefer")
3. Copy the 16-character password into `.env`

### Gemini API Key

1. Go to https://aistudio.google.com/apikey
2. Create an API key
3. Paste it into `.env`

## Usage

```bash
# Generate and send today's brief
daily-briefer brief

# Watch for new emails and process replies
daily-briefer watch

# Show current preferences
daily-briefer prefs

# Show upcoming events/reminders
daily-briefer events

# Add a preference manually
daily-briefer add-preference "AI"

# Remove a preference manually
daily-briefer remove-preference "sports"

# Add a reminder manually
daily-briefer add-event "2026-06-25" "World Cup Final highlights"

# Remove an event manually
daily-briefer remove-event 1
```

## Deployment (Render)

This project supports Docker-based deployment on Render (free tier):

1. Push to GitHub
2. Connect repo on Render
3. Add the `DATABASE_URL` and environment variables from `.env`
4. Deploy

The Dockerfile and Procfile are included.

## News Sources

Built-in sources: Hacker News, TechCrunch, Ars Technica, The Verge.
Add more by editing the `NEWS_SOURCES` list in `config.py`.
