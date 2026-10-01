"""Default idle probabilities and validation of relative selection weights."""
import math


MAX_IDLE_WEIGHT = 1_000_000


def valid_idle_weight(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= MAX_IDLE_WEIGHT and math.isfinite(value))


def validate_idle_weights(weights, actions):
    if (not isinstance(weights, dict)
            or any(name not in actions or not valid_idle_weight(value) for name, value in weights.items())):
        raise ValueError("待机权重必须是已有动作到 0–1000000 之间有限数值的映射")


def default_idle_weights(names, idle):
    if not names:
        return {}
    if idle in names and len(names) > 1:
        return {name: 90.0 if name == idle else 10.0 / (len(names) - 1) for name in names}
    return {name: 100.0 / len(names) for name in names}
