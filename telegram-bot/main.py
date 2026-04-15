#!/usr/bin/env python3
"""Main entry point for the Telegram bot.

Version: v3.3.0 - Social Visibility Release

PRD v3: Pure mediation through timing, framing, visibility, language, sequence, and memory.
PRD v3.3: Live event cards, memory-first flow, and living artifacts.
"""

import asyncio
import logging
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.settings import Settings
from config.logging import setup_logging
from bot.commands import (
    start,
    my_groups,
    profile,
    organize_event,
    private_organize_event,
    join,
    confirm,
    back,
    cancel,
    lock,
    request_confirmations,
    modify_event,
    constraints,
    suggest_time,
    status,
    event_details,
    events,
    check_deadlines,
    memory,
    my_history,
    personal_attendance_mirror,
    meaning_formation,
)
from bot.handlers import (
    event_flow,
    membership,
    mentions,
    menus,
    waitlist as waitlist_handlers,
)
from ai.llm import LLMClient
from db.connection import check_db_connection, create_engine, init_db

__version__ = "3.3.0"


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log full traceback for uncaught update handling errors."""
    logger = logging.getLogger("coord_bot.bot")
    logger.exception(
        "Unhandled Telegram update error. update=%r", update, exc_info=context.error
    )


async def check_llm_availability(logger: logging.Logger) -> None:
    """Check LLM availability on startup and log status."""
    llm = LLMClient()
    try:
        is_available, message = await llm.check_availability()
        if is_available:
            logger.info("Startup LLM check: %s", message)
        else:
            logger.warning("Startup LLM check: %s", message)
    finally:
        await llm.close()


async def check_db_availability(logger: logging.Logger, db_url: str) -> None:
    """Check database availability on startup and log status."""
    if not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    is_available, message = await check_db_connection(db_url)
    if is_available:
        logger.info("Startup DB check: %s", message)
    else:
        logger.warning("Startup DB check: %s", message)


async def run_scheduled_tasks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Run scheduled background tasks.

    Triggered by job queue every 30 minutes.
    """
    from bot.common.scheduler import run_scheduled_tasks as run_tasks

    settings = context.bot_data.get("settings")
    if not settings or not settings.db_url:
        return

    await run_tasks(context.bot, settings.db_url)


def main():
    """Main entry point."""
    settings = Settings()
    logger = setup_logging(settings)

    if not settings.telegram_token:
        raise ValueError("TELEGRAM_TOKEN is not set. Define it in environment or .env.")
    if settings.telegram_token in {
        "test-token",
        "dummy-token",
        "changeme",
        "your-token-here",
        "<set-me>",
    }:
        raise ValueError(
            "TELEGRAM_TOKEN is still a placeholder value. "
            "Set a real BotFather token in .env before starting the bot."
        )
    if ":" not in settings.telegram_token:
        raise ValueError(
            "TELEGRAM_TOKEN does not look like a valid Telegram bot token. "
            "Expected '<bot_id>:<secret>'."
        )
    if settings.environment == "production" and not settings.webhook_url:
        raise ValueError("WEBHOOK_URL must be set when ENVIRONMENT=production.")

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(check_llm_availability(logger))
    if settings.db_url:
        if not settings.db_url.startswith("postgresql+asyncpg://"):
            db_url = settings.db_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        else:
            db_url = settings.db_url
        loop.run_until_complete(check_db_availability(logger, db_url))
        # Initialize database schema (create tables and enum types if needed)
        logger.info("Initializing database...")
        engine = create_engine(db_url)
        loop.run_until_complete(init_db(engine))
        logger.info("Database initialization complete")

    # Build application with job queue for scheduled tasks
    application = ApplicationBuilder().token(settings.telegram_token).build()

    # Store settings in bot_data for access by handlers and jobs
    application.bot_data["settings"] = settings

    # Register middleware (rate limiting)
    # Note: Uncomment when ready to enable rate limiting
    # from bot.common.rate_limiter import rate_limit_middleware
    # application.middleware().add(rate_limit_middleware)

    # Capture rolling group history first for mention context.
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS, mentions.record_group_history),
        group=-2,
    )

    # Sync group users/members from any group activity before command handling.
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS, membership.track_group_members),
        group=-1,
    )

    # Mention-driven AI action inference in groups.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            mentions.handle_mention,
            block=False,
        ),
        group=1,
    )

    # Register command handlers
    command_map = {
        "start": start.handle,
        "help": start.handle,
        "my_groups": my_groups.handle,
        "profile": profile.handle,
        "how_am_i_doing": personal_attendance_mirror.handle,
        "plan": meaning_formation.handle,
        "organize_event": organize_event.handle,
        "organize_event_flexible": organize_event.handle_flexible,
        "join": join.handle,
        "confirm": confirm.handle,
        "interested": confirm.handle,
        "back": back.handle,
        "cancel": cancel.handle,
        "lock": lock.handle,
        "request_confirmations": request_confirmations.handle,
        "modify_event": modify_event.handle,
        "constraints": constraints.handle,
        "suggest_time": suggest_time.handle,
        "status": status.handle,
        "events": events.handle,
        "event_details": event_details.handle,
        "private_organize_event": private_organize_event.handle,
        "check_deadlines": check_deadlines.handle,
        # PRD v2: Memory layer commands
        "memory": memory.memory,
        "recall": memory.recall,
        "remember": memory.remember,
        # PRD v2: Weekly digest command
        "digest": memory.weekly_digest,  # Manual trigger for now
        # PRD v2: Personal history (DM only)
        "my_history": my_history.handle,
    }

    for command, handler in command_map.items():
        application.add_handler(CommandHandler(command, handler))

    # Register callback query handlers
    # NOTE: Order matters! More specific patterns must come before general ones.
    callback_handlers = [
        # Menu handlers (must come before general patterns)
        (r"^menu_", menus.handle_menu_callback),
        # Waitlist handlers (must come before general event_ patterns)
        (r"^waitlist_(join|accept|decline)_", waitlist_handlers.handle_menu_callback),
        (r"^extend_deadline_", waitlist_handlers.handle_menu_callback),
        (r"^view_waitlist_", waitlist_handlers.handle_menu_callback),
        # Event flow handlers (more specific, must come before general event_)
        (r"^event_(join|confirm|back|cancel|lock)_", event_flow.handle_event_flow),
        (
            r"^event_unconfirm_",
            event_flow.handle_event_flow,
        ),  # Uncommit (separate from back)
        (
            r"^event_(details|status|logs|constraints|close)_",
            event_details.handle_callback,
        ),
        (r"^event_modify_", mentions.handle_callback),
        # Event creation handlers (general, comes after specific ones)
        (r"^event_", organize_event.handle_callback),
        (r"^private_event_", organize_event.private_handle_callback),
        # Modify input handlers
        (r"^modinput_", mentions.handle_callback),
        # Other handlers
        (r"^constraint_nl_", constraints.handle_callback),
        (r"^mentionact_", mentions.handle_mention_callback),
        (r"^suggest_time_retry_", suggest_time.handle_callback),
        (r"^modreq_", modify_event.handle_modify_request_callback),
        # Weekly digest callbacks
        (r"^digest_", memory.handle_digest_callback),
    ]

    for pattern, handler in callback_handlers:
        application.add_handler(CallbackQueryHandler(handler, pattern=pattern))

    # Register text message handler for event creation flow
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, organize_event.handle_message),
        group=0,
    )

    # Register text message handler for pending modification requests
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, mentions.handle_modify_message),
        group=2,
    )

    application.add_error_handler(on_error)

    # Schedule periodic tasks using job queue
    # Memory collection: every 30 minutes
    # Log pruning: weekly (checked in task)
    # Threshold deadline checks: hourly (checked in task)
    # 24h reminders: daily at 9 AM (checked in task)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            run_scheduled_tasks,
            interval=1800,  # 30 minutes
            first=60,  # Start after 1 minute
            name="scheduled_tasks",
        )
        logger.info("Scheduled tasks job registered (30-minute interval)")

    # Note: Deadline checks can also be run periodically via job queue
    # For now, triggered manually via /check_deadlines command

    logger.info("Bot started. Press Ctrl+C to stop.")

    # Check if webhook mode is enabled
    if (
        settings.environment == "production"
        and hasattr(settings, "webhook_url")
        and settings.webhook_url
    ):
        # Production: Use webhook with worker queue
        logger.info("Starting in webhook mode: %s", settings.webhook_url)
        from bot.common.webhook import setup_webhook, shutdown_webhook

        async def run_webhook():
            await setup_webhook(
                application,
                webhook_url=settings.webhook_url,
                webhook_port=settings.webhook_port,
                webhook_host=settings.webhook_host,
                webhook_secret=settings.webhook_secret,
            )

        try:
            loop.run_until_complete(run_webhook())
        except KeyboardInterrupt:
            loop.run_until_complete(shutdown_webhook(application))
    else:
        # Development: Use polling
        logger.info("Starting in polling mode")
        application.run_polling()


if __name__ == "__main__":
    main()
