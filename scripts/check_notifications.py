"""Check the real MCP stdio -> local IPC -> Qt bubble path without opening a desktop window."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from pet import start_notifications, create_pet, MANIFEST
from check_support import wait_future
from contracts import MAX_QUEUE
from pet_ipc import MAX_PACKET, send_request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--preview", type=Path, help="保存气泡与桌宠的界面预览 PNG")
args = parser.parse_args()
app = QApplication([])
pet = create_pet(MANIFEST, 240, history_db=":memory:")
pet.move(400, 360)
pet.show()
server_name = "desktop-pet-check-" + uuid.uuid4().hex
start_notifications(pet, server_name)
pool = ThreadPoolExecutor(max_workers=1)


def wait(future):
    deadline = time.monotonic() + 30
    while not future.done():
        if time.monotonic() > deadline:
            raise TimeoutError("Notification check timed out")
        QTest.qWait(10)
    return future.result()


async def check_mcp():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")],
                                   env={**os.environ, "DESKTOP_PET_SOCKET": server_name})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert {t.name for t in tools} == {
                "desktop_pet_bell", "desktop_pet_status", "desktop_pet_list_actions", "desktop_pet_play_action",
            }
            bell_tool = next(t for t in tools if t.name == "desktop_pet_bell")
            assert bell_tool.inputSchema["required"] == ["message"]
            status = await session.call_tool("desktop_pet_status", {})
            assert not status.isError and status.structuredContent["running"]
            first = await session.call_tool("desktop_pet_bell", {
                "message": "任务完成啦！\n测试已经通过，可以回来看看结果了。 ✨\n<b>这是纯文本，不会解析 HTML。</b>",
                "title": "测试 Agent", "duration_seconds": 3,
            })
            assert not first.isError, first
            assert first.structuredContent["status"] == "displayed"
            second = await session.call_tool("desktop_pet_bell", {
                "message": "第二条通知：中文长消息也能滚动阅读。\n" * 50,
                "duration_seconds": 120,
            })
            assert not second.isError and second.structuredContent["status"] == "queued"
            assert second.structuredContent["id"] != first.structuredContent["id"]
            for invalid in ({"message": " "}, {"message": "x" * 2001},
                            {"message": "ok", "duration_seconds": 1},
                            {"message": "ok", "title": "bad\ntitle"}):
                result = await session.call_tool("desktop_pet_bell", invalid)
                assert result.isError, invalid
            return first.structuredContent, second.structuredContent


async def check_actions():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")],
                                   env={**os.environ, "DESKTOP_PET_SOCKET": server_name})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool = next(t for t in (await session.list_tools()).tools if t.name == "desktop_pet_play_action")
            assert tool.inputSchema["required"] == ["action"]
            assert tool.inputSchema["properties"]["once"]["default"] is True
            catalog = await session.call_tool("desktop_pet_list_actions", {})
            assert not catalog.isError
            data = catalog.structuredContent
            assert data["paused"] is True and data["current_action"] == "idle"
            actions = {a["action"]: a for a in data["actions"]}
            assert len(actions) == 9 and actions["waving"]["label"] == "招手"
            assert actions["waving"]["loop"] is True
            assert actions["jumping"]["loop"] is False
            assert actions["waving"]["duration_seconds"] == 1.8
            for invalid in ({"action": "missing"}, {"action": " "}, {"action": "x" * 65}):
                result = await session.call_tool("desktop_pet_play_action", invalid)
                assert result.isError, invalid
            unchanged = (await session.call_tool("desktop_pet_status", {})).structuredContent
            assert unchanged["current_action"] == "idle" and unchanged["paused"] is True

            # Real Qt timer playback, including resuming a manually paused pet.
            waving = await session.call_tool("desktop_pet_play_action", {"action": "waving"})
            assert not waving.isError and waving.structuredContent["status"] == "playing"
            assert waving.structuredContent["once"] is True and not waving.structuredContent["looping"]
            status = (await session.call_tool("desktop_pet_status", {})).structuredContent
            assert status["current_action"] == "waving" and not status["paused"]
            await asyncio.sleep(actions["waving"]["duration_seconds"] + 0.4)
            assert (await session.call_tool("desktop_pet_status", {})).structuredContent["current_action"] == "idle"

            running = await session.call_tool("desktop_pet_play_action", {"action": "running", "once": False})
            assert not running.isError and running.structuredContent["looping"] is True
            await asyncio.sleep(actions["running"]["duration_seconds"] + 0.4)
            assert (await session.call_tool("desktop_pet_status", {})).structuredContent["current_action"] == "running"
            jumping = await session.call_tool("desktop_pet_play_action", {"action": "jumping", "once": False})
            assert not jumping.isError and not jumping.structuredContent["looping"]
            await asyncio.sleep(actions["jumping"]["duration_seconds"] + 0.4)
            assert (await session.call_tool("desktop_pet_status", {})).structuredContent["current_action"] == "idle"
            idle = await session.call_tool("desktop_pet_play_action", {"action": "idle", "once": False})
            assert not idle.isError and idle.structuredContent["action"] == "idle"


def raw_request(payload):
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    assert socket.waitForConnected(1000)
    socket.write(payload)
    assert socket.waitForBytesWritten(1000)
    assert socket.waitForReadyRead(1000)
    data = bytes(socket.readAll())
    socket.abort()
    return data


try:
    first, second = wait(pool.submit(asyncio.run, check_mcp()))
    assert pet.notification_controller.current.id == first["id"]
    assert len(pet.notification_controller.queue) == 1
    assert pet.bubble.isVisible()
    assert "<b>这是纯文本" in pet.bubble.body.toPlainText()
    assert pet.bubble.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert pet.bubble.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert pet.bubble.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert pet.bubble.body.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert not pet.bubble.body.openExternalLinks()
    assert pet.bubble.queue_badge.isVisible() and pet.bubble.queue_badge.text() == "1"
    assert wait_future(pet.history.count()) == 2
    assert {row["notification_id"] for row in wait_future(pet.history.recent())} == {first["id"], second["id"]}
    print("PASS: real MCP initialization, tool schemas, Chinese delivery, FIFO queue and validation errors")

    pet.animation.toggle_pause(True)
    original_position = pet.pos()
    wait(pool.submit(asyncio.run, check_actions()))
    assert pet.animation.timer.isActive() and not pet.animation.paused
    assert pet.pos() == original_position
    assert pet.notification_controller.current.id == first["id"] and len(pet.notification_controller.queue) == 1
    print("PASS: MCP action catalog, invalid-action safety, resume, one-shot return, looping and track fallback")

    if args.preview:
        original_text = pet.bubble.body.toPlainText()
        pet.bubble.body.setPlainText("任务完成啦！\n测试已经通过，可以回来看看结果了。 ✨")
        rect = pet.geometry().united(pet.bubble.geometry()).adjusted(-24, -24, 24, 24)
        preview = QImage(rect.size(), QImage.Format.Format_ARGB32)
        preview.fill(QColor("#e9e8f4"))
        painter = QPainter(preview)
        pet.render(painter, pet.pos() - rect.topLeft())
        pet.bubble.render(painter, pet.bubble.pos() - rect.topLeft())
        painter.end()
        assert preview.save(str(args.preview))
        pet.bubble.body.setPlainText(original_text)

    # Bubble follows moves and stays within screen bounds, flipping its tail near the top.
    for point in (QPoint(5, 5), QPoint(560, 520), QPoint(400, 360)):
        pet.move(point)
        app.processEvents()
        assert app.primaryScreen().availableGeometry().contains(pet.bubble.geometry())
        if point == QPoint(5, 5):
            assert not pet.bubble.tail_on_bottom
    pet.resize_pet(320)
    app.processEvents()
    assert app.primaryScreen().availableGeometry().contains(pet.bubble.geometry())

    bubble = pet.bubble
    third = wait_future(pet.notification_controller.notify('最后一条通知', duration_seconds=3))
    assert third["status"] == "queued" and third["queued"] == 2
    assert bubble.queue_badge.isVisible() and bubble.queue_badge.text() == "2"
    assert pet.notification_controller.current.id == first["id"]
    original_text = bubble.body.toPlainText()
    app.sendEvent(bubble, QEvent(QEvent.Type.Enter))
    app.sendEvent(bubble, QEvent(QEvent.Type.Leave))
    QTest.qWait(3200)
    assert bubble.isVisible() and bubble.body.toPlainText() == original_text
    assert pet.notification_controller.current.id == first["id"] and len(pet.notification_controller.queue) == 2
    assert bubble.queue_badge.text() == "2"
    QTest.mouseClick(bubble.close_button, Qt.MouseButton.LeftButton)
    assert pet.notification_controller.current.id == second["id"]
    assert len(pet.notification_controller.queue) == 1
    assert bubble.isVisible() and bubble.queue_badge.isVisible() and bubble.queue_badge.text() == "1"
    assert bubble.body.verticalScrollBar().maximum() > 0
    menu = pet.create_context_menu()
    next(action for action in menu.actions() if action.text() == "收起通知 / 下一条").trigger()
    menu.deleteLater()
    assert pet.notification_controller.current.id == third["id"] and not pet.notification_controller.queue
    assert bubble.body.toPlainText() == "最后一条通知" and bubble.queue_badge.isHidden()
    app.sendEvent(bubble, QEvent(QEvent.Type.Enter))
    app.sendEvent(bubble, QEvent(QEvent.Type.Leave))
    QTest.qWait(3200)
    assert bubble.isVisible() and pet.notification_controller.current.id == third["id"]
    bubble.close()
    assert not bubble.isVisible() and pet.notification_controller.current is None
    bubble.dismiss()
    assert pet.notification_controller.current is None
    print("PASS: persistent bubble beyond legacy duration, hover/leave, red queue badge, manual FIFO close, screen edges and long-text scrolling")

    # Exercise the IPC boundary independently of the MCP argument schema.
    for payload in (b"[]\n", b"not-json\n", b'{"command":"unknown"}\n', b"x" * (MAX_PACKET + 1),
                    b'{"command":"play_action","action":123}\n',
                    b'{"command":"play_action","action":"running","once":"false"}\n'):
        assert b'"ok": false' in wait(pool.submit(raw_request, payload))
    status = wait(pool.submit(send_request, {"command": "status"}, server_name))
    assert status["running"] and status["current_id"] is None
    wait_future(pet.notification_controller.notify('当前通知', duration_seconds=120))
    for i in range(MAX_QUEUE):
        wait_future(pet.notification_controller.notify(f'排队 {i}', duration_seconds=120))
    try:
        wait(pool.submit(send_request, {"command": "bell", "message": "溢出"}, server_name))
        raise AssertionError("Full queue must reject a notification")
    except ValueError as exc:
        assert "队列已满" in str(exc)
    assert len(pet.notification_controller.queue) == MAX_QUEUE
    assert pet.bubble.queue_badge.isVisible() and pet.bubble.queue_badge.text() == str(MAX_QUEUE)
    assert wait_future(pet.history.count()) == 3 + 1 + MAX_QUEUE
    duplicate = create_pet(MANIFEST, 160, history_db=":memory:")
    try:
        start_notifications(duplicate, server_name)
        raise AssertionError("Live endpoint must never be replaced")
    except RuntimeError as exc:
        assert "已经运行" in str(exc)
    finally:
        duplicate.close()
    assert wait(pool.submit(send_request, {"command": "status"}, server_name))["running"]
    pet.close()
    try:
        wait(pool.submit(send_request, {"command": "status"}, server_name))
        raise AssertionError("Closed pet must not accept requests")
    except ConnectionError:
        pass
    print("PASS: malformed/oversized IPC, full queue, duplicate-instance guard, shutdown and offline errors")
finally:
    pet.close()
    pool.shutdown(wait=True)
