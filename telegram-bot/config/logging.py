"""
Application logging configuration.
PRD v2 Priority 1: Structured JSON logging with correlation IDs.
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar
from config.settings import Settings

# Context variables for correlation IDs
correlation_id_var: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)
event_id_var: ContextVar[Optional[int]] = ContextVar("event_id", default=None)
user_id_var: ContextVar[Optional[int]] = ContextVar("user_id", default=None)
chat_id_var: ContextVar[Optional[int]] = ContextVar("chat_id", default=None)


class StructuredJsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    Adds correlation IDs and contextual fields to every log entry.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add correlation IDs from context
        correlation_id = correlation_id_var.get()
        if correlation_id:
            log_entry["correlation_id"] = correlation_id

        event_id = event_id_var.get()
        if event_id is not None:
            log_entry["event_id"] = event_id

        user_id = user_id_var.get()
        if user_id is not None:
            log_entry["user_id"] = user_id

        chat_id = chat_id_var.get()
        if chat_id is not None:
            log_entry["chat_id"] = chat_id

        # Add standard fields if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            log_entry["stack_info"] = self.formatStack(record.stack_info)

        # Add extra fields (passed via extra={...})
        extra_fields = {
            k: v
            for k, v in record.__dict__.items()
            if k
            not in {
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "message",
                "asctime",
                "taskName",
            }
            and not k.startswith("_")
        }

        if extra_fields:
            log_entry["extra"] = extra_fields

        return json.dumps(log_entry, default=str)


def set_correlation_context(
    correlation_id: Optional[str] = None,
    event_id: Optional[int] = None,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
) -> None:
    """
    Set correlation context for the current async task.

    Use this to link logs across a single request/command lifecycle.
    """
    if correlation_id is not None:
        correlation_id_var.set(correlation_id)
    if event_id is not None:
        event_id_var.set(event_id)
    if user_id is not None:
        user_id_var.set(user_id)
    if chat_id is not None:
        chat_id_var.set(chat_id)


def clear_correlation_context() -> None:
    """Clear correlation context."""
    correlation_id_var.set(None)
    event_id_var.set(None)
    user_id_var.set(None)
    chat_id_var.set(None)


def setup_logging(settings: Settings) -> logging.Logger:
    """Set up structured logging for the application."""
    log_level_str = settings.log_level or "INFO"
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # Use JSON formatter in production, readable in dev
    use_json_logs = getattr(settings, "json_logs", False)

    formatter: logging.Formatter
    if use_json_logs:
        formatter = StructuredJsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    telegram_level = getattr(
        logging,
        (settings.log_level_telegram or "INFO").upper(),
        logging.INFO,
    )
    httpx_level = getattr(
        logging,
        (settings.log_level_httpx or "WARNING").upper(),
        logging.WARNING,
    )

    logging.getLogger("telegram").setLevel(telegram_level)
    logging.getLogger("httpx").setLevel(httpx_level)
    logging.captureWarnings(True)

    logger = logging.getLogger("coord_bot")
    logger.info(
        "Logging configured root=%s telegram=%s httpx=%s json=%s",
        log_level_str.upper(),
        logging.getLevelName(telegram_level),
        logging.getLevelName(httpx_level),
        use_json_logs,
    )
    return logger
