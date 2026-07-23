#!/usr/bin/env python3
"""Main entry point for the Telegram bot.

PRD v3: Pure mediation through timing, framing, visibility, language, sequence, and memory.
"""
import asyncio
import logging
from pathlib import Path
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

from config.settings import Settings
from config.logging import setup_logging
from bot.commands import (
    start,
    my_groups,
    profile,
    private_organize_event,
    event_creation,
    back,
    cancel,
    request_confirmations,
    modify_event,
    suggest_time,
    events,
    check_deadlines,
    memory,
    my_history,
    personal_attendance_mirror,
    about,
    preferences,
    language,
)
from bot.handlers import (
    event_panel,
    membership,
    mentions,
    menus,
    waitlist as waitlist_handlers,
)
from ai.llm import LLMClient
from bot.common.i18n import init as init_i18n
from db.connection import create_engine, init_db, wait_for_db


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log full traceback for uncaught update handling errors with full context."""
    logger = logging.getLogger("coord_bot.bot")

    # Extract context information
    user_id = None
    chat_id = None
    update_type = type(update).__name__ if update else "None"

    if update and hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id
    if update and hasattr(update, "effective_chat") and update.effective_chat:
        chat_id = update.effective_chat.id

    # Log error with full context
    logger.error(
        "[GLOBAL_ERROR] Unhandled error | update_type=%s user_id=%s chat_id=%s error_type=%s error=%s",
        update_type,
        user_id,
        chat_id,
        type(context.error).__name__ if context.error else "None",
        str(context.error) if context.error else "None",
        exc_info=True,
    )

    # Categorize common errors for easier debugging
    if context.error:
        error_str = str(context.error).lower()
        if "timeout" in error_str:
            logger.warning(
                "[GLOBAL_ERROR] Timeout error detected - may indicate slow response or network issues"
            )
        elif "rate limit" in error_str or "too many requests" in error_str:
            logger.warning("[GLOBAL_ERROR] Rate limit error - Telegram API throttling")
        elif "chat not found" in error_str or "user not found" in error_str:
            logger.warning(
                "[GLOBAL_ERROR] Chat/user not found - user may have blocked the bot or deleted account"
            )
        elif "message is not modified" in error_str:
            logger.info(
                "[GLOBAL_ERROR] Message not modified - harmless, duplicate edit"
            )
        elif "message to edit not found" in error_str:
            logger.warning("[GLOBAL_ERROR] Message not found - may have been deleted")


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


async def bootstrap_database(logger: logging.Logger, db_url: str) -> None:
    """Wait for the database, then create tables and enum types.

    Waiting first means a cold start alongside its database (compose, k8s)
    converges instead of crash-looping.
    """
    await wait_for_db(db_url)
    logger.info("Startup DB check: Database connection OK")
    logger.info("Initializing database...")
    engine = create_engine(db_url)
    await init_db(engine)
    logger.info("Database initialization complete")


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
    init_i18n()

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

    # Create the loop explicitly. asyncio.get_event_loop() with no running loop
    # is deprecated (DeprecationWarning today, RuntimeError in future Python),
    # and PTB needs this loop to still be the current one when run_polling()
    # takes over below.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(check_llm_availability(logger))
    if settings.db_url:
        # Settings.__init__ already normalized the driver, so every consumer
        # (handlers, services, scheduler) shares this exact URL.
        loop.run_until_complete(bootstrap_database(logger, settings.db_url))
    else:
        logger.warning("DB_URL is not set. Database-backed features are unavailable.")

    # Build application with job queue for scheduled tasks
    # v3.5: Add persistence so user_data persists between updates (creation flow)
    persistence_path = Path(settings.persistence_path)
    persistence_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Persistence file: %s", persistence_path)
    persistence = PicklePersistence(filepath=persistence_path)

    application = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .persistence(persistence)
        .build()
    )

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
        "back": back.handle,
        "cancel": cancel.handle,
        "request_confirmations": request_confirmations.handle,
        "modify_event": modify_event.handle,
        "suggest_time": suggest_time.handle,
        "events": events.handle,
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
        "about": about.handle,
        "preferences": preferences.handle,
        "language": language.handle,
    }

    for command, handler in command_map.items():
        application.add_handler(CommandHandler(command, handler))

    # Register callback query handlers
    # NOTE: Order matters! More specific patterns must come before general ones.
    callback_handlers = [
        # v3.5: Event panel callbacks (ev:{id}:action format) - must come before menu_
        (r"^ev:", event_panel.route_event_callback),
        # Menu handlers (must come before general patterns)
        (r"^menu_", menus.handle_menu_callback),
        (r"^noop$", menus.handle_menu_callback),
        (r"^organize_", menus.handle_menu_callback),
        # v3.5: Events list and creation flow handlers
        (r"^events_", menus.handle_menu_callback),
        (r"^create_", menus.handle_menu_callback),
        # Waitlist handlers
        (r"^waitlist_(join|accept|decline)_", waitlist_handlers.handle_menu_callback),
        (r"^extend_deadline_", waitlist_handlers.handle_menu_callback),
        (r"^view_waitlist_", waitlist_handlers.handle_menu_callback),
        # Event creation flow callbacks (must come before general event_ pattern)
        (r"^event_type_", event_creation.handle_callback),
        (r"^event_duration_", event_creation.handle_callback),
        (r"^event_edit_", event_creation.handle_callback),
        (r"^event_date_", event_creation.handle_callback),
        (r"^event_time_", event_creation.handle_callback),
        (r"^event_invitees_", event_creation.handle_callback),
        (r"^event_invite_all$", event_creation.handle_callback),
        (r"^event_invite_custom$", event_creation.handle_callback),
        (r"^event_threshold_", event_creation.handle_callback),
        (r"^event_transport_", event_creation.handle_callback),
        (r"^event_budget_", event_creation.handle_callback),
        (r"^event_location_", event_creation.handle_callback),
        (r"^event_calendar_", event_creation.handle_callback),
        (r"^event_cal_", event_creation.handle_callback),
        (r"^event_time_option_", event_creation.handle_callback),
        (r"^event_time_manual$", event_creation.handle_callback),
        (r"^event_min_", event_creation.handle_callback),
        (r"^event_target_", event_creation.handle_callback),
        (r"^event_final_", event_creation.handle_callback),
        (r"^event_cancel_no$", event_creation.handle_callback),
        (r"^event_back_to_type$", event_creation.handle_callback),
        (r"^event_back_to_time_window$", event_creation.handle_callback),
        (r"^event_back_to_transport$", event_creation.handle_callback),
        # Private event creation flow callbacks
        (r"^private_event_type_", event_creation.private_handle_callback),
        (r"^private_event_duration_", event_creation.private_handle_callback),
        (r"^private_event_edit_", event_creation.private_handle_callback),
        (r"^private_event_date_", event_creation.private_handle_callback),
        (r"^private_event_time_", event_creation.private_handle_callback),
        (r"^private_event_invitees_", event_creation.private_handle_callback),
        (r"^private_event_threshold_", event_creation.private_handle_callback),
        (r"^private_event_transport_", event_creation.private_handle_callback),
        (r"^private_event_budget_", event_creation.private_handle_callback),
        (r"^private_event_location_", event_creation.private_handle_callback),
        (r"^private_event_calendar_", event_creation.private_handle_callback),
        (r"^private_event_cal_", event_creation.private_handle_callback),
        (r"^private_event_invite_all$", event_creation.private_handle_callback),
        (r"^private_event_invite_custom$", event_creation.private_handle_callback),
        (r"^private_event_time_option_", event_creation.private_handle_callback),
        (r"^private_event_time_manual$", event_creation.private_handle_callback),
        (r"^private_event_min_", event_creation.private_handle_callback),
        (r"^private_event_target_", event_creation.private_handle_callback),
        (r"^private_event_final_", event_creation.private_handle_callback),
        (r"^private_event_cancel_no$", event_creation.private_handle_callback),
        (r"^private_event_back_to_type$", event_creation.private_handle_callback),
        (
            r"^private_event_back_to_time_window$",
            event_creation.private_handle_callback,
        ),
        (r"^private_event_back_to_transport$", event_creation.private_handle_callback),
        # Language preference
        (r"^lang_", language.handle_callback),
        # v3.5: Event panel callbacks (ev:{id}:action format)
        (r"^ev:", event_panel.route_event_callback),
        (r"^mnpick_", mentions.handle_disambiguation_callbacks),
        (
            r"^mention_(start_organize|show_status|ask_help)$",
            mentions.handle_disambiguation_callbacks,
        ),
        # Modify input handlers
        (r"^modinput_", mentions.handle_callback),
        # Other handlers
        (r"^mentionact_", mentions.handle_mention_callback),
        (r"^suggest_time_retry_", suggest_time.handle_callback),
        (r"^modreq_", modify_event.handle_modify_request_callback),
        (r"^pref_wizard_", preferences.handle_callback),
        # Help callbacks
        (r"^help_", menus.handle_menu_callback),
        # Weekly digest callbacks
        (r"^digest_", memory.handle_digest_callback),
    ]

    for pattern, handler in callback_handlers:
        application.add_handler(CallbackQueryHandler(handler, pattern=pattern))

    # v3.5: Register creation flow message handler (runs first, checks for creation_step)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND, menus.handle_creation_message, block=False
        ),
        group=-9,  # Runs BEFORE other handlers to catch enrichment prompts
    )

    # Register text message handler for event creation flow
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, event_creation.handle_message),
        group=0,
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND, private_organize_event.handle_message
        ),
        group=1,
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
        # Production: Use webhook.
        logger.info("Starting in webhook mode: %s", settings.webhook_url)
        from bot.common.webhook import setup_webhook

        # setup_webhook blocks and owns the loop, exactly like run_polling().
        # It must NOT be wrapped in run_until_complete: run_webhook() is a
        # synchronous PTB call, and driving it through the loop raised
        # TypeError before it could ever bind a port.
        setup_webhook(
            application,
            webhook_url=settings.webhook_url,
            webhook_port=settings.webhook_port,
            webhook_host=settings.webhook_host,
            webhook_secret=settings.webhook_secret,
        )
    else:
        # Development: Use polling
        logger.info("Starting in polling mode")
        application.run_polling()


if __name__ == "__main__":
    main()
