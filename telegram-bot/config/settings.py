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

        # Connection pool. Sized *per process*: with N app processes the
        # database sees N * (pool_size + max_overflow) connections at peak, so
        # these must come down as the instance count goes up rather than being
        # hardcoded. PostgreSQL's own max_connections is the ceiling.
        self.db_pool_size: int = int(os.environ.get("DB_POOL_SIZE", "10"))
        self.db_max_overflow: int = int(os.environ.get("DB_MAX_OVERFLOW", "20"))
        # Recycle below the shortest idle timeout in the path (PgBouncer,
        # load balancers, and cloud proxies all silently drop idle sockets).
        # Without this the pool hands out connections the server already closed.
        self.db_pool_recycle: int = int(os.environ.get("DB_POOL_RECYCLE", "1800"))
        # Fail fast instead of stacking requests on an exhausted pool.
        self.db_pool_timeout: int = int(os.environ.get("DB_POOL_TIMEOUT", "30"))
        self.db_echo: bool = os.environ.get("DB_ECHO", "false").lower() == "true"

        # Shared state (conversation flows, rate limits). Unset means
        # in-process state, which is correct for one instance and silently
        # wrong for several -- see core/state.py.
        self.redis_url: str | None = os.environ.get("REDIS_URL") or None
        self.state_namespace: str = os.environ.get("STATE_NAMESPACE", "zwischen")

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
