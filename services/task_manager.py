from __future__ import annotations

import asyncio


class TaskManager:
    def __init__(self):
        self.book_locks: dict[str, asyncio.Lock] = {}
        self.session_tasks: set[str] = set()

    def book_lock(self, book_id: str) -> asyncio.Lock:
        if book_id not in self.book_locks:
            self.book_locks[book_id] = asyncio.Lock()
        return self.book_locks[book_id]

    def enter_session(self, key: str) -> bool:
        if key in self.session_tasks:
            return False
        self.session_tasks.add(key)
        return True

    def leave_session(self, key: str) -> None:
        self.session_tasks.discard(key)
