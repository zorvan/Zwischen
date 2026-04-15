-- Database schema for Telegram Coordination Bot
-- 
-- SCHEMA DEFINITION - Single Source of Truth
-- ============================================
-- This file documents the complete database schema for the coordination bot.
--
-- IMPORTANT NOTES:
-- - Primary: SQLAlchemy models in db/models.py define the schema
-- - This file serves as reference documentation of the final schema
-- - The models and this file should be kept in sync
-- - Database is initialized from SQLAlchemy models at application startup
--
-- When making schema changes:
-- 1. Update db/models.py first (primary source)
-- 2. Update this file to match (documentation)
-- 3. Restart application (init_db() will create/update tables)
--
-- For future large-scale schema migrations, consider implementing
-- a migration system - see git history for previous migration setup.

-- 1. Users: Global identity across groups
CREATE TABLE IF NOT EXISTS users (
    user_id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255) UNIQUE,
    display_name VARCHAR(255),
    expertise_per_activity JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Groups: Telegram group context
CREATE TABLE IF NOT EXISTS groups (
    group_id BIGSERIAL PRIMARY KEY,
    telegram_group_id BIGINT UNIQUE NOT NULL,
    group_name VARCHAR(255),
    group_type VARCHAR(50) DEFAULT 'casual' CHECK (group_type IN ('casual', 'gathering', 'tournament')),
    member_list JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Events: Gathering lifecycle
CREATE TABLE IF NOT EXISTS events (
    event_id BIGSERIAL PRIMARY KEY,
    group_id INTEGER REFERENCES groups(group_id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    description TEXT,
    organizer_telegram_user_id BIGINT,
    admin_telegram_user_id BIGINT,
    scheduled_time TIMESTAMP,
    commit_by TIMESTAMP,
    duration_minutes INTEGER DEFAULT 120,
    planning_prefs JSONB DEFAULT '{}',
    state VARCHAR(20) DEFAULT 'proposed' CHECK (state IN ('proposed', 'interested', 'confirmed', 'locked', 'completed', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    locked_at TIMESTAMP,
    completed_at TIMESTAMP,
    -- PRD v2: Threshold enforcement fields
    min_participants INTEGER DEFAULT 2,
    target_participants INTEGER DEFAULT 6,
    collapse_at TIMESTAMP,
    lock_deadline TIMESTAMP,
    -- PRD v2: Optimistic concurrency control
    version INTEGER DEFAULT 0 NOT NULL,
    formation_hashtag JSONB DEFAULT '[]',
    locked_hashtag JSONB DEFAULT '[]',
    mosaic_message_id BIGINT
);

-- 4. Constraints: Conditional participation
CREATE TABLE IF NOT EXISTS constraints (
    constraint_id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    target_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL CHECK (
        type IN ('if_joins', 'if_attends', 'unless_joins')
        OR type LIKE 'available:%'
    ),
    confidence FLOAT DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Logs: Audit trail
CREATE TABLE IF NOT EXISTS logs (
    log_id BIGSERIAL PRIMARY KEY,
    event_id BIGINT REFERENCES events(event_id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL CHECK (action IN ('organize_event', 'join', 'confirm', 'cancel', 'suggest_time', 'nudge', 'constraint_update')),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- 6. UserPreference: Private user preference profiles
CREATE TABLE IF NOT EXISTS user_preferences (
    preference_id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    time_preference VARCHAR(50) DEFAULT 'any',
    activity_preference VARCHAR(100) DEFAULT 'any',
    budget_preference VARCHAR(50) DEFAULT 'any',
    location_type_preference VARCHAR(100) DEFAULT 'any',
    transport_preference VARCHAR(50) DEFAULT 'any',
    privacy_settings JSONB DEFAULT '{}',
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)
);

-- ============================================================================
-- PRD v2: Enum Types
-- ============================================================================

-- Participant status enum
DO $$ BEGIN
    CREATE TYPE participant_status AS ENUM ('joined', 'confirmed', 'cancelled', 'no_show');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Participant role enum
DO $$ BEGIN
    CREATE TYPE participant_role AS ENUM ('organizer', 'participant', 'observer');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================================
-- PRD v2: New Tables for Priority 1 - Structural Foundations
-- ============================================================================

-- 7. EventParticipant: Normalized participation tracking
CREATE TABLE IF NOT EXISTS event_participants (
    event_id BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,
    status participant_status NOT NULL DEFAULT 'joined',
    role participant_role NOT NULL DEFAULT 'participant',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    source VARCHAR(50),
    PRIMARY KEY (event_id, telegram_user_id)
);

-- 8. IdempotencyKey: Prevents duplicate command execution
CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key VARCHAR(255) PRIMARY KEY,
    command_type VARCHAR(100) NOT NULL,
    user_id INTEGER REFERENCES users(user_id),
    event_id BIGINT REFERENCES events(event_id),
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed')),
    response_hash VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    expires_at TIMESTAMP NOT NULL
);

-- 9. EventStateTransition: Audit trail for state changes
CREATE TABLE IF NOT EXISTS event_state_transitions (
    transition_id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    from_state VARCHAR(20) NOT NULL,
    to_state VARCHAR(20) NOT NULL,
    actor_telegram_user_id BIGINT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason TEXT,
    source VARCHAR(50) NOT NULL
);

-- ============================================================================
-- PRD v2: New Tables for Priority 3 - Layer 3 Memory
-- ============================================================================

-- 10. EventMemory: Memory Weave storage
CREATE TABLE IF NOT EXISTS event_memories (
    memory_id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE UNIQUE,
    fragments JSONB DEFAULT '[]',
    hashtags JSONB DEFAULT '[]',
    outcome_markers JSONB DEFAULT '[]',
    weave_text TEXT,
    lineage_event_ids JSONB DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 11. EventWaitlist: Waitlist for oversubscribed events
CREATE TABLE IF NOT EXISTS event_waitlist (
    waitlist_id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,
    position INTEGER,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'waiting' CHECK (
        status IN ('waiting', 'offered', 'promoted', 'expired', 'cancelled')
    ),
    UNIQUE(event_id, telegram_user_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_events_group ON events(group_id);
CREATE INDEX IF NOT EXISTS idx_events_state ON events(state);
CREATE INDEX IF NOT EXISTS idx_events_organizer_tg ON events(organizer_telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_events_admin_tg ON events(admin_telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_constraints_event ON constraints(event_id);
CREATE INDEX IF NOT EXISTS idx_logs_event ON logs(event_id);
CREATE INDEX IF NOT EXISTS idx_user_preferences_user ON user_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_user_preferences_time ON user_preferences(time_preference);
CREATE INDEX IF NOT EXISTS idx_user_preferences_activity ON user_preferences(activity_preference);
CREATE INDEX IF NOT EXISTS idx_user_preferences_budget ON user_preferences(budget_preference);

-- PRD v2: Indexes for new tables
CREATE INDEX IF NOT EXISTS idx_event_participants_event_id ON event_participants(event_id);
CREATE INDEX IF NOT EXISTS idx_event_participants_user_id ON event_participants(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_event_participants_status ON event_participants(status);
CREATE INDEX IF NOT EXISTS idx_event_state_transitions_event_id ON event_state_transitions(event_id);
CREATE INDEX IF NOT EXISTS idx_idempotency_keys_expires ON idempotency_keys(expires_at);

-- PRD v2: Waitlist indexes
CREATE INDEX IF NOT EXISTS idx_event_waitlist_event_id ON event_waitlist(event_id);
CREATE INDEX IF NOT EXISTS idx_event_waitlist_user_id ON event_waitlist(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_event_waitlist_status ON event_waitlist(status);
