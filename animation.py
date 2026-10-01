"""Single actions, random idle playback and persistent notification attention."""
import random
from collections import deque

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from contracts import validate_action
from idle_weights import default_idle_weights, validate_idle_weights


class AnimationPlayer(QObject):
    frame_changed = pyqtSignal()
    track_started = pyqtSignal(str)
    sequence_finished = pyqtSignal(str)

    def __init__(self, pet, parent=None, idle_group=None, idle_weights=None):
        super().__init__(parent)
        self.pet = pet
        self.paused = False
        self.closed = False
        self.track_name = pet.idle
        self.frame = 0
        self.once = False
        self.idle_group = list(pet.idle_group if idle_group is None else idle_group)
        self.idle_weights = dict(idle_weights or {})
        validate_idle_weights(self.idle_weights, pet.tracks)
        self.mode = "idle"
        self.notification_active = False
        self._sequence = deque()
        self._frame_order = []
        self._position = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        self.play_idle()

    def play(self, name, once=False):
        if self.mode in ("startup", "shutdown"):
            raise ValueError("桌宠正在启动或退出，请稍后播放动作")
        if name not in self.pet.tracks:
            raise ValueError(f"未知动作 {name!r}；可用动作：{', '.join(self.pet.tracks)}")
        self.mode = "action"
        self._start(name, once)

    def _start(self, name, once=False, frame_order=None):
        if self.closed:
            return
        self._frame_order = list(range(len(self.pet.tracks[name].frames))) if frame_order is None else list(frame_order)
        self._position = 0
        self.track_name, self.frame, self.once = name, self._frame_order[0], once
        self.timer.stop()
        if not self.paused:
            self.timer.start(self.pet.tracks[name].durations[self.frame])
        self.frame_changed.emit()
        self.track_started.emit(name)

    def play_sequence(self, steps, mode):
        if self.closed:
            raise ValueError("桌宠正在退出")
        if mode not in ("startup", "shutdown") or not steps:
            raise ValueError("动画序列需要启动或退出模式及至少一个动作")
        prepared = []
        for name, order in steps:
            if name not in self.pet.tracks:
                raise ValueError(f"未知序列动作：{name}")
            frames = list(range(len(self.pet.tracks[name].frames))) if order is None else list(order)
            if not frames or any(isinstance(i, bool) or not isinstance(i, int)
                                 or not 0 <= i < len(self.pet.tracks[name].frames) for i in frames):
                raise ValueError(f"序列动作 {name} 的帧序无效")
            prepared.append((name, frames))
        self.paused = False
        self.mode = mode
        self._sequence = deque(prepared)
        name, frames = self._sequence.popleft()
        self._start(name, frame_order=frames)

    def resume_background(self):
        if self.notification_active and "notification" in self.pet.tracks:
            self.mode = "notification"
            self._start("notification")
        else:
            self.play_idle()

    def play_idle(self):
        self.mode = "idle"
        weights = self.effective_idle_weights()
        choices = [name for name in self.idle_group if weights[name] > 0]
        self._start(random.choices(choices, weights=[weights[name] for name in choices], k=1)[0]
                    if choices else self.pet.idle)
        if not choices:
            # An empty group leaves a static base pose, rather than reintroducing
            # an animation the user has explicitly removed from the group.
            self.timer.stop()

    def effective_idle_weights(self):
        defaults = default_idle_weights(self.idle_group, self.pet.idle)
        return {name: self.idle_weights.get(name, weight) for name, weight in defaults.items()}

    def idle_probabilities(self):
        weights = self.effective_idle_weights()
        total = sum(weights.values())
        return {name: weight / total if total else 0.0 for name, weight in weights.items()}

    def set_idle_group(self, names):
        if (not isinstance(names, list) or any(not isinstance(name, str) or name not in self.pet.tracks for name in names)
                or len(set(names)) != len(names)):
            raise ValueError("待机组必须是不重复的已有动作名称列表")
        was_static = not any(self.effective_idle_weights().values())
        self.idle_group = list(names)
        if self.mode == "idle" and (was_static or self.effective_idle_weights().get(self.track_name, 0) == 0):
            self.play_idle()

    def set_idle_weights(self, weights):
        validate_idle_weights(weights, self.pet.tracks)
        was_static = not any(self.effective_idle_weights().values())
        self.idle_weights = dict(weights)
        if self.mode == "idle" and (was_static or self.effective_idle_weights().get(self.track_name, 0) == 0):
            self.play_idle()

    def set_notification_active(self, active):
        if self.closed:
            return
        was_active = self.notification_active
        self.notification_active = active
        if self.mode in ("startup", "shutdown"):
            return
        if active and "notification" in self.pet.tracks:
            was_paused = self.paused
            self.paused = False
            if not was_active or self.mode != "notification":
                self.mode = "notification"
                self._start("notification")
            elif was_paused:
                self.timer.start(self.pet.tracks[self.track_name].durations[self.frame])
        elif was_active:
            self.play_idle()

    def advance(self):
        if self.closed or self._position >= len(self._frame_order):
            return
        track = self.pet.tracks[self.track_name]
        self._position += 1
        if self._position == len(self._frame_order):
            if self.mode in ("startup", "shutdown"):
                if self._sequence:
                    name, frames = self._sequence.popleft()
                    self._start(name, frame_order=frames)
                else:
                    self.timer.stop()
                    self.sequence_finished.emit(self.mode)
            elif self.notification_active and "notification" in self.pet.tracks:
                self.resume_background()
            elif self.mode == "idle" or self.once or track.fallback == self.pet.idle:
                self.play_idle()
            else:
                self.play(track.fallback)
            return
        self.frame = self._frame_order[self._position]
        self.frame_changed.emit()
        self.timer.start(track.durations[self.frame])

    def toggle_pause(self, checked):
        if self.mode in ("startup", "shutdown"):
            return
        self.paused = checked
        self.timer.stop()
        if not checked and not self.closed:
            if self.mode != "idle" or any(self.effective_idle_weights().values()):
                self.timer.start(self.pet.tracks[self.track_name].durations[self.frame])

    def list_actions(self):
        return dict(pet=self.pet.name, current_action=self.track_name, paused=self.paused,
                    actions=[dict(action=name, label=self.pet.labels.get(name, name), loop=track.loop,
                                  fallback=track.fallback, duration_seconds=sum(track.durations) / 1000)
                             for name, track in self.pet.tracks.items()])

    def play_action(self, action, once=True):
        validate_action(action, once)
        if self.closed:
            raise ValueError("桌宠正在退出")
        if action not in self.pet.tracks:
            raise ValueError(f"未知动作 {action!r}；可用动作：{', '.join(self.pet.tracks)}")
        if self.mode in ("startup", "shutdown"):
            raise ValueError("桌宠正在启动或退出，请稍后播放动作")
        self.paused = False
        self.play(action, once=once)
        return dict(status="playing", action=action, label=self.pet.labels.get(action, action), once=once,
                    looping=action == "notification" and self.notification_active,
                    fallback="notification" if self.notification_active and "notification" in self.pet.tracks else self.pet.idle)

    def close(self):
        self.closed = True
        self.timer.stop()
