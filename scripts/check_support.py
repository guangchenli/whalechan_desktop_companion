"""Qt-aware waits for asynchronous integration checks; never used by application code."""
import time

from PyQt6.QtTest import QTest

from contracts import HistoryRecord


def wait_future(future, timeout=10):
    deadline = time.monotonic() + timeout
    while not future.done():
        if time.monotonic() >= deadline:
            raise TimeoutError("异步操作未完成")
        QTest.qWait(5)
    value = future.result()
    if isinstance(value, HistoryRecord):
        return value.to_dict()
    if isinstance(value, list) and all(isinstance(record, HistoryRecord) for record in value):
        return [record.to_dict() for record in value]
    return value


def wait_idle(pet, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        # Process deferred menu callbacks before considering the services idle.
        QTest.qWait(5)
        dialog = pet.history_dialog
        if (not pet.history._pending and not pet.notification_controller._pending
                and (dialog is None or not dialog.busy)):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("界面操作未完成")
