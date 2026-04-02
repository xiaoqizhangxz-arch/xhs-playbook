"""
xlsx_state_adapter.py — ETL metrics_snapshot → current_state.metric_snapshot 适配层

将 xlsx_etl.run_etl() 输出的轻量指标集映射为
current_state.metric_snapshot 可消费的统一格式，
并打 source_truth="xlsx_history_truth" 区分来源。

主入口：
    etl_to_metric_patch(etl_snapshot) -> dict[str, Any]
    merge_into_state_snapshot(state, etl_snapshot) -> dict[str, Any]
"""
from __future__ import annotations

from statistics import median
from typing import Any


# ── 固定比例字段：直接 1:1 映射 ─────────────────────────────────────────────

_DIRECT_MAP: dict[str, str] = {
    "shop_visit_to_pay_cvr": "shop_visit_to_pay_cvr",
    "aov": "aov",
    "refund_rate": "refund_rate",
    "visitors": "visitors",  # 非标准 metric，只写 info
}

# ── AINRL derived → metric_snapshot 代理映射 ────────────────────────────────
# 口径差异说明：
#   ETL 的 ainrl.derived.i_to_n = AINRL 兴趣层→新客层（全人群口径）
#   registry 的 deal_intent_to_new_cvr = 千帆成交分析 意向→新客（成交口径）
# 代理关系成立，source_truth 明确区分

_AINRL_DERIVED_MAP: dict[str, str] = {
    "a_to_i": "ainrl_a_to_i_cvr",
    "i_to_n": "ainrl_i_to_n_cvr",       # proxy: deal_intent_to_new_cvr
    "n_to_r": "ainrl_n_to_r_cvr",       # proxy: repurchase_rate
    "r_to_l": "ainrl_r_to_l_cvr",
}

# AINRL absolute counts
_AINRL_STAGE_MAP: dict[str, str] = {
    "a": "ainrl_a_count",
    "i": "ainrl_i_count",
    "n": "ainrl_n_count",
    "r": "ainrl_r_count",
    "l": "ainrl_l_count",
}


def _derive_search_metrics(top_search_terms: list[dict[str, Any]]) -> dict[str, Any]:
    """
    从 top_search_terms 聚合 search_ctr / search_purchase_cvr / search_top_term 等。
    权重：按 clicks 加权均值（高流量词贡献更大）。
    """
    if not top_search_terms:
        return {}

    total_clicks = sum(t.get("clicks", 0) or 0 for t in top_search_terms)

    # Weighted avg CTR
    if total_clicks > 0:
        wctr = sum(
            (t.get("ctr", 0) or 0) * (t.get("clicks", 0) or 0)
            for t in top_search_terms
        ) / total_clicks
    else:
        wctr = median([t.get("ctr", 0) or 0 for t in top_search_terms if t.get("ctr") is not None])

    # Weighted avg purchase CVR
    total_cvr_weight = sum(t.get("clicks", 1) or 1 for t in top_search_terms if t.get("purchase_cvr") is not None)
    if total_cvr_weight > 0:
        wcvr = sum(
            (t.get("purchase_cvr", 0) or 0) * (t.get("clicks", 1) or 1)
            for t in top_search_terms
            if t.get("purchase_cvr") is not None
        ) / total_cvr_weight
    else:
        wcvr = 0.0

    # Top-1 term
    top_term = max(top_search_terms, key=lambda t: t.get("revenue", 0) or 0, default={})

    return {
        "search_ctr": round(wctr, 6),
        "search_purchase_cvr": round(wcvr, 6),
        "search_top_term": top_term.get("term", ""),
        "search_top_term_revenue": top_term.get("revenue", 0),
        "search_term_count": len(top_search_terms),
    }


def etl_to_metric_patch(etl_snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    将 xlsx_etl.run_etl() 输出转换为一个"补丁"字典，
    可安全并入 state.metric_snapshot。

    每个字段附加 _source_truth 注记（保留在 patch 中，由调用方决定是否存入 metadata）。

    Returns:
        flat dict: {metric_name: value, ...}
        （只含有值的 metric，None 全部跳过）
    """
    patch: dict[str, Any] = {}
    metrics = etl_snapshot.get("metrics", {})
    ainrl = etl_snapshot.get("ainrl", {})
    derived = ainrl.get("derived", {})
    top_search = etl_snapshot.get("top_search_terms", [])

    # 1. 直接映射
    for etl_key, metric_name in _DIRECT_MAP.items():
        val = metrics.get(etl_key)
        if val is not None and val != 0.0:
            patch[metric_name] = val

    # 2. 月度 GMV / orders
    if metrics.get("monthly_gmv"):
        patch["monthly_gmv"] = metrics["monthly_gmv"]
    if metrics.get("monthly_orders"):
        patch["monthly_orders"] = metrics["monthly_orders"]

    # 3. AINRL derived（代理指标）
    for derived_key, metric_name in _AINRL_DERIVED_MAP.items():
        val = derived.get(derived_key)
        if val is not None:
            patch[metric_name] = round(float(val), 6)

    # 4. AINRL absolute counts
    for stage_key, metric_name in _AINRL_STAGE_MAP.items():
        val = ainrl.get(stage_key)
        if val and int(val) > 0:
            patch[metric_name] = int(val)

    # 5. 搜索指标聚合
    search_metrics = _derive_search_metrics(top_search)
    patch.update(search_metrics)

    # 6. 元信息
    patch["_etl_snapshot_date"] = etl_snapshot.get("snapshot_date", "")
    patch["_etl_stage"] = etl_snapshot.get("stage", "")
    patch["_etl_source"] = "xlsx_history_truth"

    return patch


def merge_into_state_snapshot(
    state: dict[str, Any],
    etl_snapshot: dict[str, Any],
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    将 ETL patch 并入 state["metric_snapshot"]。

    Parameters:
        state: current_state 字典（会被 in-place 修改并返回）
        etl_snapshot: xlsx_etl.run_etl() 返回的 snapshot
        overwrite: False = ETL 字段仅填充 state 里的 None；
                   True = ETL 字段覆盖 state 现有值
    Returns:
        修改后的 state（in-place）
    """
    patch = etl_to_metric_patch(etl_snapshot)
    snapshot = state.setdefault("metric_snapshot", {})

    for key, val in patch.items():
        if key.startswith("_"):
            # 写入 etl_info 子字典
            state.setdefault("etl_info", {})[key.lstrip("_")] = val
            continue
        if overwrite or snapshot.get(key) is None:
            snapshot[key] = val

    # 把 ETL 搜索词 top list 写入 state（方便 search specialist）
    top_terms = etl_snapshot.get("top_search_terms", [])
    if top_terms:
        state.setdefault("etl_search_terms", top_terms)

    # 把历史 GMV 时序写入 state（方便 trend analysis）
    history = etl_snapshot.get("transaction_history", [])
    if history:
        state.setdefault("etl_transaction_history", history)

    refund_history = etl_snapshot.get("refund_history", [])
    if refund_history:
        state.setdefault("etl_refund_history", refund_history)

    return state


def build_user_state_from_etl(
    etl_snapshot: dict[str, Any],
    industry: str = "通用",
    business_model: list[str] | None = None,
) -> dict[str, Any]:
    """
    仅用 ETL 数据（无 opencli）构建一个最小 user_state，
    可直接传给 SemanticBooster / ActionRanker / HealthScorer。
    """
    from revenue_os.foundation.config import DEFAULT_THRESHOLDS

    patch = etl_to_metric_patch(etl_snapshot)
    metrics: dict[str, Any] = {
        k: v for k, v in patch.items() if not k.startswith("_")
    }

    stage = etl_snapshot.get("stage", "ramp_up")

    # 判断弱指标
    weak: list[str] = []
    cvr = metrics.get("shop_visit_to_pay_cvr", None)
    if cvr is not None and cvr < DEFAULT_THRESHOLDS.get("shop_visit_to_pay_cvr_low", 0.01):
        weak.append("shop_visit_to_pay_cvr")
    aov = metrics.get("aov", None)
    if aov is not None and aov < DEFAULT_THRESHOLDS.get("aov_low", 100):
        weak.append("aov")

    return {
        "stage": stage,
        "industry": industry,
        "business_model": business_model or ["ecommerce"],
        "metrics": metrics,
        "weak_metrics": weak,
        "primary_objective": "conversion",  # 默认，调用方可覆盖
        "inferred": {
            "industry_weights": {industry: 1.6},
        },
    }
