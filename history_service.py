"""Serialize SQLite work on one thread and deliver Future results on the Qt thread."""
from concurrent.futures import Future, ThreadPoolExecutor
import logging
import sqlite3

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

from history_store import DEFAULT_HISTORY_DB, MessageHistory

logger = logging.getLogger(__name__)


class HistoryService(QObject):
    record_added = pyqtSignal(object)
    changed = pyqtSignal()
    _completed = pyqtSignal(object, object, object, object)

    def __init__(self, path=DEFAULT_HISTORY_DB, parent=None):
        super().__init__(parent)
        self.closed = False
        self.total = 0
        self.recent_records = []
        self.error = None
        self._pending = set()
        self._work = set()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pet-history")
        self._completed.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        # Bootstrap happens before the window is displayed. All connection access,
        # including construction and shutdown, belongs to this worker.
        try:
            self._store = self._executor.submit(MessageHistory, path).result()
            self.total, self.recent_records = self._executor.submit(self._store.page, 20).result()
        except Exception:
            if hasattr(self, "_store"):
                self._executor.submit(self._store.close).result()
            self._executor.shutdown(wait=True)
            raise

    def _submit(self, operation, *args, **kwargs):
        if self.closed:
            raise sqlite3.ProgrammingError("消息历史连接已关闭")
        result = Future()
        # Submission starts ownership of this operation. Shutdown handles queued
        # cancellation; callers observe the result without cancelling the reply.
        result.set_running_or_notify_cancel()
        self._pending.add(result)

        def run():
            value = getattr(self._store, operation)(*args, **kwargs)
            # Cache updates are read on the worker and applied only on the GUI thread.
            # Failure to refresh the cache must not turn a committed write into rejection.
            cache = None
            cache_error = None
            if operation in ("add", "delete", "delete_all"):
                try:
                    cache = self._store.page(20)
                except sqlite3.Error as exc:
                    cache_error = exc
                    logger.warning("History committed but cache refresh failed: %s", exc)
            return value, cache, cache_error

        def finished(work):
            try:
                outcome = work.result()
                error = None
            except Exception as exc:
                outcome, error = None, exc
            self._completed.emit(result, operation, outcome, error)

        work = self._executor.submit(run)
        self._work.add(work)
        work.add_done_callback(finished)
        return result

    @pyqtSlot(object, object, object, object)
    def _deliver(self, future, operation, outcome, error):
        if future not in self._pending:
            return
        self._pending.discard(future)
        self._work = {work for work in self._work if not work.done()}
        if error is not None:
            self.error = error
            future.set_exception(error)
            return
        value, cache, cache_error = outcome
        self.error = cache_error
        if cache is not None:
            self.total, self.recent_records = cache
        if operation == "add":
            self.record_added.emit(value)
        if operation in ("add", "delete", "delete_all"):
            self.changed.emit()
        future.set_result(value)

    def add(self, notification):
        return self._submit("add", notification)

    def recent(self, limit=20, before=None):
        return self._submit("recent", limit, before)

    def page(self, limit=100, before=None):
        return self._submit("page", limit, before)

    def get(self, notification_id):
        return self._submit("get", notification_id)

    def count(self):
        return self._submit("count")

    def delete(self, notification_ids):
        return self._submit("delete", tuple(notification_ids))

    def delete_all(self):
        return self._submit("delete_all")

    def close(self):
        if self.closed:
            return
        self.closed = True
        # All acknowledged writes have already committed. Cancel queued operations
        # that have not started; finish the active operation before closing the DB.
        # No callback may reopen UI or acknowledge a request during shutdown.
        for work in tuple(self._work):
            work.cancel()
        self._executor.submit(self._store.close).result()
        self._executor.shutdown(wait=True)
        self._work.clear()
        pending, self._pending = self._pending, set()
        for future in pending:
            future.set_exception(RuntimeError("桌宠正在退出"))
