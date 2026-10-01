"""Asynchronous history viewer, with explicit storage and replay dependencies."""
from datetime import datetime
import sqlite3

from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
                            QListWidgetItem, QMessageBox, QPushButton, QSplitter,
                            QTextBrowser, QVBoxLayout, QWidget)

PAGE_SIZE = 100


def local_time(record, short=False):
    timestamp = datetime.fromisoformat(record["received_at"]).astimezone()
    return timestamp.strftime("%m-%d %H:%M" if short else "%Y-%m-%d %H:%M:%S")


class MessageHistoryDialog(QDialog):
    def __init__(self, history, replay_notification, pet_name, parent=None):
        # A user explicitly opens this window; allow keyboard navigation and copying.
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.history = history
        self.replay_notification = replay_notification
        self.busy = False
        self._loading_page = False
        self._pending_added = []
        self._generation = 0
        self._initialized = False
        self._shutdown = False
        self.history.record_added.connect(self.record_added)
        self.total = 0
        self.checked_ids = set()
        self.setWindowTitle(f"历史消息 · {pet_name}")
        self.resize(740, 460)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.summary = QLabel()
        toolbar.addWidget(self.summary, 1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(lambda: self.refresh())
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)

        management = QHBoxLayout()
        self.check_all = QPushButton("全选已显示")
        self.check_all.clicked.connect(lambda: self.set_all_checked(True))
        management.addWidget(self.check_all)
        self.uncheck_all = QPushButton("取消全选")
        self.uncheck_all.clicked.connect(lambda: self.set_all_checked(False))
        management.addWidget(self.uncheck_all)
        self.delete_checked = QPushButton("删除选中")
        self.delete_checked.clicked.connect(self.delete_checked_messages)
        management.addWidget(self.delete_checked)
        management.addStretch()
        self.clear_all = QPushButton("清空全部")
        self.clear_all.clicked.connect(self.clear_history)
        management.addWidget(self.clear_all)
        layout.addLayout(management)

        splitter = QSplitter()
        self.messages = QListWidget()
        self.messages.setMinimumWidth(230)
        self.messages.currentItemChanged.connect(self.select_message)
        self.messages.itemChanged.connect(self.check_changed)
        splitter.addWidget(self.messages)
        details = QWidget()
        detail_layout = QVBoxLayout(details)
        self.title = QLabel("暂无历史消息")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold;")
        self.timestamp = QLabel()
        detail_layout.addWidget(self.title)
        detail_layout.addWidget(self.timestamp)
        self.body = QTextBrowser()
        self.body.setOpenLinks(False)
        self.body.setOpenExternalLinks(False)
        self.body.setPlaceholderText("收到的通知会保存在这里，关闭气泡后也能查看。")
        detail_layout.addWidget(self.body, 1)
        self.replay = QPushButton("重新显示气泡")
        self.replay.setEnabled(False)
        self.replay.clicked.connect(self.replay_selected)
        detail_layout.addWidget(self.replay)
        self.feedback = QLabel()
        detail_layout.addWidget(self.feedback)
        splitter.addWidget(details)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.more = QPushButton("加载更早消息")
        self.more.clicked.connect(self.load_more)
        footer.addWidget(self.more)
        footer.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)

    def add_item(self, record, prepend=False):
        preview = " ".join(record["message"].split())
        if len(preview) > 45:
            preview = preview[:45] + "…"
        item = QListWidgetItem(f"{local_time(record)} · {record['title']}\n{preview}")
        item.setData(Qt.ItemDataRole.UserRole, record)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if record["notification_id"] in self.checked_ids else Qt.CheckState.Unchecked)
        if prepend:
            self.messages.insertItem(0, item)
        else:
            self.messages.addItem(item)

    def update_summary(self):
        checked = len(self.checked_ids)
        self.summary.setText(f"共 {self.total} 条消息 · 已加载 {self.messages.count()} 条 · 已选 {checked} 条")
        self.refresh_button.setEnabled(not self.busy)
        self.replay.setEnabled(not self.busy and self.messages.currentItem() is not None)
        self.more.setEnabled(not self.busy and self.messages.count() < self.total)
        self.check_all.setEnabled(self.messages.count() > 0)
        self.uncheck_all.setEnabled(checked > 0)
        self.delete_checked.setText(f"删除选中（{checked}）" if checked else "删除选中")
        self.delete_checked.setEnabled(not self.busy and checked > 0)
        self.clear_all.setEnabled(not self.busy and self.total > 0)

    def check_changed(self, item):
        notification_id = item.data(Qt.ItemDataRole.UserRole)["notification_id"]
        if item.checkState() == Qt.CheckState.Checked:
            self.checked_ids.add(notification_id)
        else:
            self.checked_ids.discard(notification_id)
        self.update_summary()

    def set_all_checked(self, checked):
        with QSignalBlocker(self.messages):
            for index in range(self.messages.count()):
                item = self.messages.item(index)
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.checked_ids = {
            self.messages.item(index).data(Qt.ItemDataRole.UserRole)["notification_id"]
            for index in range(self.messages.count())
        } if checked else set()
        self.update_summary()

    def _watch(self, future, success, title, release_busy=True, generation=None):
        def finished(result):
            if self._shutdown or generation is not None and generation != self._generation:
                return
            if release_busy:
                self.busy = False
                self.update_summary()
            try:
                value = result.result()
            except (ValueError, sqlite3.Error, RuntimeError) as exc:
                self.busy = False
                self._loading_page = False
                self._flush_added()
                self.update_summary()
                QMessageBox.warning(self, title, str(exc))
                return
            success(value)
        future.add_done_callback(finished)
        return future

    def delete_checked_messages(self):
        ids = set(self.checked_ids)
        if not ids or self.busy:
            return
        self.busy = True
        self.update_summary()

        def deleted(count):
            with QSignalBlocker(self.messages):
                for index in range(self.messages.count() - 1, -1, -1):
                    item = self.messages.item(index)
                    if item.data(Qt.ItemDataRole.UserRole)["notification_id"] in ids:
                        self.messages.takeItem(index)
            self.checked_ids.difference_update(ids)
            self.total = self.history.total
            if self.messages.count() == 0 and self.total:
                self.refresh()
            else:
                if self.messages.currentItem() is None and self.messages.count():
                    self.messages.setCurrentRow(0)
                self.select_message(self.messages.currentItem(), None)
                self.update_summary()
            self.feedback.setText(f"已删除 {count} 条历史消息")

        return self._watch(self.history.delete(ids), deleted, "删除消息失败")

    def clear_history(self):
        if self.total == 0 or self.busy:
            return
        answer = QMessageBox.question(
            self, "清空历史消息", "确定永久删除全部历史消息吗？\n包括尚未加载的消息，删除后无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # The confirmation runs a nested Qt loop; another request may have started.
        if self.busy or self._shutdown:
            return
        self.busy = True
        self.update_summary()

        def cleared(count):
            self.checked_ids.clear()
            self.messages.clear()
            self.select_message(None, None)
            self.total = 0
            self.update_summary()
            self.feedback.setText(f"已清空 {count} 条历史消息")

        return self._watch(self.history.delete_all(), cleared, "清空历史失败")

    def refresh(self, selected_id=None):
        if self._shutdown:
            return
        selected = self.messages.currentItem()
        if selected_id is None and selected:
            selected_id = selected.data(Qt.ItemDataRole.UserRole)["notification_id"]
        self._generation += 1
        generation = self._generation
        self.busy = self._loading_page = True
        self.update_summary()

        def refreshed(page):
            if generation != self._generation:
                return
            total, records = page
            rows = [record.to_dict() for record in records]
            self.total = total
            self.checked_ids.intersection_update(record["notification_id"] for record in rows)
            with QSignalBlocker(self.messages):
                self.messages.clear()
                for record in rows:
                    self.add_item(record)
            self.busy = self._loading_page = False
            self._initialized = True
            # Buffered arrivals already included in this snapshot must not be
            # inserted again, including ones outside its first page.
            newest = records[0].sequence if records else 0
            self._pending_added = [record for record in self._pending_added if record.sequence > newest]
            self._flush_added()
            selected_row = 0
            for index in range(self.messages.count()):
                record = self.messages.item(index).data(Qt.ItemDataRole.UserRole)
                if record["notification_id"] == selected_id:
                    selected_row = index
                    break
            if self.messages.count():
                self.messages.setCurrentRow(selected_row)
            else:
                self.select_message(None, None)
            self.update_summary()

        return self._watch(self.history.page(PAGE_SIZE), refreshed, "读取历史失败",
                           release_busy=False, generation=generation)

    def load_more(self):
        last = self.messages.item(self.messages.count() - 1)
        if last is None or self.busy:
            return
        before = last.data(Qt.ItemDataRole.UserRole)["sequence"]
        self._generation += 1
        generation = self._generation
        self.busy = self._loading_page = True
        self.update_summary()

        def loaded(page):
            total, records = page
            existing = self._displayed_ids()
            for record in records:
                if record.notification_id not in existing:
                    self.add_item(record.to_dict())
            self.total = total
            self.busy = self._loading_page = False
            self._flush_added()
            self.update_summary()

        return self._watch(self.history.page(PAGE_SIZE, before=before), loaded, "读取历史失败",
                           release_busy=False, generation=generation)

    def _displayed_ids(self):
        return {self.messages.item(index).data(Qt.ItemDataRole.UserRole)["notification_id"]
                for index in range(self.messages.count())}

    def _flush_added(self):
        records, self._pending_added = self._pending_added, []
        for record in records:
            self.record_added(record)

    def record_added(self, record):
        if self._shutdown:
            return
        if self._loading_page:
            self._pending_added.append(record)
            return
        if not self._initialized:
            return
        if record.notification_id not in self._displayed_ids():
            self.add_item(record.to_dict(), prepend=True)
        self.total = self.history.total
        if self.messages.currentItem() is None:
            self.messages.setCurrentRow(0)
        self.update_summary()

    def select_message(self, current, previous):
        self.feedback.clear()
        self.replay.setEnabled(not self.busy and current is not None)
        if current is None:
            self.title.setText("暂无历史消息")
            self.timestamp.clear()
            self.body.clear()
            return
        record = current.data(Qt.ItemDataRole.UserRole)
        self.title.setText(record["title"])
        self.timestamp.setText(local_time(record))
        self.body.setPlainText(record["message"])

    def replay_selected(self):
        item = self.messages.currentItem()
        if item is None or self.busy:
            return
        try:
            future = self.replay_notification(item.data(Qt.ItemDataRole.UserRole)["notification_id"])
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "无法重新显示消息", str(exc))
            return
        self.busy = True
        self.update_summary()
        return self._watch(future, lambda result: self.feedback.setText(
            "已加入通知队列" if result["status"] == "queued" else "已重新显示气泡"), "无法重新显示消息")

    def shutdown(self):
        if self._shutdown:
            return
        self._shutdown = True
        self.history.record_added.disconnect(self.record_added)
        self.close()
