"""Verify startup frame order, the timed greeting and animated resource shutdown."""
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from check_support import wait_future
from pet import DEFAULT_SIZE, MANIFEST, STARTUP_BUBBLE_MS, create_pet


def wait_until(condition, timeout=2):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "Lifecycle check timed out"
        QTest.qWait(10)


def accelerate(window):
    window.pet.tracks["goodbye"].durations = [20] * 8
    window.pet.tracks["waving"].durations = [20] * 4


app = QApplication([])
app.setQuitOnLastWindowClosed(False)
window = create_pet(MANIFEST, history_db=":memory:")
window.show()
accelerate(window)
try:
    assert DEFAULT_SIZE == 240 and window.display_size == 240
    assert max(window.width(), window.height()) == 240
    assert STARTUP_BUBBLE_MS == 5000 and "goodbye" not in window.animation.idle_group
    startup = []
    exiting = []

    def record():
        player = window.animation
        if player.mode == "startup":
            startup.append((player.track_name, player.frame))
        elif player.mode == "shutdown":
            exiting.append((player.track_name, player.frame))

    window.animation.frame_changed.connect(record)
    window.start_startup()
    assert startup == [("goodbye", 7)] and not window.lifecycle_bubble.isVisible()
    first = wait_future(window.notification_controller.notify("启动期间收到的消息"))
    second = wait_future(window.notification_controller.notify("启动期间排队的消息"))
    assert second["status"] == "queued" and not window.bubble.isVisible()
    try:
        window.animation.play_action("waving")
        raise AssertionError("Manual actions must not replace startup")
    except ValueError:
        pass
    window.animation.toggle_pause(True)
    assert not window.animation.paused
    wait_until(lambda: window.animation.track_name == "waving")
    greeting_started = time.monotonic()
    assert window.lifecycle_bubble.isVisible()
    assert window.lifecycle_bubble.body.toPlainText() == "解码中～返回显空间"
    assert window.lifecycle_timer.isActive() and window.lifecycle_timer.remainingTime() > 4800
    wait_until(lambda: window._phase == "running")
    expected = [("goodbye", i) for i in [7, 6, 5, 4, 3, 0]] + [("waving", i) for i in range(4)]
    assert startup == expected, startup
    assert window.animation.track_name == "notification" and window.lifecycle_bubble.isVisible()
    assert wait_future(window.history.count()) == 2  # Greetings are not durable notifications.
    QTest.qWait(1000)
    assert window.lifecycle_bubble.isVisible()
    wait_until(lambda: not window.lifecycle_bubble.isVisible(), timeout=5)
    assert 4.7 < time.monotonic() - greeting_started < 5.6
    assert window.bubble.isVisible() and window.bubble.body.toPlainText() == "启动期间收到的消息"
    assert window.notification_controller.current.id == first["id"]
    window.bubble.dismiss()
    assert window.notification_controller.current.id == second["id"]
    assert window.animation.track_name == "notification"
    window.bubble.dismiss()
    assert window.animation.mode == "idle"
    print("PASS: default 240 px; source frames 8,7,6,5,4,1 then one wave; greeting expires after 5 seconds without dismissing queued messages")

    window.animation.toggle_pause(True)
    window.request_exit()
    assert window.isVisible() and not window._closed
    assert window.lifecycle_bubble.body.toPlainText() == "正在返回潜空间"
    assert window.lifecycle_bubble.isVisible() and not window.lifecycle_timer.isActive()
    assert window.animation.mode == "shutdown" and not window.animation.paused
    assert window.notification_controller.closed
    window.request_exit()
    window.close()
    assert exiting == [("goodbye", 0)]  # Repeated close requests do not restart the sequence.
    wait_until(lambda: window._closed)
    assert exiting == [("goodbye", i) for i in range(8)], exiting
    assert not window.isVisible() and not window.lifecycle_bubble.isVisible()
    assert window.history.closed and window.animation.closed and not window.animation.timer.isActive()
    print("PASS: exit plays all eight frames even when paused; repeated close is idempotent and resources close after the final frame")
finally:
    window.shutdown()

for during_startup in (False, True):
    window = create_pet(MANIFEST, history_db=":memory:")
    accelerate(window)
    window.show()
    try:
        if during_startup:
            window.start_startup()
        window.close()
        assert window._phase == "shutdown" and window.lifecycle_bubble.isVisible()
        wait_until(lambda: window._closed)
        QTest.qWait(100)
        assert not window.lifecycle_timer.isActive() and not window.lifecycle_bubble.isVisible()
        assert window.history.closed
    finally:
        window.shutdown()
print("PASS: window close and exit during startup finish cleanly without resurrecting greetings")
