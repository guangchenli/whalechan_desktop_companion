"""Validated animation assets and an instance-owned bounded pixmap cache."""
from collections import OrderedDict
from dataclasses import dataclass
import json
from pathlib import Path
import re

from PyQt6.QtGui import QPixmap


ROWS = ["idle", "running-right", "running-left", "waving", "jumping",
        "failed", "waiting", "running", "review"]
COUNTS = [6, 8, 8, 4, 5, 8, 6, 6, 6]
DEFAULT_MS = [[500, 500, 600, 500, 500, 600], [300] * 7 + [400],
              [300] * 7 + [400], [450] * 4, [400, 400, 400, 450, 450],
              [550, 550, 550, 600, 650, 700, 550, 550],
              [550, 550, 600, 550, 550, 600], [330] * 5 + [400], [650] * 6]
LABELS = dict(zip(ROWS, ["待机", "向右跑", "向左跑", "招手", "跳跃", "失落", "等待", "忙碌", "思考"]))
LABELS.update({"shy": "害羞", "shy2": "害羞 2", "shy3": "害羞 3", "work": "工作",
               "sleep": "睡觉", "sleeping": "熟睡", "sleep-intro": "准备睡觉",
               "happy": "开心", "eat": "吃东西", "drag": "被提起", "standup": "站起来"})


@dataclass
class Track:
    frames: list
    durations: list[int]
    loop: bool = True
    fallback: str = "idle"


def frame_index(path):
    match = re.search(r"(\d+)(?:_\d+)?\.[^.]+$", path.name)
    return (int(match[1]) if match else 0, path.name)


class AssetLoadError(ValueError):
    """Invalid or unreadable pet assets, with manifest and field context."""


def positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 2147483647:
        raise ValueError(f"{field} 必须是正整数且不超过 Qt 计时器范围")
    return value


class Pet:
    def __init__(self, manifest):
        manifest = Path(manifest)
        self.path = manifest.parent
        self.tracks = {}
        self.sheet = None
        self.idle = "idle"
        self._cache = OrderedDict()
        try:
            self.data = json.loads(manifest.read_text(encoding="utf-8"))
            self.name = self.data["displayName"]
            if not isinstance(self.name, str) or not self.name.strip():
                raise ValueError("displayName 必须是非空文本")
            renderer = self.data["renderer"]
            if renderer == "sprite2d":
                self._load_sprite(self.data[renderer])
            elif renderer == "frames2d":
                self._load_frames(self.data[renderer])
            else:
                raise ValueError(f"不支持的 renderer：{renderer!r}")
            self._validate_tracks()
            if self.sheet is None:
                # Decode every file now: no missing image should first fail in paintEvent.
                for name, track in self.tracks.items():
                    for index in range(len(track.frames)):
                        self.pixmap(name, index)
                first = self.pixmap(self.idle, 0)
                self.width, self.height = first.width(), first.height()
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise AssetLoadError(f"素材加载失败 {manifest}：{exc}") from exc

    def _load_sprite(self, block):
        # The upstream sprite2d format uses this fixed nine-row action layout.
        cell = block.get("cell", {"width": 192, "height": 208})
        self.width = positive_int(cell["width"], "sprite2d.cell.width")
        self.height = positive_int(cell["height"], "sprite2d.cell.height")
        columns = positive_int(block.get("columns", 8), "sprite2d.columns")
        atlas_rows = positive_int(block.get("atlasRows", 9), "sprite2d.atlasRows")
        if atlas_rows < len(ROWS):
            raise ValueError("sprite2d.atlasRows 不足以容纳九行动作")
        self.sheet = QPixmap(str(self.path / block["spritesheetPath"]))
        if self.sheet.isNull() or (self.sheet.width(), self.sheet.height()) != (self.width * columns, self.height * atlas_rows):
            raise ValueError("sprite2d.spritesheetPath 精灵图缺失或尺寸错误")
        counts = block.get("frames", COUNTS)
        if not isinstance(counts, list) or len(counts) != len(ROWS):
            raise ValueError("sprite2d.frames 必须包含九行动作的帧数")
        for row, name in enumerate(ROWS):
            count = positive_int(counts[row], f"sprite2d.frames[{row}]")
            if count > columns:
                raise ValueError(f"sprite2d.frames[{row}] 超出精灵图列数")
            config = block.get("tracks", {}).get(name, {})
            durations = config.get("durations", DEFAULT_MS[row])
            if not isinstance(durations, list) or not durations:
                raise ValueError(f"sprite2d.tracks.{name}.durations 必须是非空列表")
            for ms in durations:
                positive_int(ms, f"sprite2d.tracks.{name}.durations")
            self.tracks[name] = Track(
                [(column * self.width, row * self.height, self.width, self.height) for column in range(count)],
                [durations[i % len(durations)] for i in range(count)],
                config.get("loop", name not in ("jumping", "failed")), config.get("fallback", self.idle))

    def _load_frames(self, block):
        self.idle = block["phases"]["idle"]
        default_ms = positive_int(block.get("defaultFrameMs", 200), "frames2d.defaultFrameMs")
        for name, config in block["tracks"].items():
            folder = self.path / block.get("dir", ".") / name
            if "frames" in config:
                if not isinstance(config["frames"], list):
                    raise ValueError(f"frames2d.tracks.{name}.frames 必须是列表")
                frames = [folder / filename for filename in config["frames"]]
            else:
                frames = sorted((p for p in folder.glob("*") if p.suffix.lower() in
                                 (".webp", ".png", ".jpg", ".jpeg", ".gif")), key=frame_index)
            if not frames:
                raise ValueError(f"frames2d.tracks.{name} 动画帧缺失：{folder}")
            frame_ms = config.get("frameMs")
            if "frameMs" in config:
                if not isinstance(frame_ms, list) or not frame_ms:
                    raise ValueError(f"frames2d.tracks.{name}.frameMs 必须是非空列表")
                for ms in frame_ms:
                    positive_int(ms, f"frames2d.tracks.{name}.frameMs")
            durations = []
            for i, frame in enumerate(frames):
                ms = default_ms
                tail = re.search(r"_(\d+)\.[^.]+$", frame.name)
                if tail and 16 <= int(tail[1]) <= 5000:
                    ms = int(tail[1])
                if frame_ms is not None:
                    ms = frame_ms[i] if i < len(frame_ms) else default_ms
                durations.append(ms)
            self.tracks[name] = Track(frames, durations, config.get("loop", True), config.get("fallback", self.idle))

    def _validate_tracks(self):
        if not isinstance(self.idle, str) or self.idle not in self.tracks:
            raise ValueError(f"idle 动作不存在：{self.idle!r}")
        for name, track in self.tracks.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("动作名称必须是非空文本")
            if not track.frames or len(track.frames) != len(track.durations):
                raise ValueError(f"tracks.{name} 帧数与时长不一致")
            if not isinstance(track.loop, bool):
                raise ValueError(f"tracks.{name}.loop 必须是布尔值")
            if not isinstance(track.fallback, str) or track.fallback not in self.tracks:
                raise ValueError(f"tracks.{name}.fallback 动作不存在：{track.fallback!r}")
            for ms in track.durations:
                positive_int(ms, f"tracks.{name}.durations")

    def pixmap(self, track, index):
        key = (track, index)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        frame = self.tracks[track].frames[index]
        pixmap = self.sheet.copy(*frame) if self.sheet is not None else QPixmap(str(frame))
        if pixmap.isNull():
            raise ValueError(f"无法读取动画帧：{frame}")
        self._cache[key] = pixmap
        if len(self._cache) > 100:
            self._cache.popitem(last=False)
        return pixmap
