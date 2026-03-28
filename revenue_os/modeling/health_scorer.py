"""
health_scorer.py — 多维指标 → 0-100 健康总分 + 瓶颈维度识别
用 sigmoid 归一化（相对于 benchmark），按 primary_objective 加权聚合。
"""
from __future__ import annotations
import math
from typing import Any

DIMENSION_METRICS: dict[str, list[str]] = {
    "traffic":    ["recent_note_median_views", "cover_ctr"],
    "engagement": ["engagement_rate", "completion_rate"],
    "conversion": ["shop_visit_to_pay_cvr", "product_click_to_pay_cvr"],
    "revenue":    ["aov", "repurchase_rate"],
    "activity":   ["recent_note_count_30d", "search_ctr"],
}

# 指标方向：False = 越高越好（默认），True = 越低越好
LOWER_IS_BETTER = {"refund_rate"}

OBJECTIVE_WEIGHTS: dict[str, dict[str, float]] = {
    "conversion":       {"traffic": 0.15, "engagement": 0.15, "conversion": 0.40, "revenue": 0.20, "activity": 0.10},
    "followers_growth": {"traffic": 0.35, "engagement": 0.30, "conversion": 0.10, "revenue": 0.05, "activity": 0.20},
    "gmv":              {"traffic": 0.10, "engagement": 0.10, "conversion": 0.30, "revenue": 0.40, "activity": 0.10},
    "repurchase":       {"traffic": 0.10, "engagement": 0.15, "conversion": 0.15, "revenue": 0.45, "activity": 0.15},
    "exposure":         {"traffic": 0.40, "engagement": 0.30, "conversion": 0.05, "revenue": 0.05, "activity": 0.20},
    "store_visit":      {"traffic": 0.30, "engagement": 0.20, "conversion": 0.30, "revenue": 0.10, "activity": 0.10},
    "roi":              {"traffic": 0.10, "engagement": 0.10, "conversion": 0.25, "revenue": 0.45, "activity": 0.10},
    "lead_capture":     {"traffic": 0.25, "engagement": 0.25, "conversion": 0.25, "revenue": 0.10, "activity": 0.15},
}
_DEFAULT_WEIGHTS = {"traffic": 0.20, "engagement": 0.20, "conversion": 0.25, "revenue": 0.20, "activity": 0.15}

BOTTLENECK_GAP_THRESHOLD = 15  # 低于总分此值则标记为显著瓶颈


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def _normalize_metric(value: float, benchmark: float, lower_is_better: bool = False) -> float:
    """归一化为 [0,1]：相对 benchmark 的 z-score → sigmoid"""
    if benchmark <= 0:
        return 0.5
    z = (value - benchmark) / (benchmark * 0.5)  # σ ≈ 50% of benchmark
    if lower_is_better:
        z = -z
    return _sigmoid(z)


def compute_health_score(
    user_state: dict[str, Any],
    benchmarks: dict[str, Any],
) -> dict[str, Any]:
    """
    输入:
      user_state  — 含 metrics / stage / business_model / primary_objective
      benchmarks  — {metric_name: {p50: float, ...}} 或扁平 {metric_name: float}

    输出:
      {
        total_score: int,          # 0-100
        dimension_scores: dict,    # 每个维度 0-100
        bottleneck: dict | None,   # 最弱维度及其主指标
        data_coverage: int,        # 已填指标数 / 总指标数
        missing_metrics: list,
      }
    """
    metrics = user_state.get("metrics", {})
    objective = user_state.get("primary_objective", "conversion")
    weights = OBJECTIVE_WEIGHTS.get(objective, _DEFAULT_WEIGHTS)

    def get_benchmark(name: str) -> float | None:
        b = benchmarks.get(name)
        if b is None:
            return None
        if isinstance(b, dict):
            return b.get("p50")
        return float(b)

    dim_scores: dict[str, float] = {}
    dim_coverage: dict[str, int] = {}

    for dim, metric_names in DIMENSION_METRICS.items():
        scores = []
        for name in metric_names:
            val = metrics.get(name)
            if val is None:
                continue
            bench = get_benchmark(name)
            if bench is None:
                # 无基准时用 sigmoid(0) = 50
                scores.append(50.0)
                continue
            lower = name in LOWER_IS_BETTER
            scores.append(_normalize_metric(float(val), float(bench), lower) * 100)
        dim_scores[dim] = sum(scores) / len(scores) if scores else 50.0
        dim_coverage[dim] = len(scores)

    # 加权总分
    total = sum(weights.get(d, 0.2) * s for d, s in dim_scores.items())
    total = round(min(max(total, 0), 100))

    # 瓶颈识别：最低维度且低于总分 BOTTLENECK_GAP_THRESHOLD
    worst_dim = min(dim_scores, key=lambda d: dim_scores[d])
    worst_score = dim_scores[worst_dim]
    bottleneck = None
    if worst_score < (total - BOTTLENECK_GAP_THRESHOLD):
        # 找该维度里最弱的指标
        worst_metric = None
        worst_metric_score = 999.0
        for name in DIMENSION_METRICS[worst_dim]:
            val = metrics.get(name)
            bench = get_benchmark(name)
            if val is not None and bench is not None:
                s = _normalize_metric(float(val), float(bench), name in LOWER_IS_BETTER) * 100
                if s < worst_metric_score:
                    worst_metric_score = s
                    worst_metric = name
        bottleneck = {
            "dimension": worst_dim,
            "dimension_score": round(worst_score),
            "gap_vs_total": round(total - worst_score),
            "primary_metric": worst_metric,
            "current_value": metrics.get(worst_metric),
            "benchmark_p50": get_benchmark(worst_metric) if worst_metric else None,
        }

    # 数据覆盖率
    all_metrics = [m for ms in DIMENSION_METRICS.values() for m in ms]
    filled = sum(1 for m in all_metrics if metrics.get(m) is not None)
    missing = [m for m in all_metrics if metrics.get(m) is None]

    return {
        "total_score": total,
        "dimension_scores": {d: round(s) for d, s in dim_scores.items()},
        "bottleneck": bottleneck,
        "data_coverage": f"{filled}/{len(all_metrics)}",
        "missing_metrics": missing,
        "objective_weights_used": objective,
    }
