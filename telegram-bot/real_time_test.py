#!/usr/bin/env python3
"""
Real-time Telegram Bot Test Script
Uses actual Telegram API to test bot functionality.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from bot.commands.events import handle as events_handle
from bot.handlers.event_flow import handle_event_panel_callback, handle_enrich_callback, handle_constraint_callback

# Real Telegram configuration
TELEGRAM_TOKEN = "8759897347:AAH0wq0txn3TvQLLqv-A0TnlSFn-dmcP8mE"
TEST_GROUP_LINK = "https://t.me/+OhCg3_7U26M1NWI0"

async def test_events_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test /events command with real Telegram."""
    print("Testing /events command...")
    try:
        await events_handle(update, context)
        print("SUCCESS: /events command executed")
        return True
    except Exception as e:
        print(f"FAILED: /events command - {e}")
        return False

async def test_event_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test event panel callback with real Telegram."""
    print("Testing event panel callback...")
    try:
        await handle_event_panel_callback(update, context)
        print("SUCCESS: Event panel callback executed")
        return True
    except Exception as e:
        print(f"FAILED: Event panel callback - {e}")
        return False

async def test_enrich_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test enrich callback with real Telegram."""
    print("Testing enrich callback...")
    try:
        await handle_enrich_callback(update, context)
        print("SUCCESS: Enrich callback executed")
        return True
    except Exception as e:
        print(f"FAILED: Enrich callback - {e}")
        return False

async def test_constraint_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test constraint callback with real Telegram."""
    print("Testing constraint callback...")
    try:
        await handle_constraint_callback(update, context)
        print("SUCCESS: Constraint callback executed")
        return True
    except Exception as e:
        print(f"FAILED: Constraint callback - {e}")
        return False

async def main():
    """Main test function."""
    print(f"Starting real-time Telegram bot tests...")
    print(f"Token: {TELEGRAM_TOKEN[:10]}...")
    print(f"Test Group: {TEST_GROUP_LINK}")
    print("-" * 50)
    
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("test_events", test_events_command))
    application.add_handler(CallbackQueryHandler(test_event_panel_callback, pattern="^panel:"))
    application.add_handler(CallbackQueryHandler(test_enrich_callback, pattern="^enrich:"))
    application.add_handler(CallbackQueryHandler(test_constraint_callback, pattern="^constraint:"))
    
    # Start bot
    print("Bot started. Send /test_events to test the events command.")
    print(f"Join the test group: {TEST_GROUP_LINK}")
    print("Press Ctrl+C to stop")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    try:
        # Keep bot running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping bot...")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        print("Bot stopped.")

if __name__ == "__main__":
    # Set environment variables
    os.environ["TELEGRAM_TOKEN"] = TELEGRAM_TOKEN
    os.environ["DB_URL"] = "postgresql+asyncpg://coord_user:coord_pass@localhost:5432/coord_db"
    
    asyncio.run(main())
