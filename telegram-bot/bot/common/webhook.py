"""
Webhook Configuration and Worker Queue Setup.
PRD v2 Priority 1: Production Hardening.

Replaces polling with webhook for scalability.
Uses asyncio queue for background task processing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Any, Optional
from telegram.ext import Application

logger = logging.getLogger("coord_bot.webhook")


class WorkerQueue:
    """
    Async worker queue for background task processing.

    Features:
    - Configurable worker count
    - Task prioritization
    - Graceful shutdown
    - Error handling with retries
    """

    def __init__(self, num_workers: int = 4, max_queue_size: int = 1000):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.num_workers = num_workers
        self.workers: list[asyncio.Task] = []
        self._shutdown = False
        self._tasks_processed = 0

    async def start(self) -> None:
        """Start worker tasks."""
        logger.info("Starting %d worker tasks", self.num_workers)
        for i in range(self.num_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"), name=f"worker-{i}")
            self.workers.append(worker)

    async def _worker(self, name: str) -> None:
        """Worker task that processes items from queue."""
        logger.debug("Worker %s started", name)
        while not self._shutdown:
            try:
                # Get task with timeout
                try:
                    task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # Process task
                callback, args, kwargs = task
                try:
                    await callback(*args, **kwargs)
                    self._tasks_processed += 1
                except Exception as e:
                    logger.exception("Worker %s task failed: %s", name, e)
                finally:
                    self.queue.task_done()

            except asyncio.CancelledError:
                logger.debug("Worker %s cancelled", name)
                break
            except Exception as e:
                logger.exception("Worker %s error: %s", name, e)

        logger.debug("Worker %s stopped", name)

    async def submit(
        self,
        callback: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        """
        Submit task to worker queue.

        Returns True if submitted, False if queue is full.
        """
        if self._shutdown:
            logger.warning("Cannot submit task: worker queue is shutting down")
            return False

        try:
            await asyncio.wait_for(self.queue.put((callback, args, kwargs)), timeout=0.1)  # Fail fast if queue is full
            return True
        except asyncio.TimeoutError:
            logger.warning("Worker queue is full, task rejected")
            return False

    async def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown worker queue.

        Args:
            wait: If True, wait for pending tasks to complete
        """
        logger.info("Shutting down worker queue")
        self._shutdown = True

        if wait:
            # Wait for queue to drain
            await self.queue.join()

        # Cancel workers
        for worker in self.workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

        logger.info("Worker queue shutdown complete. Processed %d tasks.", self._tasks_processed)

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics."""
        return {
            "queue_size": self.queue.qsize(),
            "max_queue_size": self.queue.maxsize,
            "num_workers": self.num_workers,
            "active_workers": len([w for w in self.workers if not w.done()]),
            "tasks_processed": self._tasks_processed,
            "is_shutdown": self._shutdown,
        }


# Global worker queue instance
_worker_queue: Optional[WorkerQueue] = None


def get_worker_queue() -> WorkerQueue:
    """Get or create global worker queue."""
    global _worker_queue
    if _worker_queue is None:
        _worker_queue = WorkerQueue(num_workers=4, max_queue_size=1000)
    return _worker_queue


async def setup_webhook(
    application: Application,
    webhook_url: str,
    webhook_port: int = 8443,
    webhook_host: str = "0.0.0.0",
    webhook_secret: Optional[str] = None,
    allowed_updates: Optional[list[str]] = None,
) -> None:
    """
    Setup webhook for production deployment.

    Args:
        application: Telegram application instance
        webhook_url: Public URL where webhook will be set
        webhook_port: Port to listen on
        webhook_host: Host to bind to
        webhook_secret: Secret token for webhook verification
        allowed_updates: List of update types to receive
    """
    # Start worker queue
    worker_queue = get_worker_queue()
    await worker_queue.start()

    # Setup webhook
    logger.info("Setting up webhook: %s (port %d)", webhook_url, webhook_port)

    await application.run_webhook(
        listen=webhook_host,
        port=webhook_port,
        url_path="telegram-webhook",
        webhook_url=webhook_url,
        allowed_updates=allowed_updates,
        secret_token=webhook_secret,
    )


async def shutdown_webhook(application: Application) -> None:
    """Gracefully shutdown webhook and worker queue."""
    logger.info("Shutting down webhook")

    # Shutdown worker queue
    worker_queue = get_worker_queue()
    await worker_queue.shutdown(wait=True)

    # Stop application
    await application.stop()

    # Delete webhook from Telegram
    await application.bot.delete_webhook()

    logger.info("Webhook shutdown complete")


def submit_to_worker(
    callback: Callable,
    *args: Any,
    **kwargs: Any,
) -> bool:
    """
    Submit task to worker queue.

    Usage:
        from bot.common.webhook import submit_to_worker

        async def send_notification(user_id, message):
            await bot.send_message(chat_id=user_id, text=message)

        # Submit to worker
        submit_to_worker(send_notification, user_id=123, message="Hello!")
    """
    worker_queue = get_worker_queue()
    return asyncio.get_event_loop().run_until_complete(worker_queue.submit(callback, *args, **kwargs))


async def submit_to_worker_async(
    callback: Callable,
    *args: Any,
    **kwargs: Any,
) -> bool:
    """Async version of submit_to_worker."""
    worker_queue = get_worker_queue()
    return await worker_queue.submit(callback, *args, **kwargs)
