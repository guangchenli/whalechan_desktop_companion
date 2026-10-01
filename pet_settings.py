"""Atomic local preferences for each pet's idle group."""
import json
import logging
from pathlib import Path

from PyQt6.QtCore import QIODevice, QSaveFile

from history_store import DEFAULT_HISTORY_DB
from idle_weights import valid_idle_weight, validate_idle_weights


DEFAULT_SETTINGS_FILE = DEFAULT_HISTORY_DB.parent / "settings.json"


class PetSettings:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self.groups = {}
        self.weights = {}
        if self.path is not None and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                groups = data["idleGroups"]
                if (not isinstance(groups, dict)
                        or any(not isinstance(names, list) or any(not isinstance(name, str) for name in names)
                               for names in groups.values())):
                    raise ValueError("idleGroups 格式无效")
                self.groups = groups
                weights = data.get("idleWeights", {})
                if isinstance(weights, dict):
                    self.weights = {pet: {name: value for name, value in values.items() if valid_idle_weight(value)}
                                    for pet, values in weights.items() if isinstance(values, dict)}
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logging.getLogger(__name__).warning("无法读取待机组设置，使用默认值：%s", exc)

    def idle_group(self, pet):
        names = self.groups.get(pet.data.get("id", pet.name), pet.idle_group)
        return list(dict.fromkeys(name for name in names if name in pet.tracks))

    def save_idle_group(self, pet, names):
        groups = self.groups | {pet.data.get("id", pet.name): list(names)}
        self._save(groups, self.weights)

    def idle_weights(self, pet):
        weights = self.weights.get(pet.data.get("id", pet.name), {})
        return {name: value for name, value in weights.items() if name in pet.tracks and valid_idle_weight(value)}

    def save_idle_weights(self, pet, values):
        validate_idle_weights(values, pet.tracks)
        weights = self.weights | {pet.data.get("id", pet.name): dict(values)}
        self._save(self.groups, weights)

    def _save(self, groups, weights):
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            output = QSaveFile(str(self.path))
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            payload = (json.dumps({"idleGroups": groups, "idleWeights": weights}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if output.write(payload) != len(payload):
                output.cancelWriting()
                raise OSError(output.errorString())
            if not output.commit():
                raise OSError(output.errorString())
        self.groups = groups
        self.weights = weights
