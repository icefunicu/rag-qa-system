from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

from shared.auth import AuthUser, permissions_for_role

from .kb_runtime import logger


SYSTEM_SCHEDULER_USER = AuthUser(
    user_id="kb-connector-scheduler",
    email="kb-connector-scheduler@local",
    role="platform_admin",
    permissions=permissions_for_role("platform_admin"),
)


class ConnectorSchedulerManager:
    def __init__(
        self,
        *,
        has_active_schedules: Callable[[], bool],
        run_due_batch: Callable[..., dict],
        min_poll_seconds: int = 15,
        max_batch_size: int = 8,
    ) -> None:
        self._has_active_schedules = has_active_schedules
        self._run_due_batch = run_due_batch
        self._min_poll_seconds = max(int(min_poll_seconds or 15), 5)
        self._max_batch_size = max(int(max_batch_size or 8), 1)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        if self._wake_event is None:
            self._wake_event = asyncio.Event()

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def reconcile(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._reconcile_on_loop)

    async def shutdown(self) -> None:
        if self._loop is None:
            return
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is self._loop:
            await self._shutdown_on_loop()
            return
        future = asyncio.run_coroutine_threadsafe(self._shutdown_on_loop(), self._loop)
        future.result(timeout=10)

    def _reconcile_on_loop(self) -> None:
        active = bool(self._has_active_schedules())
        if active and not self.running():
            self._task = asyncio.create_task(self._run_loop(), name="kb-connector-scheduler")
            logger.info("kb connector scheduler started")
            return
        if not active and self.running() and self._task is not None:
            self._task.cancel()
            if self._wake_event is not None:
                self._wake_event.set()
            logger.info("kb connector scheduler stopped because no active schedules remain")
            return
        if active and self._wake_event is not None:
            self._wake_event.set()

    async def _shutdown_on_loop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._wake_event is not None:
            self._wake_event.clear()

    async def _run_loop(self) -> None:
        if self._wake_event is None:
            self._wake_event = asyncio.Event()
        try:
            while self._has_active_schedules():
                try:
                    result = await asyncio.to_thread(
                        self._run_due_batch,
                        limit=self._max_batch_size,
                        dry_run=False,
                        user=SYSTEM_SCHEDULER_USER,
                    )
                    count = int(result.get("count") or 0)
                    if count:
                        logger.info("kb connector scheduler executed %s due connectors", count)
                except Exception:
                    logger.exception("kb connector scheduler batch execution failed")
                self._wake_event.clear()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=self._min_poll_seconds)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        finally:
            self._task = None


__all__ = ["ConnectorSchedulerManager", "SYSTEM_SCHEDULER_USER"]
