"""Supabase database backend for preferences, events, and reply history."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from typing import Any, Generator

from daily_briefer.config import Config


def init_db(config: Config) -> None:
    """No-op for Supabase — tables are created via schema.sql."""
    pass


def _client(config: Config):
    """Get or create a Supabase client."""
    from supabase import create_client, Client
    return create_client(config.supabase_url, config.supabase_key)


# --- User Preferences ---

def add_preference(config: Config, keyword: str, weight: int = 5) -> bool:
    """Add or increment a preference keyword (case-insensitive)."""
    client = _client(config)
    row = client.table("user_preferences").select("id, keyword, weight").execute()
    prefs = row.data if row.data else []

    for rec in prefs:
        if rec["keyword"].lower() == keyword.lower():
            new_weight = max(rec["weight"] + weight, weight)
            client.table("user_preferences").update({
                "weight": new_weight,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", rec["id"]).execute()
            return True

    client.table("user_preferences").insert({
        "keyword": keyword,
        "weight": weight,
    }).execute()
    return True


def remove_preference(config: Config, keyword: str) -> None:
    """Remove a preference keyword (case-insensitive)."""
    client = _client(config)
    row = client.table("user_preferences").select("id, keyword").execute()
    prefs = row.data if row.data else []

    for rec in prefs:
        if rec["keyword"].lower() == keyword.lower():
            client.table("user_preferences").delete().eq("id", rec["id"]).execute()
            break


def get_preferences(config: Config) -> list[dict]:
    client = _client(config)
    row = client.table("user_preferences").select("keyword, weight").order(
        "weight", desc=True
    ).execute()
    return row.data if row.data else []


def get_top_keywords(config: Config, n: int = 20) -> list[str]:
    rows = get_preferences(config)
    return [r["keyword"] for r in rows[:n]]


def list_all_preferences(config: Config) -> list[dict]:
    return get_preferences(config)


# --- Events ---

def add_event(config: Config, date: str, description: str) -> int:
    """Add an event reminder. Returns event id."""
    client = _client(config)
    row = client.table("events").insert({
        "date": date,
        "description": description,
        "status": "pending",
    }).execute()
    return row.data[0]["id"] if row.data else 0


def remove_event(config: Config, event_id: int) -> None:
    client = _client(config)
    client.table("events").delete().eq("id", event_id).execute()


def get_pending_events(config: Config) -> list[dict]:
    """Get events scheduled for today or earlier that haven't been delivered."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = _client(config)
    row = client.table("events").select("id, date, description").match(
        {"status": "pending"}
    ).lte("date", today).order("date", desc=False).execute()
    return row.data if row.data else []


def get_upcoming_events(config: Config, n: int = 30) -> list[dict]:
    """Get upcoming events."""
    client = _client(config)
    row = client.table("events").select("id, date, description, status").match(
        {"status": "pending"}
    ).order("date", desc=False).limit(n).execute()
    return row.data if row.data else []


def mark_event_delivered(config: Config, event_id: int) -> None:
    client = _client(config)
    client.table("events").update({"status": "delivered"}).eq(
        "id", event_id
    ).execute()


def mark_event_expired(config: Config, event_id: int) -> None:
    client = _client(config)
    client.table("events").update({"status": "expired"}).eq(
        "id", event_id
    ).execute()


def get_all_events(config: Config) -> list[dict]:
    """Get all events for the model to see context."""
    client = _client(config)
    row = client.table("events").select("id, date, description, status").order(
        "date", desc=False
    ).execute()
    return row.data if row.data else []


def cleanup_old_events(config: Config) -> int:
    """Delete events that are past their date and already delivered/expired."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = _client(config)
    deleted = 0
    # Delete delivered events older than today
    resp = client.table("events").delete().match(
        {"status": "delivered"}
    ).lt("date", today).execute()
    deleted += len(resp.data) if resp.data else 0
    # Also delete expired events
    resp = client.table("events").delete().match(
        {"status": "expired"}
    ).lt("date", today).execute()
    deleted += len(resp.data) if resp.data else 0
    return deleted


# --- Briefs ---

def save_brief_record(config: Config, date: str, brief_content: str,
                      preferences_snapshot: list[dict] | None = None,
                      email_sent_at: str | None = None) -> int:
    import json
    snap_json = json.dumps(preferences_snapshot) if preferences_snapshot else None
    client = _client(config)

    # Upsert
    row = client.table("briefs").upsert({
        "date": date,
        "email_sent_at": email_sent_at,
        "preferences_snapshot": snap_json,
        "brief_content": brief_content,
    }, on_conflict="date").execute()
    return row.data[0]["id"] if row.data else 0


def get_recent_briefs(config: Config, n: int = 7) -> list[dict]:
    client = _client(config)
    row = client.table("briefs").select("date, email_sent_at, preferences_snapshot").order(
        "date", desc=True
    ).limit(n).execute()
    return row.data if row.data else []


def get_brief_by_date(config: Config, date: str) -> str | None:
    """Get brief content for a given date."""
    client = _client(config)
    row = client.table("briefs").select("brief_content").eq("date", date).limit(1).execute()
    if row.data and len(row.data) > 0:
        return row.data[0].get("brief_content")
    return None


def set_brief_sent(config: Config, date: str) -> None:
    """Mark a brief as sent."""
    from datetime import datetime, timezone
    client = _client(config)
    client.table("briefs").update({"email_sent_at": datetime.now(timezone.utc).isoformat()}).eq(
        "date", date
    ).execute()


def cleanup_old_briefs(config: Config) -> int:
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=config.brief_retention_days)).strftime("%Y-%m-%d")
    client = _client(config)
    resp = client.table("briefs").delete().lt("date", cutoff_date).execute()
    return len(resp.data) if resp.data else 0


# --- Reply History ---

def save_reply(config: Config, subject: str, body: str, changes: str) -> None:
    client = _client(config)
    client.table("reply_history").insert({
        "email_subject": subject,
        "email_body": body,
        "changes_applied": changes,
    }).execute()


def get_recent_replies(config: Config, n: int = 10) -> list[dict]:
    client = _client(config)
    row = client.table("reply_history").select("id, email_subject, processed_at").order(
        "processed_at", desc=True
    ).limit(n).execute()
    return row.data if row.data else []


# --- User Profile (Self-Improving Memory) ---

DEFAULT_PREFERENCES_SUMMARY = (
    "Focus on general world news, technology, AI breakthroughs, and major global events. Clear, engaging tone."
)
DEFAULT_ABOUT_USER = "No data recorded yet."


def get_all_user_profiles(config: Config) -> list[dict]:
    """Get all registered user profiles from user_profile table."""
    try:
        client = _client(config)
        res = client.table("user_profile").select("user_email, preferences_summary, about_user").execute()
        if res.data and len(res.data) > 0:
            profiles = []
            for row in res.data:
                email_val = row.get("user_email")
                if email_val:
                    profiles.append({
                        "user_email": email_val.strip().lower(),
                        "preferences_summary": row.get("preferences_summary") or DEFAULT_PREFERENCES_SUMMARY,
                        "about_user": row.get("about_user") or DEFAULT_ABOUT_USER,
                    })
            if profiles:
                return profiles
    except Exception as e:
        print(f"[DB WARN] Could not fetch all user_profile rows: {e}")

    # Default fallback profile using config email
    default_email = (config.gmail_address or "default").strip().lower()
    default_prof = get_user_profile(config, user_email=default_email)
    return [default_prof]



def get_user_profile(config: Config, user_email: str | None = None) -> dict:
    """Get the living user profile summary for a specific user_email (with fallbacks)."""
    target_email = (user_email or config.gmail_address or "default").strip().lower()

    try:
        client = _client(config)
        row = client.table("user_profile").select("user_email, preferences_summary, about_user").eq("user_email", target_email).limit(1).execute()
        if row.data and len(row.data) > 0:
            rec = row.data[0]
            return {
                "user_email": target_email,
                "preferences_summary": rec.get("preferences_summary") or DEFAULT_PREFERENCES_SUMMARY,
                "about_user": rec.get("about_user") or DEFAULT_ABOUT_USER,
            }
        
        # Try checking id=1 for backwards compatibility with single-user schema
        try:
            row_id = client.table("user_profile").select("preferences_summary, about_user").eq("id", 1).limit(1).execute()
            if row_id.data and len(row_id.data) > 0:
                rec = row_id.data[0]
                return {
                    "user_email": target_email,
                    "preferences_summary": rec.get("preferences_summary") or DEFAULT_PREFERENCES_SUMMARY,
                    "about_user": rec.get("about_user") or DEFAULT_ABOUT_USER,
                }
        except Exception:
            pass
    except Exception as e:
        print(f"[DB WARN] Could not fetch user_profile for '{target_email}': {e}")


    # Fallback to user_preferences table
    try:
        legacy_prefs = get_preferences(config)
        if legacy_prefs:
            stored_about = DEFAULT_ABOUT_USER
            stored_pref = ""
            keywords = []
            for p in legacy_prefs:
                kw = p.get("keyword", "")
                if kw.startswith("__profile_about__:"):
                    stored_about = kw.replace("__profile_about__:", "")
                elif kw.startswith("__profile_prefs__:"):
                    stored_pref = kw.replace("__profile_prefs__:", "")
                else:
                    keywords.append(kw)

            if stored_pref:
                return {"user_email": target_email, "preferences_summary": stored_pref, "about_user": stored_about}
            if keywords:
                combined = ", ".join(keywords)
                return {"user_email": target_email, "preferences_summary": f"Focus on: {combined}", "about_user": stored_about}
    except Exception as e:
        print(f"[DB WARN] Could not fetch fallback preferences: {e}")

    return {
        "user_email": target_email,
        "preferences_summary": DEFAULT_PREFERENCES_SUMMARY,
        "about_user": DEFAULT_ABOUT_USER,
    }


def update_user_profile(config: Config, preferences_summary: str, about_user: str, user_email: str | None = None) -> bool:
    """Upsert living user profile summary for a specific user_email."""
    target_email = (user_email or config.gmail_address or "default").strip().lower()
    pref_clean = preferences_summary.strip()
    about_clean = about_user.strip()

    try:
        client = _client(config)
        # Try upserting with user_email as primary key
        client.table("user_profile").upsert({
            "user_email": target_email,
            "preferences_summary": pref_clean,
            "about_user": about_clean,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_email").execute()
        return True
    except Exception as e:
        print(f"[DB WARN] Failed to update user_profile with user_email, trying id=1 fallback: {e}")

    try:
        client = _client(config)
        client.table("user_profile").upsert({
            "id": 1,
            "preferences_summary": pref_clean,
            "about_user": about_clean,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="id").execute()
        return True
    except Exception as e:
        print(f"[DB WARN] Failed id=1 upsert, using user_preferences fallback: {e}")

    # Fallback: Save to user_preferences table
    try:
        add_preference(config, f"__profile_prefs__:{pref_clean}")
        add_preference(config, f"__profile_about__:{about_clean}")
        return True
    except Exception as e:
        print(f"[DB ERROR] Failed fallback update: {e}")
        return False



