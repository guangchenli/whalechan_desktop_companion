"""Verify endpoint publication, ownership and cleanup using isolated real Qt sockets."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import getpass
import hashlib
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtTest import QTest

from pet_ipc import PetIPCServer, discovery_directory, send_request


def check_request(server):
    with ThreadPoolExecutor(max_workers=1) as client:
        future = client.submit(send_request, {"command": "status"}, server.server.fullServerName())
        deadline = time.monotonic() + 3
        while not future.done() and time.monotonic() < deadline:
            QTest.qWait(5)
        assert future.result(timeout=1) == {"running": True}


app = QCoreApplication([])
with tempfile.TemporaryDirectory(prefix="desktop-pet-discovery-check-") as temporary:
    user = hashlib.sha256(getpass.getuser().encode()).hexdigest()[:20]
    registry = Path(temporary) / f"desktop-pet-discovery-{user}"
    servers = []
    try:
        with patch("pet_ipc.discovery_directory", return_value=registry):
            received = []

            def handle(request):
                received.append(request)
                return {"running": True} if request["command"] == "status" else {"status": "queued"}

            first = PetIPCServer(handle, "desktop-pet-discovery-" + uuid.uuid4().hex)
            servers.append(first)
            first.start()
            record = first._discovery_file
            data = json.loads(record.read_text())
            assert data["version"] == 1 and data["pid"] == os.getpid()
            assert data["projectDir"] == str(ROOT)
            assert data["endpoint"] == first.server.fullServerName()
            assert isinstance(data["startedAt"], int)
            assert len(list(registry.glob("*.json"))) == 1
            assert not list(registry.glob(".endpoint-*"))
            if os.name == "posix":
                assert stat.S_IMODE(registry.stat().st_mode) == 0o700
                assert stat.S_IMODE(record.stat().st_mode) == 0o600
            check_request(first)
            print("PASS: published record contains the real Qt endpoint and is private and atomic")

            command = ["node", str(ROOT / "scripts/check_pi_bell.mjs"), "--real-discovery",
                       temporary, data["endpoint"]]
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
                deadline = time.monotonic() + 10
                while child.poll() is None and time.monotonic() < deadline:
                    QTest.qWait(5)
                if child.poll() is None:
                    child.kill()
                output, error = child.communicate(timeout=2)
                assert child.returncode == 0, (output, error)
                assert any(request["command"] == "bell" and request["message"] == "✅ Pi 已完成，等待输入"
                           for request in received), received
                print(output.strip())

            second = PetIPCServer(lambda _request: {"running": True}, "desktop-pet-discovery-" + uuid.uuid4().hex)
            servers.append(second)
            second.start()
            second_record = second._discovery_file
            assert len(list(registry.glob("*.json"))) == 2
            duplicate = PetIPCServer(lambda _request: {}, second.name)
            servers.append(duplicate)
            try:
                duplicate.start()
                raise AssertionError("Duplicate server must not start")
            except RuntimeError as error:
                assert "已经运行" in str(error)
            duplicate.close()
            assert second_record.exists()
            first.close()
            assert not record.exists() and second_record.exists()
            check_request(second)
            print("PASS: instances coexist; failed startup and closing another instance preserve the owner record")

            # A restarted owner replaces the record left by a previous crash at this endpoint.
            record.write_text('{"version":1,"endpoint":"stale"}')
            restarted = PetIPCServer(lambda _request: {"running": True}, first.name)
            servers.append(restarted)
            restarted.start()
            assert restarted._discovery_file == record
            assert json.loads(record.read_text())["endpoint"] == restarted.server.fullServerName()
            restarted.close()
            second.close()
            assert not list(registry.glob("*.json"))
            print("PASS: restart replaces stale metadata and shutdown removes only its own record")

        unavailable = PetIPCServer(lambda _request: {"running": True}, "desktop-pet-discovery-" + uuid.uuid4().hex)
        servers.append(unavailable)
        with patch("pet_ipc.discovery_directory", side_effect=OSError("unavailable")), patch("pet_ipc.logging.getLogger") as logger:
            unavailable.start()
            logger.return_value.warning.assert_called_once()
        assert unavailable.server.isListening() and unavailable._discovery_file is None
        check_request(unavailable)
        unavailable.close()
        print("PASS: discovery write failure leaves explicit IPC clients working")
    finally:
        for server in servers:
            server.close()

assert discovery_directory().parent == Path(tempfile.gettempdir())
print("IPC discovery checks passed.")
