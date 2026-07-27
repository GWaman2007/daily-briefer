-- Schema for DailyBriefer

-- User Profile (Living memory summary per user email)
CREATE TABLE IF NOT EXISTS user_profile (
    user_email TEXT PRIMARY KEY,
    preferences_summary TEXT NOT NULL DEFAULT 'Focus on general world news and major global events. Clear, engaging, neutral tone.',
    about_user TEXT NOT NULL DEFAULT 'No data recorded yet.',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Legacy Preferences (topics/keywords with weights)
CREATE TABLE IF NOT EXISTS user_preferences (
    id SERIAL PRIMARY KEY,
    keyword TEXT UNIQUE NOT NULL,
    weight FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sent Briefs History
CREATE TABLE IF NOT EXISTS briefs (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    content TEXT NOT NULL,
    preferences_snapshot JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    email_sent_at TIMESTAMPTZ
);

-- Upcoming Events & Reminders
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    description TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    is_delivered BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User Reply Log
CREATE TABLE IF NOT EXISTS user_replies (
    id SERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    subject TEXT,
    body TEXT NOT NULL,
    actions_taken JSONB,
    ai_response TEXT
);
