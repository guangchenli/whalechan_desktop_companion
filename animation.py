"""Animation playback state and timer; rendering remains the window's responsibility."""
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from contracts import validate_action
from pet_assets import LABELS


class AnimationPlayer(QObject):
    frame_changed = pyqtSignal()

    def __init__(self, pet, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.paused = False
        self.track_name = pet.idle
        self.frame = 0
        self.once = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.advance)
        self.play(pet.idle)

    def play(self, name, once=False):
        if name not in self.pet.tracks:
            raise ValueError(f"未知动作 {name!r}；可用动作：{', '.join(self.pet.tracks)}")
        self.track_name, self.frame, self.once = name, 0, once
        self.timer.stop()
        if not self.paused:
            self.timer.start(self.pet.tracks[name].durations[0])
        self.frame_changed.emit()

    def advance(self):
        track = self.pet.tracks[self.track_name]
        self.frame += 1
        if self.frame == len(track.frames):
            if self.once or not track.loop:
                self.play(self.pet.idle if self.once else track.fallback)
                return
            self.frame = 0
        self.frame_changed.emit()
        self.timer.start(track.durations[self.frame])

    def toggle_pause(self, checked):
        self.paused = checked
        self.timer.stop()
        if not checked:
            self.timer.start(self.pet.tracks[self.track_name].durations[self.frame])

    def list_actions(self):
        return dict(pet=self.pet.name, current_action=self.track_name, paused=self.paused,
                    actions=[dict(action=name, label=LABELS.get(name, name), loop=track.loop,
                                  fallback=track.fallback, duration_seconds=sum(track.durations) / 1000)
                             for name, track in self.pet.tracks.items()])

    def play_action(self, action, once=True):
        validate_action(action, once)
        if action not in self.pet.tracks:
            raise ValueError(f"未知动作 {action!r}；可用动作：{', '.join(self.pet.tracks)}")
        self.paused = False
        self.play(action, once=once)
        track = self.pet.tracks[action]
        return dict(status="playing", action=action, label=LABELS.get(action, action), once=once,
                    looping=not once and track.loop, fallback=self.pet.idle if once else track.fallback)

    def close(self):
        self.timer.stop()
