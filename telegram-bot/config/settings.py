"""
Application configuration management.
Loads environment variables and provides centralized access to settings.
PRD v2: Updated for production hardening.
"""

import os
from dotenv import load_dotenv

from db.url import normalize_db_url


load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        # Telegram
        self.telegram_token: str | None = os.environ.get("TELEGRAM_TOKEN")

        # Database. Normalized here so every consumer (handlers, services,
        # scheduler) gets an async-driver URL, not just the startup path.
        self.db_url: str | None = normalize_db_url(os.environ.get("DB_URL"))

        # AI/LLM
        self.ai_endpoint: str = os.environ.get(
            "AI_ENDPOINT", "http://127.0.0.1:8080/v1/"
        )
        self.ai_model: str = os.environ.get("AI_MODEL", "qwen/qwen3-coder-next")
        self.ai_api_key: str = os.environ.get("AI_API_KEY", "dummy-key")

        # Where PicklePersistence stores conversation state. Must point at a
        # mounted volume in containers, otherwise in-flight event-creation
        # flows are lost on every restart.
        self.persistence_path: str = os.environ.get(
            "BOT_PERSISTENCE_PATH", "bot_data.pkl"
        )

        # Logging
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO")
        self.log_level_telegram: str = os.environ.get("LOG_LEVEL_TELEGRAM", "INFO")
        self.log_level_httpx: str = os.environ.get("LOG_LEVEL_HTTPX", "WARNING")
        self.json_logs: bool = os.environ.get("JSON_LOGS", "false").lower() == "true"

        # PRD v2: Feature flags
        self.enable_materialization: bool = (
            os.environ.get("ENABLE_MATERIALIZATION", "true").lower() == "true"
        )
        self.enable_memory_layer: bool = (
            os.environ.get("ENABLE_MEMORY_LAYER", "true").lower() == "true"
        )

        # PRD v2: Production settings
        self.environment: str = os.environ.get(
            "ENVIRONMENT", "development"
        )  # development, staging, production
        self.enable_idempotency: bool = (
            os.environ.get("ENABLE_IDEMPOTENCY", "false").lower() == "true"
        )
        self.webhook_url: str | None = os.environ.get("WEBHOOK_URL")
        self.webhook_port: int = int(os.environ.get("WEBHOOK_PORT", "8443"))
        self.webhook_secret: str | None = os.environ.get("WEBHOOK_SECRET")
        self.webhook_host: str = os.environ.get("WEBHOOK_HOST", "0.0.0.0")


settings = Settings()
