"""
profile_builder.py — 问卷 responses → brand_profile，含推断层
"""
from __future__ import annotations
from typing import Any

# ── 阶段相邻关系（检索时也用）────────────────────────────────────────────────
ADJACENT_STAGES: dict[str, list[str]] = {
    "cold_start":   ["ramp_up"],
    "ramp_up":      ["cold_start", "breakthrough"],
    "breakthrough": ["ramp_up", "burst"],
    "burst":        ["breakthrough", "daily_ops"],
    "daily_ops":    ["burst", "campaign"],
    "campaign":     ["daily_ops"],
}

SIMILAR_INDUSTRIES: dict[str, list[str]] = {
    "珠宝配饰": ["奢品", "服饰", "珠宝腕表"],
    "珠宝腕表": ["奢品", "珠宝配饰"],
    "服饰":     ["服饰潮流", "潮流服饰", "奢品"],
    "美妆":     ["个护", "大健康"],
    "食品饮料": ["乳制品"],
    "母婴":     ["教育"],
    "家居家装": ["家居"],
}

# ── 冷启动先验 ────────────────────────────────────────────────────────────────
COLD_START_PRIORS: dict[tuple, dict] = {
    ("cold_start", "content"):    {"primary_mission": "content_formula_scaling", "kb_hint": "新账号最核心任务是找到可复制的内容公式，封面CTR是第一优先级。"},
    ("cold_start", "ecommerce"):  {"primary_mission": "content_formula_scaling", "kb_hint": "挂车号冷启动期先跑内容，别急着优化转化——没流量优化转化没意义。"},
    ("cold_start", "store_live"): {"primary_mission": "content_formula_scaling", "kb_hint": "开播前用笔记蓄水，冷启动期用笔记测封面点击率。"},
    ("ramp_up",    "ecommerce"):  {"primary_mission": "conversion_repair",       "kb_hint": "爬坡期已有稳定流量，进店转化率是最高价值改善点。"},
    ("ramp_up",    "store_live"): {"primary_mission": "conversion_repair",       "kb_hint": "直播号爬坡期，商品点击→付款转化是核心杠杆。"},
    ("ramp_up",    "content"):    {"primary_mission": "content_formula_scaling", "kb_hint": "内容号爬坡期目标是找到2-3个可持续的爆款公式。"},
    ("breakthrough","ecommerce"): {"primary_mission": "aov_lift",                "kb_hint": "突破期流量已验证，提升客单价是GMV增长的乘数效应点。"},
    ("breakthrough","store_live"):{"primary_mission": "aov_lift",                "kb_hint": "直播突破期用搭配组合拉高每单客单价。"},
    ("daily_ops",  "ecommerce"):  {"primary_mission": "repurchase_activation",   "kb_hint": "日常运营期私域复购是利润率最高的增长来源。"},
}

INDUSTRY_PAIN_POINTS: dict[str, dict] = {
    "珠宝配饰": {"common_missions": ["conversion_repair", "aov_lift"],          "pain": "珠宝行业信任决策周期长，进店转化率普遍1-2%，核心是信任建立。"},
    "服饰":     {"common_missions": ["content_formula_scaling", "repurchase_activation"], "pain": "服饰封面竞争激烈，CTR是第一瓶颈；复购需要主动私域运营。"},
    "美妆":     {"common_missions": ["content_formula_scaling", "search_positioning"],    "pain": "美妆搜索流量大，SEO关键词卡位价值极高。"},
    "食品饮料": {"common_missions": ["repurchase_activation", "aov_lift"],       "pain": "食品复购率高，主动复购激活ROI最高。"},
    "母婴":     {"common_missions": ["content_formula_scaling", "conversion_repair"],     "pain": "母婴用户决策谨慎，内容专业度直接影响转化。"},
    "家居家装": {"common_missions": ["search_positioning", "conversion_repair"],  "pain": "家装高客单，搜索意图明确，SEO卡位高价值。"},
    "通用":     {"common_missions": ["content_formula_scaling", "conversion_repair"],     "pain": ""},
}

PAIN_TO_MISSION: dict[str, str] = {
    "no_traffic":            "content_formula_scaling",
    "traffic_no_conversion": "conversion_repair",
    "low_aov":               "aov_lift",
    "no_repurchase":         "repurchase_activation",
    "search_invisible":      "search_positioning",
    "content_stuck":         "content_formula_scaling",
}

METRIC_TO_MISSION: dict[str, str] = {
    "shop_visit_to_pay_cvr":    "conversion_repair",
    "product_click_to_pay_cvr": "conversion_repair",
    "inquiry_to_pay_cvr":       "conversion_repair",
    "cover_ctr":                "content_formula_scaling",
    "engagement_rate":          "content_formula_scaling",
    "completion_rate":          "content_formula_scaling",
    "search_ctr":               "search_positioning",
    "aov":                      "aov_lift",
    "repurchase_rate":          "repurchase_activation",
}


def _detect_weakest_metric(metrics: dict[str, Any], thresholds: dict[str, Any]) -> str | None:
    candidates = [
        ("shop_visit_to_pay_cvr",    thresholds.get("shop_visit_to_pay_cvr_low", 0.015)),
        ("product_click_to_pay_cvr", thresholds.get("product_click_to_pay_cvr_low", 0.03)),
        ("aov",                      thresholds.get("aov_low", 0)),
        ("search_ctr",               thresholds.get("search_opportunity_ctr", 0.08)),
        ("cover_ctr",                0.04),
        ("repurchase_rate",          0.05),
    ]
    for name, floor in candidates:
        val = metrics.get(name)
        if val is not None and floor and float(val) < float(floor):
            return name
    return None


def _compute_industry_weights(industry: str) -> dict[str, float]:
    similar = SIMILAR_INDUSTRIES.get(industry, [])
    weights = {"通用": 1.3}
    weights[industry] = 1.6
    for s in similar:
        weights[s] = 1.4
    for unrelated in ["母婴", "汽车", "3C家电", "乳制品", "宠物", "金融", "房地产"]:
        weights.setdefault(unrelated, 0.7)
    return weights


def infer_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    stage    = profile.get("stage", "ramp_up")
    bm_list  = profile.get("business_model", ["ecommerce"])
    bm       = bm_list[0] if bm_list else "ecommerce"
    industry = profile.get("industry", "通用")
    metrics  = profile.get("metrics") or {}
    thresholds = profile.get("thresholds") or {}
    pain_points = profile.get("pain_points") or []

    # primary mission
    weak = _detect_weakest_metric(metrics, thresholds)
    pain_missions = [PAIN_TO_MISSION[p] for p in pain_points if p in PAIN_TO_MISSION]
    if weak:
        primary_mission = METRIC_TO_MISSION.get(weak, pain_missions[0] if pain_missions else "content_formula_scaling")
    elif pain_missions:
        primary_mission = pain_missions[0]
    else:
        prior = COLD_START_PRIORS.get((stage, bm)) or COLD_START_PRIORS.get(("cold_start", "content"))
        primary_mission = prior["primary_mission"] if prior else "content_formula_scaling"

    adjacent = ADJACENT_STAGES.get(stage, [stage])
    ind_hints = INDUSTRY_PAIN_POINTS.get(industry, INDUSTRY_PAIN_POINTS["通用"])

    return {
        "primary_mission": primary_mission,
        "industry_weights": _compute_industry_weights(industry),
        "kb_filter": {
            "stage": [stage] + adjacent,
            "business_model": bm_list,
            "applicable_industry": [industry] + SIMILAR_INDUSTRIES.get(industry, []) + ["通用"],
        },
        "cold_start_hint": COLD_START_PRIORS.get((stage, bm), {}).get("kb_hint", ""),
        "industry_pain": ind_hints.get("pain", ""),
    }


def generate_brand_profile(responses: dict[str, Any]) -> dict[str, Any]:
    """问卷 responses → 完整 brand_profile（含 inferred 块）"""
    from datetime import datetime
    METRIC_FIELDS = {
        "recent_note_median_views", "cover_ctr", "engagement_rate",
        "completion_rate", "search_ctr", "shop_visit_to_pay_cvr",
        "product_click_to_pay_cvr", "aov", "repurchase_rate", "recent_note_count_30d",
    }
    profile: dict[str, Any] = {
        "profile_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "role":              responses.get("role", "merchant"),
        "business_model":    responses.get("business_model", ["ecommerce"]),
        "industry":          responses.get("industry", "通用"),
        "stage":             responses.get("stage", "ramp_up"),
        "account_age_months": responses.get("account_age_months"),
        "primary_objective": responses.get("primary_objective", "conversion"),
        "monthly_gmv_target": responses.get("monthly_gmv_target"),
        "content_capacity":  responses.get("content_capacity", "3-5/week"),
        "has_live":          responses.get("has_live", False),
        "pain_points":       responses.get("pain_points", []),
        "metrics": {k: v for k, v in responses.items() if k in METRIC_FIELDS and v is not None},
    }
    profile["inferred"] = infer_from_profile(profile)
    return profile
