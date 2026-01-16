"""GTFS-RT automatic fetcher scheduler.

This module provides a background scheduler that automatically fetches
GTFS-RT data at regular intervals.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from sqlalchemy.orm import Session

from core.database import SessionLocal
from src.gtfs_bc.realtime.infrastructure.services.gtfs_rt_fetcher import GTFSRealtimeFetcher

logger = logging.getLogger(__name__)


class GTFSRTScheduler:
    """Background scheduler for GTFS-RT data fetching."""

    # Fetch interval in seconds (30 seconds for real-time accuracy)
    FETCH_INTERVAL = 30

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_fetch: Optional[datetime] = None
        self._fetch_count = 0
        self._error_count = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> dict:
        """Get scheduler status."""
        return {
            "running": self._running,
            "last_fetch": self._last_fetch.isoformat() if self._last_fetch else None,
            "fetch_count": self._fetch_count,
            "error_count": self._error_count,
            "interval_seconds": self.FETCH_INTERVAL,
        }

    async def start(self):
        """Start the background fetch task."""
        if self._running:
            logger.warning("GTFS-RT scheduler already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._fetch_loop())
        logger.info(f"GTFS-RT scheduler started (interval: {self.FETCH_INTERVAL}s)")

    async def stop(self):
        """Stop the background fetch task."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("GTFS-RT scheduler stopped")

    async def _fetch_loop(self):
        """Main fetch loop that runs in background."""
        # Initial delay to let the app fully start
        await asyncio.sleep(5)

        while self._running:
            try:
                await self._do_fetch()
            except Exception as e:
                self._error_count += 1
                logger.error(f"GTFS-RT fetch error: {e}")

            # Wait for next interval
            await asyncio.sleep(self.FETCH_INTERVAL)

    async def _do_fetch(self):
        """Perform a single GTFS-RT fetch."""
        # Run the synchronous fetch in a thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._fetch_sync)

        self._last_fetch = datetime.utcnow()
        self._fetch_count += 1

        if result:
            logger.info(
                f"GTFS-RT auto-fetch #{self._fetch_count}: "
                f"{result.get('vehicle_positions', 0)} positions, "
                f"{result.get('trip_updates', 0)} updates, "
                f"{result.get('alerts', 0)} alerts"
            )

    def _fetch_sync(self) -> dict:
        """Synchronous fetch operation."""
        db = SessionLocal()
        try:
            fetcher = GTFSRealtimeFetcher(db)
            return fetcher.fetch_all_sync()
        finally:
            db.close()


# Global scheduler instance
gtfs_rt_scheduler = GTFSRTScheduler()


@asynccontextmanager
async def lifespan_with_scheduler(app):
    """FastAPI lifespan context manager that starts/stops the scheduler."""
    # Startup
    await gtfs_rt_scheduler.start()
    yield
    # Shutdown
    await gtfs_rt_scheduler.stop()
