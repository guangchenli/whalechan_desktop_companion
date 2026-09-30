"""Notification capacity, durable acceptance, FIFO display and silent replay."""
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
import sqlite3

from PyQt6.QtCore import QObject, pyqtSignal

from contracts import MAX_QUEUE, Notification, validate_notification


@dataclass
class PendingNotification:
    result: Future
    notification: Notification | None = None
    storage: Future | None = None


class NotificationController(QObject):
    changed = pyqtSignal(object, int)
    presented = pyqtSignal(object)

    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.history = history
        self.queue = deque()
        self.current = None
        self._pending = deque()
        self.closed = False

    def _reserve(self):
        if self.closed:
            raise ValueError("桌宠正在退出")
        # One displayed notification plus MAX_QUEUE waiting notifications. Pending
        # writes and replay lookups occupy capacity before touching the database.
        occupied = len(self.queue) + len(self._pending) + (self.current is not None)
        if occupied >= MAX_QUEUE + 1:
            raise ValueError("桌宠通知队列已满，请稍后重试")
        pending = PendingNotification(Future())
        pending.result.set_running_or_notify_cancel()
        self._pending.append(pending)
        return pending

    def notify(self, message, title="Agent", duration_seconds=12, sound=False):
        notification = Notification(**validate_notification(message, title, duration_seconds, sound))
        pending = self._reserve()
        pending.notification = notification
        try:
            pending.storage = self.history.add(notification)
        except Exception as exc:
            pending.storage = Future()
            pending.storage.set_exception(exc)
        pending.storage.add_done_callback(lambda _: self._drain())
        return pending.result

    def replay(self, notification_id):
        pending = self._reserve()
        try:
            pending.storage = self.history.get(notification_id)
        except Exception as exc:
            pending.storage = Future()
            pending.storage.set_exception(exc)
        pending.storage.add_done_callback(lambda _: self._drain())
        return pending.result

    def _drain(self):
        # Results enter the display queue in request order, including replay requests.
        while not self.closed and self._pending and self._pending[0].storage.done():
            pending = self._pending.popleft()
            try:
                record = pending.storage.result()
                notification = pending.notification
                if notification is None:
                    if record is None:
                        raise ValueError("这条历史消息不存在")
                    notification = Notification(**validate_notification(
                        record.message, record.title, record.duration_seconds, False))
            except Exception as exc:
                if isinstance(exc, sqlite3.Error):
                    operation = "保存" if pending.notification is not None else "读取"
                    exc = ValueError(f"无法{operation}消息历史：{exc}")
                pending.result.set_exception(exc)
                continue
            queued = self.current is not None
            self.queue.append(notification)
            if queued:
                self.changed.emit(self.current, len(self.queue))
            else:
                self.dismiss()
            pending.result.set_result(dict(status="queued" if queued else "displayed",
                                           id=notification.id, queued=len(self.queue)))

    def dismiss(self):
        self.current = self.queue.popleft() if self.queue else None
        self.changed.emit(self.current, len(self.queue))
        if self.current is not None:
            self.presented.emit(self.current)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.queue.clear()
        self.current = None
        pending, self._pending = self._pending, deque()
        for item in pending:
            item.result.set_exception(ValueError("桌宠正在退出"))
        self.changed.emit(None, 0)
