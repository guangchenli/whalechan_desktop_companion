"""Shared notification rules and JSON boundary types, independent of Qt and MCP."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
from typing import Literal
import uuid

from typing_extensions import TypedDict

MAX_MESSAGE = 2000
MAX_TITLE = 60
MAX_QUEUE = 20


class BellResult(TypedDict):
    status: Literal["displayed", "queued"]
    id: str
    queued: int


class PetStatus(TypedDict):
    running: bool
    pet: str
    queued: int
    current_id: str | None
    current_action: str
    paused: bool


class ActionInfo(TypedDict):
    action: str
    label: str
    loop: bool
    fallback: str
    duration_seconds: float


class ActionList(TypedDict):
    pet: str
    current_action: str
    paused: bool
    actions: list[ActionInfo]


class ActionResult(TypedDict):
    status: Literal["playing"]
    action: str
    label: str
    once: bool
    looping: bool
    fallback: str


@dataclass(frozen=True)
class Notification:
    message: str
    title: str = "Agent"
    duration_seconds: float = 12
    sound: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    received_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class HistoryRecord:
    sequence: int
    notification_id: str
    received_at: str
    title: str
    message: str
    duration_seconds: float
    sound: bool

    @classmethod
    def from_row(cls, row):
        values = dict(row)
        values["sound"] = bool(values["sound"])
        return cls(**values)

    def to_dict(self):
        return asdict(self)


def validate_notification(message, title="Agent", duration_seconds=12, sound=False):
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE:
        raise ValueError(f"message 必须是 1–{MAX_MESSAGE} 字符的非空文本")
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE or "\n" in title or "\r" in title:
        raise ValueError("title 必须是 1–60 字符的单行文本")
    if (isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds) or not 3 <= duration_seconds <= 120):
        raise ValueError("duration_seconds 必须在 3–120 秒之间")
    if not isinstance(sound, bool):
        raise ValueError("sound 必须是布尔值")
    return dict(message=message.strip(), title=title.strip(),
                duration_seconds=duration_seconds, sound=sound)


def validate_action(action, once=True):
    if not isinstance(action, str) or not action.strip() or len(action) > 64:
        raise ValueError("action 必须是 1–64 字符的动作名称")
    if not isinstance(once, bool):
        raise ValueError("once 必须是布尔值")
    return dict(action=action, once=once)
