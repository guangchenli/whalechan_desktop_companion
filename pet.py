"""Native PyQt6 desktop companion using the original dsh-web assets."""
import argparse
import ctypes
import os
from pathlib import Path
import random
import sqlite3
import sys

from PyQt6.QtCore import QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from animation import AnimationPlayer
from history_service import HistoryService
from history_store import DEFAULT_HISTORY_DB
from message_history import MessageHistoryDialog, local_time
from notification_controller import NotificationController
from pet_assets import AssetLoadError, LABELS, Pet
from pet_commands import PetCommands
from pet_ipc import PetIPCServer
from speech_bubble import SpeechBubble

ASSETS = Path(__file__).resolve().parent / "assets"
MANIFEST = ASSETS / "whale-refined" / "pet.json"
OVERLAY_FLAGS = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)


def mouse_only(widget):
    widget.setWindowFlags(OVERLAY_FLAGS)
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    widget.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus)


class DesktopPet(QWidget):
    def __init__(self, pet, size, history, notifications, animation):
        super().__init__()
        self.pet = pet
        self.display_size = size
        self.pressed = None
        self.dragged = False
        self.history = history
        self.notification_controller = notifications
        self.animation = animation
        self.ipc = None
        self.history_dialog = None
        self._closed = False
        mouse_only(self)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("左键拖动 · 点击互动 · 右键菜单 · 滚轮缩放")
        self.setWindowTitle(f"桌面宠物 · {pet.name}")
        self.bubble = SpeechBubble(self, mouse_only)
        self.bubble.dismissed.connect(notifications.dismiss)
        notifications.changed.connect(self.display_notification)
        notifications.presented.connect(lambda notification: QApplication.beep() if notification.sound else None)
        animation.frame_changed.connect(self.update)
        self.resize_pet(size)

    def display_notification(self, notification, queued):
        if notification is None:
            self.bubble.hide()
        elif self.bubble.isVisible() and self.bubble.notification_id == notification.id:
            self.bubble.set_queue_count(queued)
        else:
            self.bubble.present(notification, queued)

    def show_history(self, selected_id=None):
        if self._closed:
            return
        if self.history_dialog is None:
            self.history_dialog = MessageHistoryDialog(
                self.history, self.notification_controller.replay, self.pet.name, self)
        self.history_dialog.refresh(selected_id)
        self.history_dialog.show()
        self.history_dialog.raise_()
        self.history_dialog.activateWindow()

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "bubble") and self.bubble.isVisible():
            self.bubble.reposition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "bubble") and self.bubble.isVisible():
            self.bubble.reposition()

    def closeEvent(self, event):
        if not self._closed:
            self._closed = True
            self.animation.close()
            if self.ipc:
                self.ipc.close()
            if self.history_dialog:
                self.history_dialog.shutdown()
            self.notification_controller.close()
            self.history.close()
        super().closeEvent(event)

    def resize_pet(self, size):
        self.display_size = max(96, min(640, size))
        ratio = self.display_size / max(self.pet.width, self.pet.height)
        self.setFixedSize(round(self.pet.width * ratio), round(self.pet.height * ratio))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pixmap = self.pet.pixmap(self.animation.track_name, self.animation.frame)
        fitted = pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF((self.width() - fitted.width()) / 2, (self.height() - fitted.height()) / 2,
                        fitted.width(), fitted.height())
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed = event.globalPosition().toPoint()
            self.origin = self.pos()
            self.dragged = False

    def mouseMoveEvent(self, event):
        if self.pressed is None:
            return
        delta = event.globalPosition().toPoint() - self.pressed
        if not self.dragged and delta.manhattanLength() >= QApplication.startDragDistance():
            self.dragged = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if QApplication.platformName().startswith("wayland"):
                # Wayland disallows client positioning; the compositor owns this drag.
                self.windowHandle().startSystemMove()
        if self.dragged and not QApplication.platformName().startswith("wayland"):
            self.move(self.origin + delta)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.pressed is not None:
            if not self.dragged:
                choices = [n for n in ("shy", "happy", "waving", "jumping") if n in self.pet.tracks]
                if choices:
                    self.animation.play(random.choice(choices), once=True)
            self.pressed = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event):
        self.resize_pet(self.display_size + (24 if event.angleDelta().y() > 0 else -24))

    def create_context_menu(self):
        menu = QMenu(self)
        menu.addAction(self.pet.name).setEnabled(False)
        actions = menu.addMenu("动作 / 换装")
        for name in self.pet.tracks:
            action = actions.addAction(LABELS.get(name, name))
            action.triggered.connect(lambda checked, n=name: self.animation.play(n))
        scale = menu.addMenu("大小")
        for size in (160, 240, 320, 480):
            scale.addAction(f"{size} px", lambda s=size: self.resize_pet(s))
        pause = menu.addAction("暂停动画")
        pause.setCheckable(True)
        pause.setChecked(self.animation.paused)
        pause.triggered.connect(self.animation.toggle_pause)
        if self.notification_controller.current:
            menu.addAction("收起通知 / 下一条", self.bubble.dismiss)
        history = menu.addMenu("历史消息")
        history_available = self.history.error is None
        recent = [record.to_dict() for record in self.history.recent_records]
        if not history_available:
            history.addAction("历史消息暂不可用").setEnabled(False)
        if history_available and not recent:
            history.addAction("暂无历史消息").setEnabled(False)
        for record in recent:
            preview = " ".join(record["message"].split())
            if len(preview) > 30:
                preview = preview[:30] + "…"
            label = f"{local_time(record, short=True)} · {record['title'][:20]} · {preview}"
            action = history.addAction(label.replace("&", "&&"))
            action.triggered.connect(lambda checked, n=record["notification_id"]:
                                     QTimer.singleShot(0, lambda: self.show_history(n)))
        history.addSeparator()
        history.addAction("查看 / 管理全部消息…", lambda: QTimer.singleShot(0, lambda: self.show_history()))
        menu.addSeparator()
        menu.addAction("退出", self.close)
        return menu

    def contextMenuEvent(self, event):
        menu = self.create_context_menu()
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()


def create_pet(manifest, size, history_db=DEFAULT_HISTORY_DB, server_name=None):
    """Composition root: validate assets, assemble services and optionally start IPC."""
    pet = Pet(manifest)
    history = HistoryService(history_db)
    window = None
    animation = None
    try:
        notifications = NotificationController(history)
        animation = AnimationPlayer(pet)
        window = DesktopPet(pet, size, history, notifications, animation)
        history.setParent(window)
        notifications.setParent(window)
        animation.setParent(window)
        if server_name is not None:
            start_notifications(window, server_name)
        return window
    except Exception:
        if window is not None:
            window.close()
        else:
            if animation is not None:
                animation.close()
            history.close()
        raise


def start_notifications(window, server_name=None):
    ipc = PetIPCServer(PetCommands(window.notification_controller, window.animation), server_name, window)
    ipc.start()
    window.ipc = ipc


def configure_platform():
    """GNOME exposes keep-above to XWayland clients, not Qt's xdg-shell windows."""
    if (sys.platform.startswith("linux") and os.environ.get("DISPLAY")
            and os.environ.get("XDG_SESSION_TYPE") == "wayland"
            and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    if os.environ.get("QT_QPA_PLATFORM") == "xcb":
        local_cursor = ASSETS.parent / ".native/usr/lib64/libxcb-cursor.so.0"
        if local_cursor.exists():
            ctypes.CDLL(str(local_cursor), mode=ctypes.RTLD_GLOBAL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=320, help="窗口最长边像素数")
    parser.add_argument("--check", action="store_true", help="离屏验证动画帧及窗口，不打开桌面窗口")
    parser.add_argument("--socket", help="本机通知 IPC 名称，默认按项目路径和用户生成")
    parser.add_argument("--history-db", type=Path, default=DEFAULT_HISTORY_DB, help="消息历史 SQLite 文件路径")
    args = parser.parse_args()
    if not MANIFEST.is_file():
        parser.error("缺少鲸鱼娘（精致版）素材，请运行 python scripts/fetch_assets.py")
    if args.check:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    configure_platform()
    app = QApplication([sys.argv[0]])
    if args.check:
        pet = Pet(MANIFEST)
        count = 0
        for name, track in pet.tracks.items():
            assert track.loop or track.fallback in pet.tracks, name
            assert len(track.frames) == len(track.durations) and min(track.durations) > 0
            for i in range(len(track.frames)):
                pixmap = pet.pixmap(name, i)
                assert pixmap.hasAlphaChannel(), (name, i)
                count += 1
        print(f"OK whale-refined: {len(pet.tracks)} tracks, {count} transparent frames", flush=True)
        window = create_pet(MANIFEST, args.size, history_db=":memory:")
        window.show()
        app.processEvents()
        assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        result = QImage(window.size(), QImage.Format.Format_ARGB32)
        result.fill(Qt.GlobalColor.transparent)
        window.render(result)
        assert result.pixelColor(0, 0).alpha() == 0
        assert any(result.pixelColor(x, y).alpha() > 0 for x in range(0, result.width(), 8)
                   for y in range(0, result.height(), 8))
        window.close()
        print("OK frameless window and transparent rendering")
        return 0
    try:
        window = create_pet(MANIFEST, args.size, history_db=args.history_db)
        start_notifications(window, args.socket)
    except (AssetLoadError, RuntimeError, sqlite3.Error, OSError) as exc:
        if "window" in locals():
            window.close()
        parser.error(str(exc))
    area = app.primaryScreen().availableGeometry()
    if not QApplication.platformName().startswith("wayland"):
        window.move(area.bottomRight() - QPoint(window.width() + 40, window.height() + 30))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
