"""
semantic_booster.py — 四维乘法 boost，叠加在 BM25 分数之上
"""
from __future__ import annotations
from typing import Any

ADJACENT_STAGES: dict[str, list[str]] = {
    "cold_start":   ["ramp_up"],
    "ramp_up":      ["cold_start", "breakthrough"],
    "breakthrough": ["ramp_up", "burst"],
    "burst":        ["breakthrough", "daily_ops"],
    "daily_ops":    ["burst", "campaign"],
    "campaign":     ["daily_ops"],
}

SIMILAR_INDUSTRIES: dict[str, list[str]] = {
    "珠宝配饰": ["奢品", "服饰", "珠宝腕表", "文玩玉翠"],
    "珠宝腕表": ["奢品", "珠宝配饰"],
    "服饰":     ["服饰潮流", "潮流服饰", "奢品"],
    "美妆":     ["个护", "大健康"],
    "食品饮料": ["乳制品", "美食"],
    "母婴":     ["教育", "玩具"],
    "家居家装": ["家居", "建材"],
    "大健康":   ["美妆", "个护", "医疗"],
}

UNRELATED_INDUSTRIES = {"母婴", "汽车", "3C家电", "乳制品", "宠物", "金融", "房地产"}


def compute_boost(
    ko: dict[str, Any],
    user_state: dict[str, Any],
    bottleneck_metric: str | None = None,
) -> float:
    b = 1.0
    b *= _metrics_boost(ko, bottleneck_metric, user_state)
    b *= _stage_boost(ko, user_state.get("stage", ""))
    b *= _bm_boost(ko, user_state.get("business_model", []))
    b *= _industry_boost(ko, user_state.get("industry", "通用"),
                         user_state.get("inferred", {}).get("industry_weights", {}))
    return b


# ── 四个 boost 函数 ────────────────────────────────────────────────────────

def _metrics_boost(ko: dict, bottleneck_metric: str | None, user_state: dict) -> float:
    ko_metrics = set(ko.get("triggering_metrics") or [])
    if not ko_metrics:
        return 1.0
    if bottleneck_metric and bottleneck_metric in ko_metrics:
        return 2.5
    weak = set(user_state.get("weak_metrics") or [])
    if ko_metrics & weak:
        return 1.5
    return 1.0


def _stage_boost(ko: dict, user_stage: str) -> float:
    ko_stages = set(ko.get("stage") or [])
    if not ko_stages or "all" in ko_stages:
        return 1.2
    if user_stage in ko_stages:
        return 1.8
    adjacent = set(ADJACENT_STAGES.get(user_stage, []))
    if ko_stages & adjacent:
        return 1.2
    return 0.7


def _bm_boost(ko: dict, user_bm: list[str]) -> float:
    ko_bm = set(ko.get("business_model") or [])
    if not ko_bm or "all" in ko_bm:
        return 1.2
    overlap = len(ko_bm & set(user_bm))
    return 1.0 + 0.3 * overlap


def _industry_boost(ko: dict, user_industry: str, weights: dict[str, float]) -> float:
    ko_ind = set(ko.get("applicable_industry") or ko.get("_industry") or [])
    if not ko_ind:
        return 1.0
    if user_industry in ko_ind:
        return weights.get(user_industry, 1.6)
    if "通用" in ko_ind:
        return 1.3
    similar = set(SIMILAR_INDUSTRIES.get(user_industry, []))
    if ko_ind & similar:
        return 1.2
    if ko_ind & UNRELATED_INDUSTRIES:
        return 0.7
    return 1.0
