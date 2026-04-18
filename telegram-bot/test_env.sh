#!/bin/bash
# Test environment setup for real-time bot testing

# Set the sandbox bot token
export TELEGRAM_TOKEN="8759897347:AAH0wq0txn3TvQLLqv-A0TnlSFn-dmcP8mE"

# Set database URL with correct credentials
export DB_URL="postgresql+asyncpg://coord_user:coord_pass@localhost:5432/coord_db"

# Set logging to DEBUG for detailed testing
export LOG_LEVEL="DEBUG"
export LOG_LEVEL_TELEGRAM="DEBUG"

# Enable features for testing
export ENABLE_MATERIALIZATION="true"
export ENABLE_MEMORY_LAYER="true"
export ENABLE_IDEMPOTENCY="true"

# Set environment
export ENVIRONMENT="development"

echo "Test environment configured:"
echo "Telegram Token: ${TELEGRAM_TOKEN:0:10}..."
echo "Database URL: ${DB_URL}"
echo "Log Level: ${LOG_LEVEL}"
echo ""
echo "Starting bot with real-time testing configuration..."
echo "Test Group: https://t.me/+OhCg3_7U26M1NWI0"
echo ""
echo "Press Ctrl+C to stop the bot"
