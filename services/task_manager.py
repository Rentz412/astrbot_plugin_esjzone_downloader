"""下载任务并发控制模块。

提供会话级和书籍级锁，防止同一会话或同一本书的重复下载任务互相覆盖。"""

from __future__ import annotations

import asyncio


class TaskManager:
    """维护运行中的任务标记和书籍下载锁。"""
    def __init__(self):
        """初始化对象依赖和运行时目录。"""
        self.book_locks: dict[str, asyncio.Lock] = {}
        self.session_tasks: set[str] = set()

    def book_lock(self, book_id: str) -> asyncio.Lock:
        """获取指定书籍的异步锁。"""
        if book_id not in self.book_locks:
            self.book_locks[book_id] = asyncio.Lock()
        return self.book_locks[book_id]

    def enter_session(self, key: str) -> bool:
        """尝试登记会话任务，已存在时返回 False。"""
        if key in self.session_tasks:
            return False
        self.session_tasks.add(key)
        return True

    def leave_session(self, key: str) -> None:
        """移除会话任务标记。"""
        self.session_tasks.discard(key)
