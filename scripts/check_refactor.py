"""Check concurrency, GUI responsiveness, shutdown, asset validation and cache ownership."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QCoreApplication, Qt, QTimer
from PyQt6.QtNetwork import QLocalServer
from PyQt6.QtWidgets import QApplication, QMessageBox

from check_support import wait_future, wait_idle
from contracts import MAX_QUEUE
from history_service import HistoryService
from notification_controller import NotificationController
from pet import MANIFEST, create_pet
from pet_assets import AssetLoadError, Pet
from pet_ipc import PetIPCServer, send_request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--lock-child")
parser.add_argument("--gate", type=Path)
args = parser.parse_args()


def lock_child():
    app = QCoreApplication([])
    while not args.gate.exists():
        time.sleep(0.005)
    server = PetIPCServer(lambda request: {"owner": os.getpid()}, args.lock_child)
    try:
        server.start()
    except RuntimeError as exc:
        assert "已经运行" in str(exc), str(exc)
        print("LOSER", flush=True)
        return
    print(f"WINNER {os.getpid()}", flush=True)
    QTimer.singleShot(2500, app.quit)
    app.exec()
    server.close()


def check_instance_lock(temporary):
    for attempt in range(3):
        name = "desktop-pet-race-" + uuid.uuid4().hex
        gate = temporary / f"gate-{attempt}"
        command = [sys.executable, str(Path(__file__).resolve()), "--lock-child", name, "--gate", str(gate)]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for _ in range(2)]
        try:
            gate.touch()
            lines = [process.stdout.readline().strip() for process in children]
            assert sum(line.startswith("WINNER ") for line in lines) == 1, lines
            assert lines.count("LOSER") == 1, lines
            owner = int(next(line.split()[1] for line in lines if line.startswith("WINNER ")))
            # The losing instance must not unlink the winner's endpoint.
            assert send_request({"command": "status"}, name)["owner"] == owner
            for process in children:
                output, error = process.communicate(timeout=5)
                assert process.returncode == 0, (output, error)
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    # Cleanup of an endpoint left by a crashed process must still work.
    name = "desktop-pet-stale-" + uuid.uuid4().hex
    command = [sys.executable, "-c", "\n".join([
        "import os, sys", "from PyQt6.QtCore import QCoreApplication",
        "from PyQt6.QtNetwork import QLocalServer", "app=QCoreApplication([])",
        "server=QLocalServer()", "assert server.listen(sys.argv[1])", "os._exit(0)",
    ]), name]
    subprocess.run(command, check=True, timeout=5)
    server = PetIPCServer(lambda request: {}, name)
    try:
        server.start()
        assert server.server.isListening()
    finally:
        server.close()

    # A live legacy instance does not own a QLockFile, but must also be protected.
    name = "desktop-pet-legacy-" + uuid.uuid4().hex
    legacy = QLocalServer()
    assert legacy.listen(name)
    server = PetIPCServer(lambda request: {}, name)
    try:
        try:
            server.start()
            raise AssertionError("Legacy live endpoint must not be replaced")
        except RuntimeError as exc:
            assert "已经运行" in str(exc)
        assert legacy.isListening()
    finally:
        server.close()
        legacy.close()
    print("PASS: simultaneous startup has exactly one owner; stale and legacy endpoints are handled safely")


def check_responsiveness(temporary, app):
    db = temporary / "responsive.sqlite3"
    pet = create_pet(MANIFEST, 160, history_db=db,
                     server_name="desktop-pet-responsive-" + uuid.uuid4().hex)
    pet.show()
    pulses = []
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: pulses.append(time.monotonic()))
    heartbeat.start()
    try:
        callbacks = []
        main_thread = threading.get_ident()
        pet.history.record_added.connect(lambda record: callbacks.append(threading.get_ident()))
        assert pet.history._executor.submit(threading.get_ident).result() != main_thread
        with sqlite3.connect(db) as blocker, ThreadPoolExecutor(max_workers=1) as client:
            blocker.execute("BEGIN IMMEDIATE")
            failed = pet.notification_controller.notify("锁定中的写入")
            status = client.submit(send_request, {"command": "status"}, pet.ipc.name)
            # Reads / status and animation remain responsive while a write waits.
            assert wait_future(status)["running"]
            pet.animation.play_action("waving")
            pet.show_history()
            start_count = len(pulses)
            try:
                wait_future(failed)
                raise AssertionError("Locked write must fail")
            except ValueError as exc:
                assert "无法保存消息历史" in str(exc)
            assert len(pulses) - start_count >= 20
            assert not pet.notification_controller._pending
            assert pet.notification_controller.current is None
            assert not pet.notification_controller.queue
            assert not pet.bubble.isVisible()
        wait_idle(pet)
        assert wait_future(pet.history.count()) == 0
        assert wait_future(pet.notification_controller.notify("解锁后正常接收"))["status"] == "displayed"
        wait_idle(pet)
        assert pet.history_dialog.messages.count() == 1
        pet.bubble.dismiss()
        # All in-flight writes reserve capacity; overflow never reaches storage.
        with sqlite3.connect(db) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            pending = [pet.notification_controller.notify(f"同时写入 {index}")
                       for index in range(MAX_QUEUE + 1)]
            try:
                pet.notification_controller.notify("超出容量")
                raise AssertionError("Pending writes must count toward capacity")
            except ValueError as exc:
                assert "队列已满" in str(exc)
            # Release before the worker timeout so all accepted requests succeed.
            blocker.rollback()
        results = [wait_future(future) for future in pending]
        assert results[0]["status"] == "displayed"
        assert all(result["status"] == "queued" for result in results[1:])
        assert pet.notification_controller.current.id == results[0]["id"]
        assert [item.id for item in pet.notification_controller.queue] == [item["id"] for item in results[1:]]
        assert wait_future(pet.history.count()) == MAX_QUEUE + 2
        # A page query and an arrival may overlap without duplicating the list.
        pet.history_dialog.refresh()
        for _ in range(MAX_QUEUE + 1):
            pet.bubble.dismiss()
        wait_future(pet.notification_controller.notify("刷新期间的新消息"))
        wait_idle(pet)
        records = [pet.history_dialog.messages.item(index).data(Qt.ItemDataRole.UserRole)
                   for index in range(pet.history_dialog.messages.count())]
        assert len({record["notification_id"] for record in records}) == len(records)
        assert len(records) == wait_future(pet.history.count())
        assert callbacks and set(callbacks) == {main_thread}
        # A failed asynchronous query must leave the displayed history usable.
        with patch.object(pet.history._store, "page", side_effect=sqlite3.OperationalError("read failure")):
            with patch.object(QMessageBox, "warning") as warning:
                pet.history_dialog.refresh()
                wait_idle(pet)
                warning.assert_called_once()
        assert pet.history_dialog.messages.count() == len(records)
        assert not pet.history_dialog.busy
    finally:
        heartbeat.stop()
        pet.close()
    print("PASS: DB lock leaves Qt heartbeat, animation commands and IPC status responsive; reservations release on failure and preserve FIFO")

    # Replays reserve capacity in arrival order, while generating fresh silent IDs.
    history = HistoryService(temporary / "replay.sqlite3")
    controller = NotificationController(history)
    try:
        first = wait_future(controller.notify("原始消息", sound=True))
        controller.dismiss()
        replay = controller.replay(first["id"])
        following = controller.notify("重放之后")
        replay_result, following_result = wait_future(replay), wait_future(following)
        assert controller.current.id == replay_result["id"] != first["id"]
        assert controller.current.sound is False
        assert controller.queue[0].id == following_result["id"]
        assert wait_future(history.count()) == 2
        missing = controller.replay("missing")
        try:
            wait_future(missing)
            raise AssertionError("Missing replay must fail")
        except ValueError:
            pass
        assert not controller._pending
    finally:
        controller.close()
        history.close()
    print("PASS: async replay preserves arrival order, releases failed reservations and avoids duplicate history")


def check_pending_shutdown(temporary, app):
    db = temporary / "pending-shutdown.sqlite3"
    pet = create_pet(MANIFEST, 160, history_db=db)
    pet.show()
    wait_future(pet.notification_controller.notify("已确认消息必须保留"))
    pet.show_history()
    wait_idle(pet)
    started = threading.Event()
    original_add = pet.history._store.add

    def blocked_add(notification):
        started.set()
        return original_add(notification)

    try:
        with sqlite3.connect(db) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            with patch.object(pet.history._store, "add", side_effect=blocked_add):
                pending = [pet.notification_controller.notify(f"退出前待写入 {index}")
                           for index in range(MAX_QUEUE)]
                assert started.wait(2)
                began = time.monotonic()
                pet.close()
                assert time.monotonic() - began < 2.5
                assert all(future.done() and future.exception() is not None for future in pending)
        app.processEvents()
        assert not pet.bubble.isVisible() and not pet.history_dialog.isVisible()
        assert pet.history.closed and not pet.animation.timer.isActive()
        with sqlite3.connect(db) as reader:
            assert reader.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
            reader.execute("BEGIN IMMEDIATE")
            reader.rollback()
    finally:
        pet.close()
    print("PASS: shutdown cancels queued writes, settles futures, closes DB on its owner thread and preserves acknowledged history")


def check_assets(temporary):
    base = json.loads(MANIFEST.read_text())
    base["sprite2d"]["spritesheetPath"] = str(MANIFEST.parent / "spritesheet.webp")
    invalid = []
    for label, edit in (
        ("empty durations", lambda data: data["sprite2d"]["tracks"]["idle"].update(durations=[])),
        ("zero duration", lambda data: data["sprite2d"]["tracks"]["idle"].update(durations=[0])),
        ("invalid fallback", lambda data: data["sprite2d"]["tracks"]["jumping"].update(fallback="missing")),
        ("crop outside atlas", lambda data: data["sprite2d"]["frames"].__setitem__(0, 9)),
        ("invalid loop", lambda data: data["sprite2d"]["tracks"]["idle"].update(loop="yes")),
        ("wrong frames length", lambda data: data["sprite2d"].update(frames=[6])),
    ):
        data = json.loads(json.dumps(base))
        edit(data)
        invalid.append((label, data))
    for label, data in invalid:
        path = temporary / "invalid.json"
        path.write_text(json.dumps(data))
        try:
            Pet(path)
            raise AssertionError(label)
        except AssetLoadError as exc:
            assert str(path) in str(exc)

    # frames2d validates the idle name and every image, including non-idle tracks.
    first = Pet(MANIFEST)
    folder = temporary / "idle"
    folder.mkdir()
    assert first.pixmap("idle", 0).save(str(folder / "0.png"))
    valid = {"displayName": "测试", "renderer": "frames2d", "frames2d": {
        "phases": {"idle": "idle"}, "tracks": {"idle": {"frames": ["0.png"]}}}}
    path = temporary / "frames.json"
    path.write_text(json.dumps(valid))
    assert Pet(path).tracks["idle"].durations == [200]
    for edit in (lambda data: data["frames2d"]["phases"].update(idle="missing"),
                 lambda data: data["frames2d"]["tracks"].update(broken={"frames": ["missing.png"]}),
                 lambda data: data["frames2d"]["tracks"]["idle"].update(frameMs=[False])):
        data = json.loads(json.dumps(valid))
        edit(data)
        path.write_text(json.dumps(data))
        try:
            Pet(path)
            raise AssertionError("Malformed frames2d must fail at load time")
        except AssetLoadError:
            pass
    second = Pet(MANIFEST)
    first.pixmap("idle", 0)
    assert first._cache and not second._cache
    second.pixmap("waving", 0)
    second._cache.clear()
    assert first._cache
    print("PASS: invalid tracks, durations, frame bounds and missing images fail during loading; caches belong to each instance")


if args.lock_child:
    lock_child()
else:
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="desktop-pet-refactor-") as directory:
        temporary = Path(directory)
        check_instance_lock(temporary)
        check_responsiveness(temporary, app)
        check_pending_shutdown(temporary, app)
        check_assets(temporary)
