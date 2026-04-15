-- Add missing columns to events table
-- This fixes: "column formation_hashtag of relation events does not exist"

ALTER TABLE events ADD COLUMN formation_hashtag JSON DEFAULT '[]';
ALTER TABLE events ADD COLUMN locked_hashtag JSON DEFAULT '[]';
ALTER TABLE events ADD COLUMN mosaic_message_id BIGINT;
