#!/usr/bin/env python3
"""Main entry point for the Telegram bot.

Version: v3.3.0 - Social Visibility Release

PRD v3: Pure mediation through timing, framing, visibility, language, sequence, and memory.
PRD v3.3: Live event cards, memory-first flow, and living artifacts.
"""

import asyncio
import logging
from telegram.ext import (
    Application,
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
    request_confirmations,
    events,
    check_deadlines,
    memory,
    my_history,
    personal_attendance_mirror,
    meaning_formation,
    about,
)

from bot.handlers import (
    event_flow,
    menus,
    mentions,
)
from ai.llm import LLMClient
from db.connection import check_db_connection, create_engine

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

    async_engine = create_engine(db_url)
    try:
        await check_db_connection(async_engine)
        logger.info("Database connection: OK")
    finally:
        await async_engine.dispose()


async def setup_bot(application: Application) -> None:
    """Set up bot commands and webhook/polling."""
    bot_logger = logging.getLogger("coord_bot.bot")
    if Settings.WEBHOOK_ENABLED:
        await application.bot.setWebhook(
            url=Settings.WEBHOOK_URL,
            secret_token=Settings.WEBHOOK_SECRET_TOKEN,
            allowed_updates=Settings.WEBHOOK_ALLOWED_UPDATES,
        )
        bot_logger.info("Webhook configured")
    else:
        bot_logger.info("Polling mode active")


async def run_webhook() -> Application:
    """Run the bot in webhook mode."""
    app = ApplicationBuilder().token(Settings.TELEGRAM_BOT_TOKEN).build()

    app.add_error_handler(on_error)

    command_handlers = [
        CommandHandler("start", start.handle_start),
        CommandHandler("my_groups", my_groups.handle_my_groups),
        CommandHandler("profile", profile.handle_profile),
        CommandHandler("organize", organize_event.handle_organize),
        CommandHandler(
            "private_organize", private_organize_event.handle_private_organize
        ),
        CommandHandler(
            "request_confirmations", request_confirmations.handle_request_confirmations
        ),
        CommandHandler("events", events.handle_events),
        CommandHandler("check_deadlines", check_deadlines.handle_check_deadlines),
        CommandHandler("memory", memory.handle_memory),
        CommandHandler("my_history", my_history.handle_my_history),
        CommandHandler(
            "personal_attendance_mirror",
            personal_attendance_mirror.handle_personal_attendance_mirror,
        ),
        CommandHandler("meaning_formation", meaning_formation.handle_meaning_formation),
        CommandHandler("about", about.handle_about),
        CommandHandler("event", event_flow.handle_ev_command),
    ]

    for handler in command_handlers:
        app.add_handler(handler)

    message_handlers = [
        MessageHandler(
            filters.Regex(r"^event_(join|confirm|back|cancel|lock)_"),
            event_flow.handle_event_flow,
        ),
        MessageHandler(
            filters.Regex(r"^event_flow_"),
            event_flow.handle_event_flow,
        ),
    ]

    for handler in message_handlers:
        app.add_handler(handler)

    callback_handlers = [
        CallbackQueryHandler(
            event_flow.handle_event_flow,
            pattern=r"^event_(join|confirm|back|cancel|lock|unconfirm)_",
        ),
        CallbackQueryHandler(
            event_flow.handle_event_panel_callback, pattern=r"^panel:"
        ),
        CallbackQueryHandler(event_flow.handle_event_flow, pattern=r"^action:"),
        CallbackQueryHandler(
            event_flow.handle_enrich_callback, pattern=r"^enrich:"
        ),
        CallbackQueryHandler(
            event_flow.handle_constraint_callback, pattern=r"^constraint:"
        ),
        CallbackQueryHandler(event_flow.handle_ev_callback, pattern=r"^ev:"),
        CallbackQueryHandler(event_flow.handle_event_flow, pattern=r"^event_status_"),
        CallbackQueryHandler(event_flow.handle_event_flow, pattern=r"^event_details_"),
        CallbackQueryHandler(event_flow.handle_constraint_callback, pattern=r"^avail_add_"),
        CallbackQueryHandler(menus.handle_menu_callback, pattern=r"^menu_"),
        CallbackQueryHandler(menus.handle_menu_callback, pattern=r"^help_"),
        CallbackQueryHandler(menus.handle_menu_callback, pattern=r"^noop$"),
        CallbackQueryHandler(mentions.handle_mention_callback, pattern=r"^mentionact_"),
        CallbackQueryHandler(mentions.handle_disambiguation_callbacks, pattern=r"^(mnpick_|mention_)"),
    ]

    for handler in callback_handlers:
        app.add_handler(handler)

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^/ev\s"),
            event_flow.handle_ev_command,
        )
    )

    # Add mention handler for bot mentions and replies
    app.add_handler(
        MessageHandler(
            filters.Entity("mention") | filters.REPLY,
            mentions.handle_mention,
        )
    )

    await setup_bot(app)
    await app.initialize()
    await app.start()
    return app


async def shutdown_webhook(application: Application) -> None:
    """Clean shutdown for webhook mode."""
    await application.stop()


def main() -> None:
    """Main entry point for the Telegram bot."""
    settings = Settings()
    setup_logging(settings)
    logger = logging.getLogger("coord_bot.bot")

    logger.info("Starting Telegram Bot")
    logger.info("Version: %s", __version__)

    if Settings.WEBHOOK_ENABLED:
        if not Settings.WEBHOOK_URL:
            logger.error("WEBHOOK_URL is required when WEBHOOK_ENABLED is True")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        app: Application | None = None
        try:
            app = loop.run_until_complete(run_webhook())
        except KeyboardInterrupt:
            if app:
                loop.run_until_complete(shutdown_webhook(app))
    else:
        application = ApplicationBuilder().token(Settings.TELEGRAM_BOT_TOKEN).build()

        application.add_error_handler(on_error)

        command_handlers = [
            CommandHandler("start", start.handle_start),
            CommandHandler("my_groups", my_groups.handle_my_groups),
            CommandHandler(
                "request_confirmations",
                request_confirmations.handle_request_confirmations,
            ),
            CommandHandler("events", events.handle_events),
            CommandHandler("check_deadlines", check_deadlines.handle_check_deadlines),
            CommandHandler("memory", memory.handle_memory),
            CommandHandler("my_history", my_history.handle_my_history),
            CommandHandler(
                "personal_attendance_mirror",
                personal_attendance_mirror.handle_personal_attendance_mirror,
            ),
            CommandHandler(
                "meaning_formation", meaning_formation.handle_meaning_formation
            ),
            CommandHandler("about", about.handle_about),
            CommandHandler("event", event_flow.handle_ev_command),
        ]

        for handler in command_handlers:
            application.add_handler(handler)

        message_handlers = [
            MessageHandler(
                filters.Regex(r"^event_(join|confirm|back|cancel|lock)_"),
                event_flow.handle_event_flow,
            ),
            MessageHandler(
                filters.Regex(r"^event_flow_"),
                event_flow.handle_event_flow,
            ),
        ]

        for handler in message_handlers:
            application.add_handler(handler)

        callback_handlers = [
            CallbackQueryHandler(
                event_flow.handle_event_flow,
                pattern=r"^event_(join|confirm|back|cancel|lock|unconfirm)_",
            ),
            CallbackQueryHandler(
                event_flow.handle_event_panel_callback, pattern=r"^panel:"
            ),
            CallbackQueryHandler(event_flow.handle_event_flow, pattern=r"^action:"),
            CallbackQueryHandler(
                event_flow.handle_enrich_callback, pattern=r"^enrich:"
            ),
            CallbackQueryHandler(
                event_flow.handle_constraint_callback, pattern=r"^constraint:"
            ),
            CallbackQueryHandler(event_flow.handle_ev_callback, pattern=r"^ev:"),
            CallbackQueryHandler(event_flow.handle_event_flow, pattern=r"^event_status_"),
            CallbackQueryHandler(event_flow.handle_event_flow, pattern=r"^event_details_"),
            CallbackQueryHandler(event_flow.handle_constraint_callback, pattern=r"^avail_add_"),
            CallbackQueryHandler(menus.handle_menu_callback, pattern=r"^menu_"),
            CallbackQueryHandler(menus.handle_menu_callback, pattern=r"^help_"),
            CallbackQueryHandler(menus.handle_menu_callback, pattern=r"^noop$"),
            CallbackQueryHandler(mentions.handle_mention_callback, pattern=r"^mentionact_"),
            CallbackQueryHandler(mentions.handle_disambiguation_callbacks, pattern=r"^(mnpick_|mention_)"),
        ]

        for handler in callback_handlers:
            application.add_handler(handler)

        application.add_handler(
            MessageHandler(
                filters.Regex(r"^/ev\s"),
                event_flow.handle_ev_command,
            )
        )

        # Add mention handler for bot mentions and replies
        application.add_handler(
            MessageHandler(
                filters.Entity("mention") | filters.REPLY,
                mentions.handle_mention,
            )
        )

        application.run_polling()


if __name__ == "__main__":
    main()
