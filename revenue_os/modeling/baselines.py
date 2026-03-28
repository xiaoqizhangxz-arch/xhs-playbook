from __future__ import annotations

from typing import Any


def simple_statistical_baseline(state: dict[str, Any]) -> str:
    metric_snapshot = state.get("metric_snapshot", {})
    scores = {
        "conversion_repair": max(
            0.0,
            1.0 - float(metric_snapshot.get("shop_visit_to_pay_cvr") or 0.0) / 0.02,
            1.0 - float(metric_snapshot.get("inquiry_to_pay_cvr") or 0.0) / 0.20,
        ),
        "aov_lift": max(0.0, 1.0 - float(metric_snapshot.get("aov") or 0.0) / 300.0),
        "repurchase_activation": max(0.0, 1.0 - float(metric_snapshot.get("repurchase_rate") or 0.0) / 0.08),
        "search_positioning": max(0.0, float(len(state.get("search_opportunities", []))) / 5.0),
        "content_formula_scaling": max(
            0.0,
            float(state.get("creator_signal_summary", {}).get("recent_note_median_views", 0.0) or 0.0) / 1200.0,
        ),
    }
    return max(scores.items(), key=lambda item: item[1])[0]
