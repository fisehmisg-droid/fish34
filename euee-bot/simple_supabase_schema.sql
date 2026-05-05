-- ============================================================================
-- SIMPLE SUPABASE SCHEMA FOR ABEBE EUEE BOT
-- No foreign key constraints - will work immediately
-- Run this ONCE in Supabase Dashboard → SQL
-- ============================================================================

-- Helper function for timestamps
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 1. USERS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    name VARCHAR(100),
    language VARCHAR(10) DEFAULT 'en',
    tier VARCHAR(20) DEFAULT 'free',
    subscription_active BOOLEAN DEFAULT TRUE,
    subscription_expires_at TIMESTAMPTZ,
    tier_updated_at TIMESTAMPTZ,
    streak INTEGER DEFAULT 0,
    streak_freezes INTEGER DEFAULT 0,
    last_active_date DATE DEFAULT CURRENT_DATE,
    questions_today INTEGER DEFAULT 0,
    questions_total INTEGER DEFAULT 0,
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
    parent_token VARCHAR(32) UNIQUE,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    last_question_date DATE DEFAULT CURRENT_DATE,
    last_explanation TEXT DEFAULT '',
    chosen_subject VARCHAR(20) DEFAULT 'math',
    questions_this_week INTEGER DEFAULT 0,
    week_start DATE DEFAULT CURRENT_DATE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Drop and recreate trigger to avoid duplicates
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_tier ON users(tier);
CREATE INDEX IF NOT EXISTS idx_users_parent_token ON users(parent_token);
CREATE INDEX IF NOT EXISTS idx_users_subscription_active ON users(subscription_active);

-- ============================================================================
-- 2. PAYMENT ATTEMPTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS payment_attempts (
    tx_id TEXT PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    username VARCHAR(100),
    plan_requested VARCHAR(50),
    status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger for payment attempts
DROP TRIGGER IF EXISTS update_payment_attempts_updated_at ON payment_attempts;
CREATE TRIGGER update_payment_attempts_updated_at
    BEFORE UPDATE ON payment_attempts
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- 3. TIER CHANGE LOG TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS tier_change_log (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    old_tier VARCHAR(20),
    new_tier VARCHAR(20),
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- 4. WRONG QUESTIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS wrong_questions (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    subject VARCHAR(50),
    question TEXT,
    correct_answer VARCHAR(10),
    user_answer VARCHAR(10),
    explanation TEXT,
    topic VARCHAR(100),
    question_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for wrong questions
CREATE INDEX IF NOT EXISTS idx_wrong_questions_telegram_id ON wrong_questions(telegram_id);
CREATE INDEX IF NOT EXISTS idx_wrong_questions_subject ON wrong_questions(subject);

-- ============================================================================
-- 5. BATTLES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS battles (
    battle_id TEXT PRIMARY KEY,
    challenger_id BIGINT NOT NULL,
    opponent_id BIGINT,
    status VARCHAR(20) DEFAULT 'waiting',
    subject VARCHAR(50),
    question TEXT,
    options JSONB,
    correct_answer VARCHAR(10),
    explanation TEXT,
    challenger_answer VARCHAR(10),
    opponent_answer VARCHAR(10),
    challenger_correct BOOLEAN,
    opponent_correct BOOLEAN,
    challenger_time DECIMAL(10,2),
    opponent_time DECIMAL(10,2),
    winner_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

-- Indexes for battles
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

-- Index for boss fights
CREATE INDEX IF NOT EXISTS idx_boss_fights_year_week ON boss_fights(year, week);

-- ============================================================================
-- 7. EXAMS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS exams (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    subject VARCHAR(50),
    score INTEGER,
    total INTEGER,
    weak_topics JSONB DEFAULT '[]',
    exam_type VARCHAR(20) DEFAULT 'mock',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for exams
CREATE INDEX IF NOT EXISTS idx_exams_telegram_id ON exams(telegram_id);
CREATE INDEX IF NOT EXISTS idx_exams_subject ON exams(subject);

-- ============================================================================
-- 8. PARENT REPORTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS parent_reports (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    parent_token VARCHAR(32),
    report TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for parent reports
CREATE INDEX IF NOT EXISTS idx_parent_reports_token ON parent_reports(parent_token);
CREATE INDEX IF NOT EXISTS idx_parent_reports_telegram_id ON parent_reports(telegram_id);

-- ============================================================================
-- 9. CONTENT CACHE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS content_cache (
    cache_key TEXT PRIMARY KEY,
    content JSONB,
    file_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

-- Index for content cache
CREATE INDEX IF NOT EXISTS idx_content_cache_expires ON content_cache(expires_at);

-- ============================================================================
-- 10. FEATURE SUGGESTIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS feature_suggestions (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    suggestion TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for feature suggestions
CREATE INDEX IF NOT EXISTS idx_feature_suggestions_status ON feature_suggestions(status);

-- ============================================================================
-- 11. DAILY TIPS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS daily_tips (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE,
    tip_en TEXT,
    tip_am TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for daily tips
CREATE INDEX IF NOT EXISTS idx_daily_tips_date ON daily_tips(date);

-- ============================================================================
-- 12. TEXTBOOK CHUNKS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS textbook_chunks (
    id SERIAL PRIMARY KEY,
    subject VARCHAR(50),
    chapter INTEGER,
    chunk_index INTEGER,
    content TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for textbook chunks
CREATE INDEX IF NOT EXISTS idx_textbook_chunks_subject ON textbook_chunks(subject);
CREATE INDEX IF NOT EXISTS idx_textbook_chunks_chapter ON textbook_chunks(subject, chapter);

-- ============================================================================
-- 13. REAL EXAMS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS real_exams (
    id SERIAL PRIMARY KEY,
    year INTEGER,
    subject VARCHAR(50),
    exam_type VARCHAR(20),
    questions JSONB,
    answers JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for real exams
CREATE INDEX IF NOT EXISTS idx_real_exams_year_subject ON real_exams(year, subject);

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '✅ Supabase schema created successfully!';
    RAISE NOTICE '🎓 Abebe EUEE Bot database is ready!';
    RAISE NOTICE '🚀 All tables created without foreign key constraints!';
    RAISE NOTICE '📝 You can add foreign keys later if needed';
END $$;
