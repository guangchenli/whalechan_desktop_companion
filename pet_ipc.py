"""Small local-only bridge between the stdio MCP server and the Qt pet."""
import getpass
import hashlib
import json
import logging
import os
from pathlib import Path
import time
import tempfile

from concurrent.futures import Future

from PyQt6 import sip
from PyQt6.QtCore import QObject, QLockFile, QTimer
from PyQt6.QtNetwork import QAbstractSocket, QLocalServer, QLocalSocket

MAX_PACKET = 16384


def discovery_directory():
    """Shared with standalone clients; independent of the checkout's location."""
    user = hashlib.sha256(getpass.getuser().encode()).hexdigest()[:20]
    return Path(tempfile.gettempdir()) / f"desktop-pet-discovery-{user}"


def default_server_name():
    identity = f"{Path(__file__).resolve().parent}:{getpass.getuser()}"
    suffix = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return os.environ.get("DESKTOP_PET_SOCKET", f"desktop-pet-{suffix}")


def send_request(request, server_name=None, timeout_ms=3000):
    """Blocking client; call from a worker thread, never from the GUI thread."""
    packet = json.dumps(request, ensure_ascii=False).encode() + b"\n"
    if len(packet) > MAX_PACKET:
        raise ValueError("通知请求过大")
    socket = QLocalSocket()
    deadline = time.monotonic() + timeout_ms / 1000

    def remaining():
        return max(1, int((deadline - time.monotonic()) * 1000))

    try:
        socket.connectToServer(server_name or default_server_name())
        if not socket.waitForConnected(remaining()):
            raise ConnectionError("桌宠未运行或无法连接，请先启动 pet.py；检查双方的 DESKTOP_PET_SOCKET 设置")
        socket.write(packet)
        while socket.bytesToWrite():
            if not socket.waitForBytesWritten(remaining()):
                raise ConnectionError("发送桌宠通知超时")
        data = bytearray()
        while b"\n" not in data:
            data.extend(bytes(socket.readAll()))
            if len(data) > MAX_PACKET:
                raise ConnectionError("桌宠响应过大")
            if b"\n" in data:
                break
            if time.monotonic() >= deadline or not socket.waitForReadyRead(remaining()):
                # A final reply can arrive together with the disconnect signal.
                data.extend(bytes(socket.readAll()))
                if b"\n" not in data:
                    raise ConnectionError("桌宠未及时确认通知")
        response = json.loads(data.split(b"\n", 1)[0])
        if not response.get("ok"):
            raise ValueError(response.get("error", "桌宠拒绝通知"))
        return response["result"]
    finally:
        socket.abort()


class PetIPCServer(QObject):
    def __init__(self, handler, server_name=None, parent=None):
        super().__init__(parent)
        self.handler = handler
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.accept_connections)
        self.name = server_name or default_server_name()
        # QLocalServer's default endpoints and these locks share the temporary
        # directory. This also works when a client cannot write XDG_RUNTIME_DIR.
        lock_root = Path(tempfile.gettempdir())
        suffix = hashlib.sha256(f"{getpass.getuser()}:{self.name}".encode()).hexdigest()
        self.lock = QLockFile(str(lock_root / f"desktop-pet-{suffix}.lock"))
        self.lock.setStaleLockTime(0)
        self._connections = set()
        self._discovery_file = None
        self.closed = False

    def _publish_endpoint(self):
        """Publish only after listening; one atomic record per independently locked endpoint."""
        temporary = None
        try:
            directory = discovery_directory()
            directory.mkdir(mode=0o700, exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise OSError("桌宠发现目录必须是普通目录")
            if os.name == "posix":
                if directory.stat().st_uid != os.getuid():
                    raise OSError("桌宠发现目录属于其他用户")
                directory.chmod(0o700)
            suffix = hashlib.sha256(self.name.encode()).hexdigest()[:20]
            target = directory / f"{suffix}.json"
            record = dict(version=1, endpoint=self.server.fullServerName(),
                          projectDir=str(Path(__file__).resolve().parent),
                          pid=os.getpid(), startedAt=time.time_ns() // 1_000_000)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf8", dir=directory,
                                             prefix=".endpoint-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(record, stream, ensure_ascii=False)
            os.replace(temporary, target)
            self._discovery_file = target
        except OSError as exc:
            # Explicit socket clients must remain usable if discovery cannot be published.
            logging.getLogger(__name__).warning("无法发布桌宠 IPC 发现记录：%s", exc)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def start(self):
        if not self.lock.tryLock(0):
            if self.lock.error() == QLockFile.LockError.LockFailedError:
                raise RuntimeError("此项目的桌宠已经运行；请使用现有窗口，或设置不同的 DESKTOP_PET_SOCKET")
            raise RuntimeError("无法获取桌宠实例锁：请检查运行目录权限")
        try:
            # Hold the instance lock throughout probing, stale cleanup and listen.
            # Also detect a live pre-refactor instance, which does not use this lock.
            probe = QLocalSocket()
            probe.connectToServer(self.name)
            connected = probe.waitForConnected(200)
            error = probe.error()
            probe.abort()
            if connected:
                raise RuntimeError("此项目的桌宠已经运行；请使用现有窗口，或设置不同的 DESKTOP_PET_SOCKET")
            absent_errors = (QLocalSocket.LocalSocketError.ConnectionRefusedError,
                             QLocalSocket.LocalSocketError.ServerNotFoundError)
            if error not in absent_errors:
                raise RuntimeError("无法确认 IPC 端点是否已失效；请检查访问权限或连接状态")
            if not self.server.listen(self.name):
                if (self.server.serverError() == QAbstractSocket.SocketError.AddressInUseError
                        and error == QLocalSocket.LocalSocketError.ConnectionRefusedError):
                    QLocalServer.removeServer(self.name)
                    if not self.server.listen(self.name):
                        raise RuntimeError(f"无法启动桌宠通知服务：{self.server.errorString()}")
                else:
                    raise RuntimeError(f"无法启动桌宠通知服务：{self.server.errorString()}")
            self._publish_endpoint()
        except Exception:
            self.server.close()
            self.lock.unlock()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.server.close()
        for socket in tuple(self._connections):
            if not sip.isdeleted(socket):
                socket.abort()
        if self._discovery_file is not None:
            try:
                self._discovery_file.unlink(missing_ok=True)
            except OSError as exc:
                logging.getLogger(__name__).warning("无法清理桌宠 IPC 发现记录：%s", exc)
        self.lock.unlock()

    def accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._connections.add(socket)
            buffer = bytearray()
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(5000)
            socket.disconnected.connect(lambda s=socket: self._connections.discard(s))
            socket.disconnected.connect(socket.deleteLater)
            socket.readyRead.connect(lambda s=socket, b=buffer, t=timer: self.read_request(s, b, t))
            if socket.bytesAvailable():
                self.read_request(socket, buffer, timer)

    def _reply(self, socket, response):
        if (self.closed or sip.isdeleted(socket)
                or socket.state() != QLocalSocket.LocalSocketState.ConnectedState):
            return
        socket.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")
        socket.disconnectFromServer()

    def _reply_future(self, socket, future):
        try:
            response = dict(ok=True, result=future.result())
        except Exception as exc:
            response = dict(ok=False, error=str(exc))
        self._reply(socket, response)

    def read_request(self, socket, buffer, timer):
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) <= MAX_PACKET and b"\n" not in buffer:
            return
        timer.stop()
        socket.readyRead.disconnect()
        try:
            if len(buffer) > MAX_PACKET:
                raise ValueError("通知请求过大")
            request = json.loads(buffer.split(b"\n", 1)[0])
            if not isinstance(request, dict):
                raise ValueError("请求必须是 JSON 对象")
            result = self.handler(request)
            if isinstance(result, Future):
                # Handler futures complete on the GUI thread; socket use stays there.
                result.add_done_callback(lambda f, s=socket: self._reply_future(s, f))
            else:
                self._reply(socket, dict(ok=True, result=result))
        except (ValueError, TypeError, UnicodeError, RuntimeError) as exc:
            self._reply(socket, dict(ok=False, error=str(exc)))
