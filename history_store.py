"""SQLite repository. No Qt dependency; use a connection only on its owning thread."""
from pathlib import Path
import sqlite3

from contracts import Notification, HistoryRecord

DEFAULT_HISTORY_DB = Path(__file__).resolve().parent / "data" / "messages.sqlite3"


class MessageHistory:
    def __init__(self, path=DEFAULT_HISTORY_DB):
        if str(path) != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            path = Path(path).expanduser()
        self.path = str(path)
        self.connection = sqlite3.connect(self.path, timeout=1)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT NOT NULL UNIQUE,
                    received_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    sound INTEGER NOT NULL CHECK (sound IN (0, 1))
                )
            """)
            self.connection.commit()
        except sqlite3.Error:
            self.connection.close()
            raise

    def add(self, notification: Notification) -> HistoryRecord:
        received_at = notification.received_at
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO messages (notification_id, received_at, title, message, duration_seconds, sound) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (notification.id, received_at, notification.title, notification.message,
                 notification.duration_seconds, int(notification.sound)),
            )
        return HistoryRecord(sequence=cursor.lastrowid, notification_id=notification.id,
                    received_at=received_at, title=notification.title, message=notification.message,
                    duration_seconds=notification.duration_seconds, sound=notification.sound)

    def recent(self, limit=20, before=None):
        if before is None:
            rows = self.connection.execute("SELECT * FROM messages ORDER BY sequence DESC LIMIT ?", (limit,))
        else:
            rows = self.connection.execute(
                "SELECT * FROM messages WHERE sequence < ? ORDER BY sequence DESC LIMIT ?", (before, limit),
            )
        return [HistoryRecord.from_row(row) for row in rows]

    def get(self, notification_id):
        row = self.connection.execute("SELECT * FROM messages WHERE notification_id = ?", (notification_id,)).fetchone()
        return HistoryRecord.from_row(row) if row else None

    def count(self):
        return self.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def delete(self, notification_ids):
        ids = list(dict.fromkeys(notification_ids))
        if not ids:
            return 0
        # One transaction, with bound parameters and no limit on the batch's size.
        with self.connection:
            cursor = self.connection.executemany(
                "DELETE FROM messages WHERE notification_id = ?", ((notification_id,) for notification_id in ids),
            )
        return cursor.rowcount

    def delete_all(self):
        with self.connection:
            cursor = self.connection.execute("DELETE FROM messages")
        return cursor.rowcount

    def page(self, limit=100, before=None):
        # Both reads run in one snapshot, even if a separate process writes this DB.
        self.connection.execute("BEGIN")
        try:
            return self.count(), self.recent(limit, before)
        finally:
            self.connection.rollback()

    def close(self):
        self.connection.close()
