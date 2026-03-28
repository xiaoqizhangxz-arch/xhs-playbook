"""
action_ranker.py — Utility × Relevance / Effort^0.5 优先级排序
"""
from __future__ import annotations
import math
from typing import Any

EFFORT_BY_ACTION_FAMILY: dict[str, float] = {
    "comment_pathing":    0.5,
    "pricing_adjustment": 0.5,
    "cs_script":          0.8,
    "content_brief":      1.0,
    "shop_asset_refresh": 1.2,
    "search_keyword":     1.0,
    "live_strategy":      2.0,
    "ads_optimization":   1.5,
    "private_domain":     1.2,
}

METRIC_OBJECTIVE_WEIGHT: dict[str, dict[str, float]] = {
    "conversion": {"shop_visit_to_pay_cvr": 1.0, "product_click_to_pay_cvr": 0.9,
                   "inquiry_to_pay_cvr": 0.8, "cover_ctr": 0.4, "aov": 0.5},
    "gmv":        {"shop_visit_to_pay_cvr": 0.7, "aov": 1.0, "repurchase_rate": 0.8},
    "followers_growth": {"cover_ctr": 1.0, "engagement_rate": 0.9, "recent_note_median_views": 0.8},
    "repurchase": {"repurchase_rate": 1.0, "aov": 0.6},
    "exposure":   {"recent_note_median_views": 1.0, "cover_ctr": 0.9, "engagement_rate": 0.7},
}
_DEFAULT_METRIC_WEIGHTS: dict[str, float] = {m: 0.5 for m in [
    "shop_visit_to_pay_cvr", "cover_ctr", "engagement_rate", "aov", "repurchase_rate"
]}


def _estimate_effort(ko: dict[str, Any]) -> float:
    families = ko.get("applicable_action_families") or []
    if not families:
        return 1.0
    return min(EFFORT_BY_ACTION_FAMILY.get(f, 1.0) for f in families)


def _compute_utility(ko: dict[str, Any], user_state: dict[str, Any],
                     bottleneck: dict[str, Any] | None) -> float:
    objective = user_state.get("primary_objective", "conversion")
    mw = METRIC_OBJECTIVE_WEIGHT.get(objective, _DEFAULT_METRIC_WEIGHTS)
    metrics = user_state.get("metrics", {})

    utility = 0.0
    for m in (ko.get("triggering_metrics") or []):
        val = metrics.get(m)
        obj_weight = mw.get(m, 0.3)
        # 指标越低，改善空间越大 → utility 越高
        if val is not None and val > 0:
            gap_factor = min(1.0, 1.0 / float(val)) if float(val) < 0.1 else 0.3
        else:
            gap_factor = 0.5  # 无数据时给中等 utility
        utility += obj_weight * gap_factor

    # 瓶颈指标加成
    if bottleneck and bottleneck.get("primary_metric") in (ko.get("triggering_metrics") or []):
        utility *= 1.5

    return max(utility, 0.1)


def rank_actions(
    kos: list[dict[str, Any]],
    user_state: dict[str, Any],
    bottleneck: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    scored = []
    for ko in kos:
        utility   = _compute_utility(ko, user_state, bottleneck)
        effort    = _estimate_effort(ko)
        relevance = ko.get("score", 1.0)
        priority  = utility * relevance / math.pow(max(effort, 0.1), 0.5)
        scored.append({
            **ko,
            "priority_score": round(priority, 2),
            "utility":        round(utility, 3),
            "effort":         round(effort, 1),
        })
    return sorted(scored, key=lambda x: -x["priority_score"])
