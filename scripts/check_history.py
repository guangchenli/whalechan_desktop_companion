"""Check SQLite durability and the right-click history UI using an isolated temporary database."""
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from message_history import PAGE_SIZE
from pet import start_notifications, create_pet, MANIFEST
from check_support import wait_future, wait_idle
from contracts import Notification

app = QApplication([])


def history_menu(pet):
    menu = pet.create_context_menu()
    submenu = next(action.menu() for action in menu.actions() if action.text() == "历史消息")
    return menu, submenu


with TemporaryDirectory(prefix="desktop-pet-history-check-") as temporary:
    db = Path(temporary) / "nested" / "messages.sqlite3"
    pet = create_pet(MANIFEST, 160, history_db=db)
    pet.show()
    try:
        menu, history = history_menu(pet)
        assert history.actions()[0].text() == "暂无历史消息"
        assert not history.actions()[0].isEnabled()
        history.actions()[-1].trigger()
        wait_idle(pet)
        app.processEvents()
        assert pet.history_dialog.isVisible()
        assert pet.history_dialog.messages.count() == 0
        assert not pet.history_dialog.replay.isEnabled()
        assert not pet.history_dialog.delete_checked.isEnabled()
        assert not pet.history_dialog.clear_all.isEnabled()
        menu.deleteLater()

        message = "任务完成啦！✨\n'; DROP TABLE messages; --\n<b>原样保存的中文与 HTML</b>"
        first = wait_future(pet.notification_controller.notify(message, title='Agent & 测试', duration_seconds=120))
        second = wait_future(pet.notification_controller.notify('排队中的通知也会保存', title='第二条', duration_seconds=120, sound=True))
        assert first["status"] == "displayed" and second["status"] == "queued"
        assert wait_future(pet.history.count()) == 2
        assert pet.history_dialog.messages.count() == 2
        rows = wait_future(pet.history.recent())
        assert [row["notification_id"] for row in rows] == [second["id"], first["id"]]
        assert rows[1]["message"] == message
        assert rows[0]["sound"] == 1
        with sqlite3.connect(db) as reader:
            assert reader.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
            assert reader.execute("SELECT message FROM messages WHERE notification_id = ?", (first["id"],)).fetchone()[0] == message

        menu, history = history_menu(pet)
        assert "第二条" in history.actions()[0].text()
        assert "Agent && 测试" in history.actions()[1].text()
        history.actions()[1].trigger()
        wait_idle(pet)
        app.processEvents()
        dialog = pet.history_dialog
        assert dialog.body.toPlainText() == message
        assert dialog.title.text() == "Agent & 测试"
        assert not dialog.body.openExternalLinks()
        selected = dialog.messages.currentItem().data(Qt.ItemDataRole.UserRole)["notification_id"]
        wait_future(pet.notification_controller.notify('正在阅读时收到的新通知', duration_seconds=120))
        assert dialog.messages.currentItem().data(Qt.ItemDataRole.UserRole)["notification_id"] == selected
        assert dialog.body.toPlainText() == message
        assert dialog.messages.count() == 3
        menu.deleteLater()
        current_id = pet.notification_controller.current.id
        queue_size = len(pet.notification_controller.queue)
        with sqlite3.connect(db) as writer:
            writer.execute("BEGIN IMMEDIATE")
            try:
                wait_future(pet.notification_controller.notify('数据库锁定时应返回错误', duration_seconds=120))
                raise AssertionError("Storage failure must not acknowledge or enqueue a notification")
            except ValueError as exc:
                assert "无法保存消息历史" in str(exc)
        assert wait_future(pet.history.count()) == 3
        assert pet.notification_controller.current.id == current_id and len(pet.notification_controller.queue) == queue_size
        print("PASS: empty/recent menu entries, live list updates, full plain text and committed SQLite records")
        print("PASS: database write failure returns an error without changing the queue or stored history")
    finally:
        pet.close()

    # Recreate the pet against the same file: pending popups stay dismissed, history survives.
    pet = create_pet(MANIFEST, 160, history_db=db)
    pet.show()
    try:
        assert wait_future(pet.history.count()) == 3
        assert not pet.notification_controller.queue and pet.notification_controller.current is None
        pet.show_history(second["id"])
        wait_idle(pet)
        dialog = pet.history_dialog
        assert dialog.title.text() == "第二条"
        dialog.replay.click()
        wait_idle(pet)
        assert pet.bubble.body.toPlainText() == "排队中的通知也会保存"
        assert pet.notification_controller.current.sound is False
        assert wait_future(pet.history.count()) == 3
        assert pet.notification_controller.current.id != second["id"]
        assert dialog.feedback.text() == "已重新显示气泡"
        print("PASS: restart durability, queued-message persistence and silent replay without duplicate history")

        for index in range(PAGE_SIZE + 25):
            wait_future(pet.history.add(Notification(**dict(id=uuid.uuid4().hex, title='较早通知', message=f'历史 {index}', duration_seconds=12, sound=False))))
        dialog.refresh()
        wait_idle(pet)
        assert dialog.messages.count() == PAGE_SIZE and dialog.more.isEnabled()
        # A new arrival between pages must not create gaps or duplicate earlier rows.
        wait_future(pet.notification_controller.notify('分页过程中收到的通知', duration_seconds=120))
        assert dialog.messages.count() == PAGE_SIZE + 1
        dialog.more.click()
        wait_idle(pet)
        records = [dialog.messages.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dialog.messages.count())]
        sequences = [record["sequence"] for record in records]
        assert len(sequences) == wait_future(pet.history.count())
        assert sequences == sorted(set(sequences), reverse=True)
        assert not dialog.more.isEnabled()
        print("PASS: history pagination preserves chronological order with no gaps or duplicates during new arrivals")

        dialog.check_all.click()
        wait_idle(pet)
        assert len(dialog.checked_ids) == dialog.messages.count()
        dialog.uncheck_all.click()
        wait_idle(pet)
        assert not dialog.checked_ids and not dialog.delete_checked.isEnabled()
        dialog.messages.setCurrentRow(2)
        preserved_body = dialog.body.toPlainText()
        checked = [dialog.messages.item(0), dialog.messages.item(dialog.messages.count() - 1)]
        deleted_ids = {item.data(Qt.ItemDataRole.UserRole)["notification_id"] for item in checked}
        for item in checked:
            item.setCheckState(Qt.CheckState.Checked)
        assert dialog.checked_ids == deleted_ids and dialog.delete_checked.isEnabled()
        fresh = wait_future(pet.notification_controller.notify('批量选择期间收到的消息', duration_seconds=120))
        assert dialog.checked_ids == deleted_ids
        assert dialog.messages.item(0).checkState() == Qt.CheckState.Unchecked
        before = wait_future(pet.history.count())
        dialog.delete_checked.click()
        wait_idle(pet)
        assert wait_future(pet.history.count()) == before - 2
        assert all(wait_future(pet.history.get(notification_id)) is None for notification_id in deleted_ids)
        assert wait_future(pet.history.get(fresh['id'])) is not None
        assert dialog.body.toPlainText() == preserved_body
        assert len(dialog.checked_ids) == 0 and not dialog.delete_checked.isEnabled()
        assert dialog.messages.count() == wait_future(pet.history.count())
        print("PASS: checkbox selection across pages, select/unselect all, batch deletion and unselected new arrivals")

        # A failed deletion keeps both the database and the selected checkboxes intact.
        item = dialog.messages.item(0)
        item.setCheckState(Qt.CheckState.Checked)
        protected_id = item.data(Qt.ItemDataRole.UserRole)["notification_id"]
        before = wait_future(pet.history.count())
        with sqlite3.connect(db) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with patch.object(QMessageBox, "warning") as warning:
                dialog.delete_checked.click()
                wait_idle(pet)
                warning.assert_called_once()
        assert wait_future(pet.history.count()) == before and wait_future(pet.history.get(protected_id))
        assert dialog.checked_ids == {protected_id}
        print("PASS: failed batch deletion preserves stored messages and selection")

        answers = []

        def answer_confirmation(button):
            popup = app.activeModalWidget()
            assert isinstance(popup, QMessageBox)
            assert popup.standardButton(popup.defaultButton()) == QMessageBox.StandardButton.No
            answers.append(button)
            popup.button(button).click()

        QTimer.singleShot(0, lambda: answer_confirmation(QMessageBox.StandardButton.No))
        dialog.clear_all.click()
        wait_idle(pet)
        assert answers == [QMessageBox.StandardButton.No]
        assert wait_future(pet.history.count()) == before and dialog.checked_ids == {protected_id}

        # Clear all must also erase older rows which are not loaded in the current list.
        dialog.refresh()
        wait_idle(pet)
        assert dialog.messages.count() == PAGE_SIZE and dialog.more.isEnabled()
        QTimer.singleShot(0, lambda: answer_confirmation(QMessageBox.StandardButton.Yes))
        dialog.clear_all.click()
        wait_idle(pet)
        assert wait_future(pet.history.count()) == 0 and dialog.messages.count() == 0
        assert not dialog.checked_ids and dialog.body.toPlainText() == ""
        assert not dialog.replay.isEnabled() and not dialog.more.isEnabled()
        assert not dialog.delete_checked.isEnabled() and not dialog.clear_all.isEnabled()
        menu, history = history_menu(pet)
        assert history.actions()[0].text() == "暂无历史消息"
        menu.deleteLater()
        with sqlite3.connect(db) as reader:
            assert reader.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        print("PASS: cancel/default-safe confirmation, clear unloaded history and synchronize empty UI/menu/database")

        after_clear = wait_future(pet.notification_controller.notify('清空后仍能接收并保存新消息', title='新历史', duration_seconds=120))
        assert wait_future(pet.history.count()) == 1 and dialog.messages.count() == 1
        assert dialog.messages.item(0).checkState() == Qt.CheckState.Unchecked
        assert dialog.clear_all.isEnabled() and not dialog.delete_checked.isEnabled()
    finally:
        pet.close()

    pet = create_pet(MANIFEST, 160, history_db=db)
    try:
        assert wait_future(pet.history.count()) == 1
        assert wait_future(pet.history.recent())[0]["notification_id"] == after_clear["id"]
        assert wait_future(pet.history.get(first['id'])) is None and wait_future(pet.history.get(second['id'])) is None
        assert all(wait_future(pet.history.get(notification_id)) is None for notification_id in deleted_ids)
        print("PASS: deletion persists after restart, while new messages continue to be stored normally")

        for index in range(PAGE_SIZE + 7):
            wait_future(pet.history.add(Notification(**dict(id=uuid.uuid4().hex, title='分页删除', message=f'分页删除 {index}', duration_seconds=12, sound=False))))
        pet.show_history()
        wait_idle(pet)
        dialog = pet.history_dialog
        assert dialog.messages.count() == PAGE_SIZE and dialog.more.isEnabled()
        dialog.check_all.click()
        wait_idle(pet)
        dialog.delete_checked.click()
        wait_idle(pet)
        assert wait_future(pet.history.count()) == 8 and dialog.messages.count() == 8
        assert not dialog.more.isEnabled() and not dialog.checked_ids
        assert dialog.body.toPlainText() != "" and dialog.replay.isEnabled()
        dialog.check_all.click()
        wait_idle(pet)
        dialog.delete_checked.click()
        wait_idle(pet)
        assert wait_future(pet.history.count()) == 0 and dialog.messages.count() == 0
        assert dialog.body.toPlainText() == "" and not dialog.replay.isEnabled()
        assert not dialog.check_all.isEnabled() and not dialog.clear_all.isEnabled()
        print("PASS: deleting all displayed rows loads the next page; deleting the final batch clears details and controls")
    finally:
        pet.close()
