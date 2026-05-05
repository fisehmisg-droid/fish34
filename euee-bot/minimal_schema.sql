-- ============================================================================
-- MINIMAL SUPABASE SCHEMA - GUARANTEED TO WORK
-- Run this ONCE in Supabase Dashboard → SQL
-- ============================================================================

-- 1. USERS TABLE
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

-- 2. PAYMENT ATTEMPTS TABLE
CREATE TABLE IF NOT EXISTS payment_attempts (
    tx_id TEXT PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    username VARCHAR(100),
    plan_requested VARCHAR(50),
    status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. TIER CHANGE LOG TABLE
CREATE TABLE IF NOT EXISTS tier_change_log (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    old_tier VARCHAR(20),
    new_tier VARCHAR(20),
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. WRONG QUESTIONS TABLE
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

-- 5. BATTLES TABLE
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

-- 6. BOSS FIGHTS TABLE
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

-- 7. EXAMS TABLE
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

-- 8. PARENT REPORTS TABLE
CREATE TABLE IF NOT EXISTS parent_reports (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    parent_token VARCHAR(32),
    report TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 9. CONTENT CACHE TABLE
CREATE TABLE IF NOT EXISTS content_cache (
    cache_key TEXT PRIMARY KEY,
    content JSONB,
    file_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

-- 10. FEATURE SUGGESTIONS TABLE
CREATE TABLE IF NOT EXISTS feature_suggestions (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    suggestion TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 11. DAILY TIPS TABLE
CREATE TABLE IF NOT EXISTS daily_tips (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE,
    tip_en TEXT,
    tip_am TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 12. TEXTBOOK CHUNKS TABLE
CREATE TABLE IF NOT EXISTS textbook_chunks (
    id SERIAL PRIMARY KEY,
    subject VARCHAR(50),
    chapter INTEGER,
    chunk_index INTEGER,
    content TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 13. REAL EXAMS TABLE
CREATE TABLE IF NOT EXISTS real_exams (
    id SERIAL PRIMARY KEY,
    year INTEGER,
    subject VARCHAR(50),
    exam_type VARCHAR(20),
    questions JSONB,
    answers JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Minimal Supabase schema created successfully!';
    RAISE NOTICE '🎓 Abebe EUEE Bot database is ready!';
END $$;
