"""Database error handling utilities."""

import logging
from typing import TypeVar, Callable, Any
from sqlalchemy.exc import SQLAlchemyError
from telegram.ext import ContextTypes
from telegram import Update

logger = logging.getLogger("coord_bot.db.errors")

T = TypeVar("T")


class DatabaseError(Exception):
    """Base exception for database errors."""

    pass


class DatabaseConnectionError(DatabaseError):
    """Exception raised when database connection fails."""

    pass


class DatabaseOperationError(DatabaseError):
    """Exception raised when database operation fails."""

    pass


def log_database_error(
    operation: str, error: Exception, context: dict | None = None
) -> None:
    """Log database error with context information."""
    logger.error(
        "Database %s failed: %s",
        operation,
        type(error).__name__,
        exc_info=True,
        extra={"context": context or {}},
    )


async def handle_database_error(
    update: Update | None,
    context: ContextTypes.DEFAULT_TYPE,
    operation: str,
    error: Exception,
    user_message: str | None = None,
) -> bool:
    """
    Handle database error gracefully and return True if error was handled.

    Returns False if error should be propagated.
    """
    log_database_error(
        operation,
        error,
        {
            "update_id": update.update_id if update else None,
            "chat_id": (
                update.effective_chat.id if update and update.effective_chat else None
            ),
        },
    )

    if not user_message:
        user_message = (
            "❌ A database error occurred while processing your request. "
            "Please try again later."
        )

    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(user_message)
        except Exception as e:
            logger.warning("Failed to send error message to user: %s", e)

    return True


def database_error_handler(operation: str, user_message: str | None = None):
    """
    Decorator for handling database errors in handlers.

    Usage:
        @database_error_handler("fetch events", "Failed to load events")
        async def get_events(session):
            ...
    """

    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs) -> Any:
            try:
                return await func(*args, **kwargs)
            except DatabaseError:
                raise
            except SQLAlchemyError as e:
                # Handle SQLAlchemy-specific errors
                raise DatabaseOperationError(f"Database operation failed: {e}") from e
            except Exception as e:
                # Handle other errors
                raise DatabaseConnectionError(f"Database connection failed: {e}") from e

        return wrapper

    return decorator


def is_connection_error(error: Exception) -> bool:
    """Check if error is related to database connection."""
    error_str = str(error).lower()
    connection_errors = {
        "connection refused",
        "connection reset",
        "connection timeout",
        "network unreachable",
        "host unreachable",
        "refused",
        "could not translate host name",
        "no route to host",
    }

    return any(err in error_str for err in connection_errors)


def is_transaction_error(error: Exception) -> bool:
    """Check if error is related to transaction state."""
    error_str = str(error).lower()
    transaction_errors = {"transaction", "rollback", "commit", "session", "flush"}

    return any(err in error_str for err in transaction_errors)
