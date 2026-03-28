from __future__ import annotations

import math
from typing import Iterable


def weighted_geometric_mean(values: dict[str, float], weights: dict[str, float]) -> float:
    safe_values = []
    total_weight = 0.0
    for key, value in values.items():
        weight = weights.get(key, 1.0)
        total_weight += weight
        clipped = min(max(value, 1e-6), 1.0)
        safe_values.append(math.log(clipped) * weight)
    if not safe_values or total_weight <= 0:
        return 0.0
    return math.exp(sum(safe_values) / total_weight)
