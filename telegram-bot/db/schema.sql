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
-- NOTE: expertise_per_activity removed in v3.5 (behavioral scoring deprecated)
-- v3.5: All timestamps use WITH TIME ZONE for proper UTC handling
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255) UNIQUE,
    display_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Groups: Telegram group context
CREATE TABLE IF NOT EXISTS groups (
    group_id SERIAL PRIMARY KEY,
    telegram_group_id BIGINT UNIQUE NOT NULL,
    group_name VARCHAR(255),
    group_type VARCHAR(50) DEFAULT 'casual',
    member_list JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Events: Gathering lifecycle
-- NOTE: admin_telegram_user_id renamed to emergency_admin_telegram_user_id in v3.5
CREATE TABLE IF NOT EXISTS events (
    event_id SERIAL PRIMARY KEY,
    group_id INTEGER REFERENCES groups(group_id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    description TEXT,
    organizer_telegram_user_id BIGINT,
    emergency_admin_telegram_user_id BIGINT,
    scheduled_time TIMESTAMP WITH TIME ZONE,
    commit_by TIMESTAMP WITH TIME ZONE,
    duration_minutes INTEGER DEFAULT 120,
    planning_prefs JSONB DEFAULT '{}',
    state VARCHAR(20) DEFAULT 'proposed' CHECK (state IN ('proposed', 'interested', 'confirmed', 'locked', 'completed', 'cancelled')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    locked_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    -- PRD v2: Threshold enforcement fields
    min_participants INTEGER DEFAULT 2,
    target_participants INTEGER DEFAULT 6,
    collapse_at TIMESTAMP WITH TIME ZONE,
    lock_deadline TIMESTAMP WITH TIME ZONE,
    -- PRD v2: Optimistic concurrency control
    version INTEGER DEFAULT 0 NOT NULL
);

-- 4. Constraints: Conditional participation
CREATE TABLE IF NOT EXISTS constraints (
    constraint_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    target_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    event_id INTEGER REFERENCES events(event_id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL,
    confidence FLOAT DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Logs: Audit trail
CREATE TABLE IF NOT EXISTS logs (
    log_id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- 6. UserPreference: Private user preference profiles
CREATE TABLE IF NOT EXISTS user_preferences (
    preference_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    time_preference VARCHAR(50) DEFAULT 'any',
    activity_preference VARCHAR(100) DEFAULT 'any',
    budget_preference VARCHAR(50) DEFAULT 'any',
    location_type_preference VARCHAR(100) DEFAULT 'any',
    transport_preference VARCHAR(50) DEFAULT 'any',
    privacy_settings JSONB DEFAULT '{}',
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
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
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,
    status participant_status NOT NULL DEFAULT 'joined',
    role participant_role NOT NULL DEFAULT 'participant',
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    source VARCHAR(50),
    PRIMARY KEY (event_id, telegram_user_id)
);

-- 8. IdempotencyKey: Prevents duplicate command execution
CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key VARCHAR(255) PRIMARY KEY,
    command_type VARCHAR(100) NOT NULL,
    user_id INTEGER REFERENCES users(user_id),
    event_id INTEGER REFERENCES events(event_id),
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'failed')),
    response_hash VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

-- 9. EventStateTransition: Audit trail for state changes
CREATE TABLE IF NOT EXISTS event_state_transitions (
    transition_id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    from_state VARCHAR(20) NOT NULL,
    to_state VARCHAR(20) NOT NULL,
    actor_telegram_user_id BIGINT,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason TEXT,
    source VARCHAR(50) NOT NULL
);

-- ============================================================================
-- PRD v2: New Tables for Priority 3 - Layer 3 Memory
-- ============================================================================

-- 10. EventMemory: Memory Weave storage
CREATE TABLE IF NOT EXISTS event_memories (
    memory_id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE UNIQUE,
    fragments JSONB DEFAULT '[]',
    hashtags JSONB DEFAULT '[]',
    outcome_markers JSONB DEFAULT '[]',
    weave_text TEXT,
    lineage_event_ids JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 11. EventWaitlist: Waitlist for oversubscribed events
CREATE TABLE IF NOT EXISTS event_waitlist (
    waitlist_id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,
    position INTEGER,
    added_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
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

-- ============================================================================
-- PRD v3.5: New Tables for Event Enrichments, Lineage, Live Cards, Group Settings
-- ============================================================================

-- 12. EventEnrichment: Member contributions (ideas, hashtags, memories)
CREATE TABLE IF NOT EXISTS event_enrichments (
    enrichment_id BIGSERIAL PRIMARY KEY,
    event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,
    enrichment_type VARCHAR(30) NOT NULL,
    -- Values: 'idea', 'hashtag', 'memory'
    content TEXT NOT NULL,
    is_public BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 13. EventLineage: Parent-child relationships between events
CREATE TABLE IF NOT EXISTS event_lineage (
    parent_event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE,
    child_event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE,
    relation_type VARCHAR(30) DEFAULT 'same_type',
    linked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (parent_event_id, child_event_id)
);

-- 14. EventLiveCard: Track live cards posted to group chats
CREATE TABLE IF NOT EXISTS event_live_cards (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT REFERENCES events(event_id) ON DELETE CASCADE UNIQUE,
    message_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    participant_count INTEGER DEFAULT 0,
    confirmed_count INTEGER DEFAULT 0,
    reaction_counts JSONB DEFAULT '{}',
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 15. GroupSettings: Per-group configuration
CREATE TABLE IF NOT EXISTS group_settings (
    group_id INTEGER REFERENCES groups(group_id) ON DELETE CASCADE PRIMARY KEY,
    enable_live_cards BOOLEAN DEFAULT TRUE,
    group_timezone VARCHAR(50) DEFAULT 'UTC',
    max_hashtags_per_event INTEGER DEFAULT 5,
    lineage_selection_method VARCHAR(10) DEFAULT 'fixed',
    -- 'fixed' = most recent fragment | 'llm' = context-aware
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- PRD v3.5: Indexes for new tables
CREATE INDEX IF NOT EXISTS idx_enrichments_event ON event_enrichments(event_id);
CREATE INDEX IF NOT EXISTS idx_enrichments_type ON event_enrichments(enrichment_type);
CREATE INDEX IF NOT EXISTS idx_enrichments_public ON event_enrichments(is_public);
CREATE INDEX IF NOT EXISTS idx_lineage_parent ON event_lineage(parent_event_id);
CREATE INDEX IF NOT EXISTS idx_lineage_child ON event_lineage(child_event_id);
