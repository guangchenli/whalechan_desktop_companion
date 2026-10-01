"""Check idle preferences, one-cycle actions and unread-message animation priority."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import random
from collections import Counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from check_support import wait_future
from pet import MANIFEST, create_pet
from pet_settings import PetSettings
from idle_weights_dialog import IdleWeightsDialog


def finish_cycle(player):
    for _ in range(len(player.pet.tracks[player.track_name].frames) - player.frame):
        player.advance()


def idle_menu(window):
    menu = window.create_context_menu()
    settings = next(action.menu() for action in menu.actions() if action.text() == "设置")
    assert len(settings.actions()) == 1
    group = settings.actions()[0].menu()
    assert group.title() == "待机组表情"
    return menu, {action.text(): action for action in group.actions() if action.isCheckable()}


app = QApplication([])
with tempfile.TemporaryDirectory(prefix="desktop-pet-animation-") as directory:
    path = Path(directory) / "settings.json"
    window = create_pet(MANIFEST, 240, history_db=":memory:", settings_path=path)
    window.show()
    try:
        player = window.animation
        assert len(window.pet.tracks) == 12 and not any(t.loop for t in window.pet.tracks.values())
        assert set(player.idle_group) == window.pet.tracks.keys() - {"failed", "running", "notification", "goodbye"}
        assert "head-scratch" in player.idle_group and window.pet.labels["head-scratch"] == "扣扣脑袋"
        defaults = list(player.idle_group)
        probabilities = player.idle_probabilities()
        assert math.isclose(probabilities["idle"], 0.9)
        assert all(math.isclose(probabilities[name], 0.1 / 7) for name in defaults if name != "idle")
        with patch("animation.random.choices", side_effect=random.Random(20261002).choices):
            counts = Counter()
            repeated_idle = False
            for _ in range(10000):
                previous = player.track_name
                player.play_idle()
                counts[player.track_name] += 1
                repeated_idle |= previous == player.track_name == "idle"
            assert 0.89 < counts["idle"] / 10000 < 0.91 and repeated_idle
            assert set(counts) == set(defaults)
        player.set_idle_group([name for name in defaults if name != "waving"])
        assert math.isclose(player.idle_probabilities()["idle"], 0.9)
        player.set_idle_group(["waving", "head-scratch"])
        assert player.idle_probabilities() == {"waving": 0.5, "head-scratch": 0.5}
        player.set_idle_group([])
        player.set_idle_group(["idle"])
        assert player.idle_probabilities() == {"idle": 1.0} and player.timer.isActive()
        player.set_idle_group(defaults)
        with patch("animation.random.choices", side_effect=lambda choices, **kwargs: [choices[-1]]):
            for _ in range(20):
                assert player.mode == "idle" and player.track_name in player.idle_group
                finish_cycle(player)
            for name in window.pet.tracks:
                player.play_action(name, once=False)
                finish_cycle(player)
                assert player.mode == "idle" and player.track_name in player.idle_group
        print("PASS: all 12 tracks end after one cycle; idle randomly selects allowed expressions")
        print("PASS: default selection is 90% idle with equal remaining shares, allows repeats and redistributes after group changes")

        custom = {name: 0 for name in defaults} | {"idle": 1, "waving": 3}
        player.set_idle_weights(custom)
        assert player.idle_probabilities()["idle"] == 0.25
        assert player.idle_probabilities()["waving"] == 0.75
        with patch("animation.random.choices", side_effect=random.Random(42).choices):
            selected = set()
            for _ in range(100):
                player.play_idle()
                selected.add(player.track_name)
            assert selected == {"idle", "waving"}
        dialog = IdleWeightsDialog(player, window)
        idle_row = dialog.names.index("idle")
        assert dialog.table.item(idle_row, 2).text() == "25.00%"
        dialog.spins["idle"].setValue(0)
        assert dialog.table.item(dialog.names.index("waving"), 2).text() == "100.00%"
        assert player.idle_weights == custom  # Edits are isolated until accepted.
        dialog.restore_defaults()
        assert dialog.weights == {} and dialog.table.item(idle_row, 2).text() == "90.00%"
        dialog.reject()
        dialog.deleteLater()

        def accept_weights(dialog):
            dialog.weights = dict(custom)
            return QDialog.DialogCode.Accepted

        with patch("pet.IdleWeightsDialog.exec", new=accept_weights):
            window.edit_idle_weights()
        assert PetSettings(path).idle_weights(window.pet) == custom
        saved = path.read_bytes()
        with patch("pet.IdleWeightsDialog.exec", return_value=QDialog.DialogCode.Rejected):
            window.edit_idle_weights()
        assert path.read_bytes() == saved and player.idle_weights == custom
        with patch("pet.IdleWeightsDialog.exec", new=accept_weights), \
                patch.object(window.settings, "save_idle_weights", side_effect=OSError("disk full")), \
                patch("pet.QMessageBox.warning") as warning:
            window.edit_idle_weights()
            assert warning.called
        assert path.read_bytes() == saved
        player.set_idle_weights({name: 0 for name in defaults})
        assert not player.timer.isActive()
        player.toggle_pause(True)
        player.toggle_pause(False)
        assert not player.timer.isActive()
        player.set_idle_weights({})
        window.settings.save_idle_weights(window.pet, {})
        assert player.timer.isActive() and math.isclose(player.idle_probabilities()["idle"], 0.9)
        for invalid in (-1, float("nan"), float("inf"), True, 10 ** 400):
            try:
                player.set_idle_weights({"idle": invalid})
                raise AssertionError("Invalid weight must not change playback")
            except ValueError:
                pass
        assert player.idle_weights == {}
        print("PASS: custom weights, zero exclusion, probability previews, restore defaults, cancel and atomic save failure")

        menu, actions = idle_menu(window)
        assert len(actions) == 12 and actions["扣扣脑袋"].isChecked()
        for action in actions.values():
            if action.isChecked():
                action.trigger()
        assert not player.idle_group and not player.timer.isActive()
        assert player.track_name == window.pet.idle and player.frame == 0
        player.toggle_pause(True)
        player.toggle_pause(False)
        assert not player.timer.isActive()
        actions["扣扣脑袋"].trigger()
        assert player.idle_group == ["head-scratch"] and player.track_name == "head-scratch"
        assert PetSettings(path).idle_group(window.pet) == ["head-scratch"]
        window.settings.save_idle_weights(window.pet, {"head-scratch": 2})
        player.set_idle_weights({"head-scratch": 2})
        before = path.read_bytes()
        with patch.object(window.settings, "save_idle_group", side_effect=OSError("disk full")), \
                patch("pet.QMessageBox.warning") as warning:
            actions["招手"].trigger()
            assert warning.called and not actions["招手"].isChecked()
        assert player.idle_group == ["head-scratch"] and path.read_bytes() == before
        menu.deleteLater()
        print("PASS: settings menu persists selections, supports an empty group and preserves preferences on write failure")

        player.toggle_pause(True)
        first = wait_future(window.notification_controller.notify("未读消息"))
        assert player.track_name == "notification" and not player.paused
        for _ in range(3):
            finish_cycle(player)
            assert player.track_name == "notification" and player.frame == 0
        player.advance()
        player.advance()
        frame = player.frame
        second = wait_future(window.notification_controller.notify("排队消息"))
        assert second["status"] == "queued" and player.frame == frame
        window.bubble.dismiss()
        assert window.notification_controller.current.id == second["id"]
        assert player.track_name == "notification" and player.frame == frame
        finish_cycle(player)
        assert player.track_name == "notification"
        # Explicit interactions may play one cycle, then return to unread attention.
        result = player.play_action("head-scratch", once=False)
        assert result["fallback"] == "notification" and not result["looping"]
        finish_cycle(player)
        assert player.track_name == "notification"
        window.bubble.dismiss()
        assert window.notification_controller.current is None and not window.bubble.isVisible()
        assert player.mode == "idle" and player.track_name == "head-scratch"
        # Use real Qt timers for the persistent reminder, with shorter test timings.
        window.pet.tracks["notification"].durations = [20] * 6
        wait_future(window.notification_controller.notify("计时器检查"))
        QTest.qWait(400)
        assert player.mode == "notification" and player.track_name == "notification" and player.timer.isActive()
        window.shutdown()
        assert player.closed and not player.timer.isActive()
        print("PASS: unread bubbles repeat reminders, queued messages preserve progress, final dismissal restores idle and shutdown stops timers")
    finally:
        window.shutdown()

    restarted = create_pet(MANIFEST, 160, history_db=":memory:", settings_path=path)
    try:
        assert restarted.animation.idle_group == ["head-scratch"]
        assert restarted.animation.track_name == "head-scratch"
        assert restarted.animation.idle_weights == {"head-scratch": 2}
        data = {"idleGroups": {restarted.pet.data["id"]: ["missing", "head-scratch", "head-scratch"]},
                "idleWeights": {restarted.pet.data["id"]: {"missing": 10, "head-scratch": 2, "idle": -1}}}
        path.write_text(json.dumps(data), encoding="utf-8")
        assert PetSettings(path).idle_group(restarted.pet) == ["head-scratch"]
        assert PetSettings(path).idle_weights(restarted.pet) == {"head-scratch": 2}
        # Older settings files containing only group membership remain valid.
        path.write_text(json.dumps({"idleGroups": {restarted.pet.data["id"]: ["idle"]}}), encoding="utf-8")
        assert PetSettings(path).idle_weights(restarted.pet) == {}
        path.write_text("invalid json", encoding="utf-8")
        assert PetSettings(path).idle_group(restarted.pet) == restarted.pet.idle_group
    finally:
        restarted.shutdown()
    print("PASS: restart restores idle preferences; stale action names and malformed settings recover safely")
