"""Verify right-click Exit ends a real Qt event loop and its process, with isolated state."""
import argparse
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--desktop", action="store_true", help="在真实桌面短暂打开测试窗口")
parser.add_argument("--child", choices=("plain", "bubble", "history"))
parser.add_argument("--db", type=Path)
parser.add_argument("--socket")
args = parser.parse_args()


def child():
    if not args.desktop:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtCore import QPoint, Qt, QTimer
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtNetwork import QLocalSocket
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from pet import start_notifications, create_pet, MANIFEST, configure_platform
    from check_support import wait_future, wait_idle

    configure_platform()
    app = QApplication([])
    pet = create_pet(MANIFEST, 160, history_db=args.db)
    start_notifications(pet, args.socket)
    socket_path = pet.ipc.server.fullServerName()
    pet.show()
    if args.child != "plain":
        wait_future(pet.notification_controller.notify('退出检查：历史记录应保存。', title='退出测试', duration_seconds=120))
    if args.child == "history":
        pet.show_history()
        wait_idle(pet)
    # An incomplete IPC request must be disconnected as part of closing the pet.
    incomplete = QLocalSocket()
    incomplete.connectToServer(args.socket)
    assert incomplete.waitForConnected(1000)
    incomplete.write(b'{"command":')
    incomplete.flush()
    app.processEvents()
    callbacks = []

    def click_exit():
        menu = app.activePopupWidget()
        assert menu is not None
        action = next(action for action in menu.actions() if action.text() == "退出")
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
        callbacks.append("exit")

    def open_menu():
        QTimer.singleShot(50, click_exit)
        point = QPoint(10, 10)
        pet.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, pet.mapToGlobal(point)))

    QTimer.singleShot(50, open_menu)
    code = app.exec()
    assert code == 0 and callbacks == ["exit"]
    assert not pet.isVisible() and not pet.bubble.isVisible()
    assert not pet.animation.timer.isActive()
    assert not pet.ipc.server.isListening()
    if pet.history_dialog:
        assert not pet.history_dialog.isVisible()
    try:
        wait_future(pet.history.count())
        raise AssertionError("History connection must be closed")
    except sqlite3.ProgrammingError:
        pass
    if os.name != "nt":
        assert not Path(socket_path).exists(), socket_path
    print(f"PASS child {args.child}: menu Exit returned from app.exec and closed resources", flush=True)


def parent():
    with TemporaryDirectory(prefix="desktop-pet-shutdown-") as temporary:
        for mode in ("plain", "bubble", "history"):
            db = Path(temporary) / f"{mode}.sqlite3"
            command = [sys.executable, str(Path(__file__).resolve()), "--child", mode,
                       "--db", str(db), "--socket", "desktop-pet-shutdown-" + uuid.uuid4().hex]
            if args.desktop:
                command.append("--desktop")
            # communicate() waits for and reaps the child, and a deadline catches hidden event loops.
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
                try:
                    stdout, stderr = process.communicate(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise AssertionError(f"{mode}: pet process remained running after Exit\n{stdout}\n{stderr}")
                assert process.returncode == 0, f"{mode}: {stdout}\n{stderr}"
                print(stdout.strip())
            with sqlite3.connect(db) as history:
                expected = 0 if mode == "plain" else 1
                assert history.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == expected
                history.execute("BEGIN IMMEDIATE")
                history.rollback()
        print("PASS: all pet processes exited normally and were reaped; IPC endpoints and database locks were released")


if args.child:
    child()
else:
    parent()
