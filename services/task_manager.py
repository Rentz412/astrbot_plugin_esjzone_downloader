from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class TaskManager:
    def __init__(self) -> None:
        self._book_locks: dict[str, asyncio.Lock] = {}
        self._session_tasks: set[str] = set()

    def is_session_busy(self, session_key: str) -> bool:
        return session_key in self._session_tasks

    def mark_session(self, session_key: str) -> None:
        self._session_tasks.add(session_key)

    def unmark_session(self, session_key: str) -> None:
        self._session_tasks.discard(session_key)

    def book_lock(self, book_id: str) -> asyncio.Lock:
        lock = self._book_locks.get(book_id)
        if lock is None:
            lock = asyncio.Lock()
            self._book_locks[book_id] = lock
        return lock

    @asynccontextmanager
    async def session_guard(self, session_key: str) -> AsyncIterator[None]:
        self.mark_session(session_key)
        try:
            yield
        finally:
            self.unmark_session(session_key)
