"""Run a short, real-desktop XWayland stacking/menu regression check."""
import sys
from pathlib import Path
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pet import MANIFEST, create_pet, configure_platform
from check_support import wait_future, wait_idle
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

configure_platform()
app = QApplication([])
assert app.platformName() == "xcb", "This integration check requires XWayland/X11"
normal = QWidget()
normal.setWindowTitle("Desktop pet — temporary stacking check")
normal.setGeometry(80, 80, 480, 420)
normal.show()
pet = create_pet(MANIFEST, 160, history_db=":memory:")
pet.move(160, 160)
pet.show()
QTest.qWait(400)


def prop(window, name):
    return subprocess.check_output(["xprop", "-id", hex(int(window.winId())), name], text=True)


try:
    assert "_NET_WM_STATE_ABOVE" in prop(pet, "_NET_WM_STATE")
    assert "input focus: False" in prop(pet, "WM_HINTS")
    normal.activateWindow()
    QTest.qWait(100)
    wait_future(pet.notification_controller.notify('任务完成啦！\n测试已经通过，可以回来看看结果了。', title='Agent', duration_seconds=120))
    QTest.qWait(200)
    assert pet.bubble.isVisible()
    assert "_NET_WM_STATE_ABOVE" in prop(pet.bubble, "_NET_WM_STATE")
    assert "input focus: False" in prop(pet.bubble, "WM_HINTS")
    active = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], text=True)
    assert hex(int(normal.winId())) in active, active
    for _ in range(3):
        normal.raise_()
        normal.activateWindow()
        QTest.qWait(300)
        stacking = subprocess.check_output(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"], text=True)
        ids = stacking.partition("#")[2].strip().split(", ")
        assert ids.index(hex(int(pet.winId()))) > ids.index(hex(int(normal.winId())))
        assert ids.index(hex(int(pet.bubble.winId()))) > ids.index(hex(int(normal.winId())))
        active = subprocess.check_output(["xprop", "-root", "_NET_ACTIVE_WINDOW"], text=True)
        assert hex(int(normal.winId())) in active, active
    print("PASS: pet and speech bubble remain above a repeatedly activated ordinary window; notifications preserve keyboard focus")
    dismissed = []

    def dismiss_menu():
        menu = app.activePopupWidget()
        if menu is not None:
            QTest.keyClick(menu, Qt.Key.Key_Escape)
            dismissed.append(True)

    for _ in range(3):
        QTimer.singleShot(200, dismiss_menu)
        QTimer.singleShot(1500, lambda: app.activePopupWidget() and app.activePopupWidget().close())
        pet.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(10, 10), pet.mapToGlobal(QPoint(10, 10))))
        QTest.qWait(100)
        assert pet.isVisible() and pet.animation.timer.isActive()
        assert app.activePopupWidget() is None
        assert "_NET_WM_STATE_ABOVE" in prop(pet, "_NET_WM_STATE")
    assert len(dismissed) == 3
    QTest.keyClick(pet, Qt.Key.Key_Escape)
    assert pet.isVisible()
    print("PASS: original menu opens/closes repeatedly; Esc dismisses only menu; pet stays visible and animated")
    pet.show_history()
    wait_idle(pet)
    QTest.qWait(200)
    assert pet.history_dialog.isVisible()
    assert pet.history_dialog.messages.count() == 1
    assert "input focus: True" in prop(pet.history_dialog, "WM_HINTS")
    QTest.keyClick(pet.history_dialog, Qt.Key.Key_Escape)
    QTest.qWait(100)
    assert not pet.history_dialog.isVisible()
    assert pet.isVisible() and pet.animation.timer.isActive()
    assert "input focus: False" in prop(pet, "WM_HINTS")
    print("PASS: explicitly opened history supports keyboard focus; Esc closes history and preserves the animated pet")
finally:
    pet.shutdown()
    normal.close()
