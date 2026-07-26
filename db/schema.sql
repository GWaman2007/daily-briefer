-- DailyBriefer Supabase Schema
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS user_preferences (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    keyword TEXT UNIQUE NOT NULL,
    weight INTEGER DEFAULT 5,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS briefs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date TEXT UNIQUE NOT NULL,
    email_sent_at TIMESTAMPTZ,
    preferences_snapshot TEXT,
    brief_content TEXT
);

CREATE TABLE IF NOT EXISTS reply_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email_subject TEXT NOT NULL,
    email_body TEXT NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    changes_applied TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_preferences_weight ON user_preferences(weight DESC);
CREATE INDEX IF NOT EXISTS idx_events_date_status ON events(date, status);
CREATE INDEX IF NOT EXISTS idx_briefs_date ON briefs(date);
