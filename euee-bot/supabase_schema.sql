-- ============================================================================
-- SUPABASE SCHEMA FOR EUEE ABEBE BOT
-- Run this in your Supabase SQL Editor
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- 1. USERS TABLE (Main student accounts)
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT 'Student',
    language TEXT DEFAULT 'en',
    tier TEXT DEFAULT 'free' CHECK (tier IN ('free', 'pro', 'max')),
    subscription_active BOOLEAN DEFAULT TRUE,
    subscription_expires_at TIMESTAMPTZ,
    subscription_expired_at TIMESTAMPTZ,
    tier_updated_at TIMESTAMPTZ DEFAULT NOW(),
    streak INTEGER DEFAULT 0,
    streak_freezes INTEGER DEFAULT 0,
    last_active_date DATE,
    questions_today INTEGER DEFAULT 0,
    questions_total INTEGER DEFAULT 0,
    questions_this_week INTEGER DEFAULT 0,
    week_start DATE,
    study_minutes_today INTEGER DEFAULT 0,
    study_minutes_total INTEGER DEFAULT 0,
    score_by_subject JSONB DEFAULT '{}',
    subject_correct JSONB DEFAULT '{}',
    subject_wrong JSONB DEFAULT '{}',
    subject_attempts JSONB DEFAULT '{}',
    topic_performance JSONB DEFAULT '{}',
    correct_total INTEGER DEFAULT 0,
    wrong_total INTEGER DEFAULT 0,
    exams_taken INTEGER DEFAULT 0,
    badges JSONB DEFAULT '[]',
    parent_token TEXT UNIQUE DEFAULT uuid_generate_v4()::text,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    last_question_date DATE,
    last_explanation TEXT DEFAULT '',
    chosen_subject TEXT DEFAULT 'math',
    last_predict_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for users
CREATE INDEX IF NOT EXISTS idx_users_tier ON users(tier);
CREATE INDEX IF NOT EXISTS idx_users_parent_token ON users(parent_token);
CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active_date);

-- ============================================================================
-- 2. PAYMENT ATTEMPTS TABLE (Payment verification)
-- ============================================================================
CREATE TABLE IF NOT EXISTS payment_attempts (
    transaction_id TEXT PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    username TEXT,
    plan_requested TEXT NOT NULL,
    screenshot_url TEXT,
    status TEXT DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    amount INTEGER,
    source TEXT DEFAULT 'telebirr',
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    approved_by BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_status ON payment_attempts(status);
CREATE INDEX IF NOT EXISTS idx_payments_telegram_id ON payment_attempts(telegram_id);
CREATE INDEX IF NOT EXISTS idx_payments_submitted ON payment_attempts(submitted_at);

-- ============================================================================
-- 3. EXAM RESULTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS exam_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    percentage DECIMAL(5,2),
    weak_topics JSONB DEFAULT '[]',
    taken_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exam_results_telegram_id ON exam_results(telegram_id);
CREATE INDEX IF NOT EXISTS idx_exam_results_taken ON exam_results(taken_at);

-- ============================================================================
-- 4. CONFESSIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS confessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_confessions_telegram_id ON confessions(telegram_id);

-- ============================================================================
-- 5. BATTLES TABLE (Battle mode)
-- ============================================================================
CREATE TABLE IF NOT EXISTS battles (
    battle_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    challenger_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    opponent_id BIGINT REFERENCES users(telegram_id),
    subject TEXT NOT NULL,
    question TEXT NOT NULL,
    options JSONB NOT NULL,
    correct_answer TEXT NOT NULL,
    explanation TEXT,
    status TEXT DEFAULT 'waiting' CHECK (status IN ('waiting', 'active', 'done')),
    challenger_answer TEXT,
    opponent_answer TEXT,
    challenger_correct BOOLEAN,
    opponent_correct BOOLEAN,
    challenger_time DECIMAL(10,2),
    opponent_time DECIMAL(10,2),
    winner_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_battles_challenger ON battles(challenger_id);
CREATE INDEX IF NOT EXISTS idx_battles_opponent ON battles(opponent_id);
CREATE INDEX IF NOT EXISTS idx_battles_status ON battles(status);

-- ============================================================================
-- 6. BOSS FIGHTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS boss_fights (
    id TEXT PRIMARY KEY,
    year INTEGER NOT NULL,
    week INTEGER NOT NULL,
    subject TEXT NOT NULL,
    question TEXT NOT NULL,
    model_answer TEXT,
    explanation TEXT,
    completers JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_boss_fights_year_week ON boss_fights(year, week);

-- ============================================================================
-- 7. WRONG QUESTIONS TABLE (For review sheets)
-- ============================================================================
CREATE TABLE IF NOT EXISTS wrong_questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    topic TEXT,
    question TEXT NOT NULL,
    options JSONB,
    answer TEXT,
    explanation TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wrong_questions_telegram ON wrong_questions(telegram_id);
CREATE INDEX IF NOT EXISTS idx_wrong_questions_timestamp ON wrong_questions(timestamp);

-- ============================================================================
-- 8. TIER CHANGE LOG (Audit trail)
-- ============================================================================
CREATE TABLE IF NOT EXISTS tier_change_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    old_tier TEXT NOT NULL,
    new_tier TEXT NOT NULL,
    reason TEXT,
    changed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tier_log_telegram ON tier_change_log(telegram_id);

-- ============================================================================
-- 9. DAILY TIPS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS daily_tips (
    date DATE PRIMARY KEY,
    tip TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 10. CONTENT CACHE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS content_cache (
    cache_key TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 11. FEATURE SUGGESTIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS feature_suggestions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    username TEXT,
    suggestion TEXT NOT NULL,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_suggestions_submitted ON feature_suggestions(submitted_at);

-- ============================================================================
-- 12. TEXTBOOK CHUNKS TABLE (For RAG)
-- ============================================================================
CREATE TABLE IF NOT EXISTS textbook_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_subject ON textbook_chunks(subject);

-- ============================================================================
-- 13. REAL EXAM QUESTIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS real_exam_questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject TEXT NOT NULL,
    question TEXT NOT NULL,
    options JSONB,
    answer TEXT,
    explanation TEXT,
    year INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_real_questions_subject ON real_exam_questions(subject);

-- ============================================================================
-- 14. PARENT REPORTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS parent_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parent_token TEXT NOT NULL REFERENCES users(parent_token),
    report TEXT NOT NULL,
    week INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parent_reports_token ON parent_reports(parent_token);

-- ============================================================================
-- 15. PANIC KIT QUESTIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS panic_kit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rank INTEGER NOT NULL,
    question TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_panic_rank ON panic_kit(rank);

-- ============================================================================
-- TRIGGERS FOR UPDATED_AT
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to all tables with updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_payment_attempts_updated_at BEFORE UPDATE ON payment_attempts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_content_cache_updated_at BEFORE UPDATE ON content_cache
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- ROW LEVEL SECURITY POLICIES
-- ============================================================================

-- Enable RLS on all tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE exam_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE confessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE battles ENABLE ROW LEVEL SECURITY;
ALTER TABLE wrong_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_suggestions ENABLE ROW LEVEL SECURITY;

-- Create policies for service role (your bot)
CREATE POLICY "Service role full access" ON users
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON payment_attempts
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON exam_results
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON confessions
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON battles
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON wrong_questions
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON feature_suggestions
    FOR ALL USING (true) WITH CHECK (true);

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Insert some sample panic kit questions
INSERT INTO panic_kit (rank, question) VALUES
(1, 'What is the powerhouse of the cell?'),
(2, 'Solve for x: 2x + 5 = 15'),
(3, 'What is the chemical formula for water?')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- DONE! Your Supabase database is ready for the EUEE Abebe Bot
-- ============================================================================
