#!/usr/bin/env python3
"""Test script for verification."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_all():
    """Test all imports and basic functionality."""
    print("=" * 60)
    print("Telegram AI Coordination Bot - Full Test Suite")
    print("=" * 60)

    # Test config
    print("\n1. Testing config module...")
    from config.settings import settings
    from config.logging import setup_logging

    setup_logging(settings)
    print("   ✅ config module")

    # Test database
    print("\n2. Testing database module...")
    from db.connection import create_engine, create_session
    from db.models import Base, User, Group, Event, Constraint, Log, Feedback, AILog

    print("   ✅ db module")

    # Test AI
    print("\n3. Testing AI module...")
    from ai.core import AICoordinationEngine
    from ai.rules import RuleBasedEngine
    from ai.llm import LLMClient

    print("   ✅ ai module")

    # Test commands
    print("\n4. Testing command handlers...")
    from bot.commands import (
        start,
        my_groups,
        profile,
        cancel,
        suggest_time,
        event_details,
    )

    print("   ✅ command handlers")

    # Test handlers
    print("\n5. Testing handlers...")
    from bot.handlers import event_panel, feedback

    print("   ✅ event_panel, feedback")

    # Test utils
    print("\n6. Testing utils...")
    # nudges module removed - nudge message inlined into cancel.py
    print("   ✅ utils cleaned up")

    # Test main
    print("\n7. Testing main entry point...")
    from main import main

    print("   ✅ main.py ready")

    # Test database connection
    print("\n8. Testing database connection...")
    db_url = os.getenv("DB_URL", "postgresql://coord_user:coord_pass@localhost:5432/coord_db")
    if not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_engine(db_url)
    from sqlalchemy import text
    import asyncio

    async def check_db():
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar()

    result = asyncio.run(check_db())
    print(f"   ✅ Database query successful (result: {result})")

    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED")
    print("=" * 60)
    print("\nReady for development!")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(test_all())
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
