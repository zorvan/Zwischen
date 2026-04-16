-- Migration: Fix constraint table column types to match users table
-- This fixes the type mismatch where constraints.user_id was INTEGER but should be BIGINT

ALTER TABLE constraints 
    ALTER COLUMN user_id TYPE BIGINT USING user_id::BIGINT,
    ALTER COLUMN target_user_id TYPE BIGINT USING target_user_id::BIGINT;

-- Update foreign key constraints if needed
ALTER TABLE constraints DROP CONSTRAINT IF EXISTS constraints_user_id_fkey;
ALTER TABLE constraints DROP CONSTRAINT IF EXISTS constraints_target_user_id_fkey;

ALTER TABLE constraints 
    ADD CONSTRAINT constraints_user_id_fkey 
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    ADD CONSTRAINT constraints_target_user_id_fkey 
        FOREIGN KEY (target_user_id) REFERENCES users(user_id) ON DELETE SET NULL;
