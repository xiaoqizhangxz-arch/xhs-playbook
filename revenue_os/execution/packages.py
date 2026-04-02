from __future__ import annotations

from typing import Any

from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import read_artifact, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso
from revenue_os.specialists.conversion_doctor import build_conversion_interventions
from revenue_os.specialists.repurchase import build_repurchase_interventions
from revenue_os.specialists.search_positioning import build_search_interventions
from revenue_os.knowledge.kb_retriever import retrieve_for_mission
from revenue_os.planning.action_ranker import rank_actions


CANONICAL_METRICS_BY_MISSION = {
    "conversion_repair": ["shop_visit_to_pay_cvr", "inquiry_to_pay_cvr", "product_click_to_pay_cvr"],
    "aov_lift": ["aov", "shop_visit_to_pay_cvr"],
    "repurchase_activation": ["repurchase_rate", "aov"],
    "search_positioning": ["search_ctr", "search_purchase_cvr"],
    "content_formula_scaling": ["shop_visit_to_pay_cvr"],
    "data_repair": ["shop_visit_to_pay_cvr"],
    "audit_only": ["shop_visit_to_pay_cvr"],
}


AOV_INTERVENTIONS = [
    {
        "id": "action__bundle_offer",
        "action_family": "bundle_offer",
        "title": "Create premium-anchored hero SKU bundle",
        "priority": 1,
        "diagnosis": "AOV is below target and needs a product path with higher basket value.",
        "owner_role": "merchant",
        "estimated_effort": "M",
        "asset_dependencies": ["bundle_pricing", "sku_page_copy"],
        "expected_metric_impact": ["aov"],
    },
    {
        "id": "action__price_anchor",
        "action_family": "price_anchor",
        "title": "Add premium comparison anchor on the product page",
        "priority": 2,
        "diagnosis": "Visitors need a higher reference point to move up the basket.",
        "owner_role": "operator",
        "estimated_effort": "S",
        "asset_dependencies": ["sku_page_copy", "comparison_visual"],
        "expected_metric_impact": ["aov"],
    },
]


CONTENT_INTERVENTIONS = [
    {
        "id": "action__content_brief",
        "action_family": "content_brief",
        "title": "Issue one narrative brief that routes into the hero SKU",
        "priority": 1,
        "diagnosis": "A working content formula exists and can be translated into a focused demand brief.",
        "owner_role": "writer",
        "estimated_effort": "S",
        "asset_dependencies": ["brief_template", "hero_sku_assets"],
        "expected_metric_impact": ["shop_visit_to_pay_cvr"],
    }
]


DATA_REPAIR_INTERVENTIONS = [
    {
        "id": "action__reconcile_metrics",
        "action_family": "data_repair",
        "title": "Reconcile extracted metrics against raw workbook extracts",
        "priority": 1,
        "diagnosis": "Planner confidence is limited by integrity and parsing drift.",
        "owner_role": "operator",
        "estimated_effort": "S",
        "asset_dependencies": ["raw_source_access", "reconcile_report"],
        "expected_metric_impact": ["shop_visit_to_pay_cvr"],
    }
]


AUDIT_INTERVENTIONS = [
    {
        "id": "action__audit_runtime",
        "action_family": "audit",
        "title": "Audit current runtime inputs and anomaly gate evidence",
        "priority": 1,
        "diagnosis": "Audit-only mode is active and no commercial experiment should be launched.",
        "owner_role": "operator",
        "estimated_effort": "S",
        "asset_dependencies": ["runtime_artifacts"],
        "expected_metric_impact": ["shop_visit_to_pay_cvr"],
    }
]


BRIEF_BLOCKS = {
    "conversion_repair": ["shop_assets", "pinned_comment", "cs_script"],
    "search_positioning": ["keyword_package", "note_angle", "term_placement"],
    "repurchase_activation": ["lifecycle_trigger", "bundle", "segment_list"],
    "aov_lift": ["bundle_pricing", "sku_page_anchor"],
    "content_formula_scaling": ["content_brief"],
    "data_repair": ["reconcile_checklist"],
    "audit_only": ["runtime_audit"],
}


def _decorate(actions: list[dict[str, Any]], evidence_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for action in actions:
        payload = dict(action)
        payload.setdefault("evidence_refs", evidence_refs[:3])
        decorated.append(payload)
    return decorated


def _actions_for_mission(mission_type: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_refs = state.get("evidence_summary", [])
    if mission_type == "conversion_repair":
        raw_actions = build_conversion_interventions(state)
    elif mission_type == "search_positioning":
        raw_actions = build_search_interventions(state)
    elif mission_type == "repurchase_activation":
        raw_actions = build_repurchase_interventions(state)
    elif mission_type == "aov_lift":
        raw_actions = _decorate(AOV_INTERVENTIONS, evidence_refs)
    elif mission_type == "content_formula_scaling":
        raw_actions = _decorate(CONTENT_INTERVENTIONS, evidence_refs)
    elif mission_type == "data_repair":
        raw_actions = _decorate(DATA_REPAIR_INTERVENTIONS, evidence_refs)
    else:
        raw_actions = _decorate(AUDIT_INTERVENTIONS, evidence_refs)

    # 用 ActionRanker 按 Utility×Relevance/Effort^0.5 重排序
    # 如果排序失败（缺少字段），fallback 到原始顺序
    bottleneck_info: dict[str, Any] | None = None
    bottleneck_metric = state.get("primary_bottleneck")
    if bottleneck_metric:
        bottleneck_info = {"primary_metric": bottleneck_metric}

    user_state_for_rank = {
        "primary_objective": state.get("brand_context", {}).get("primary_objective", "conversion"),
        "metrics": state.get("metric_snapshot", {}),
    }
    try:
        # rank_actions 期望输入是 KO形式；对 action 需要添加 triggering_metrics / applicable_action_families
        rankable = []
        for action in raw_actions:
            ko_like = dict(action)
            ko_like.setdefault("triggering_metrics", action.get("expected_metric_impact", []))
            ko_like.setdefault("applicable_action_families", [action.get("action_family", "")])
            ko_like.setdefault("score", 1.0)
            rankable.append(ko_like)
        ranked = rank_actions(rankable, user_state_for_rank, bottleneck_info)
        # 还原 priority 字段为连续整数
        for i, action in enumerate(ranked, start=1):
            action["priority"] = i
            action.pop("priority_score", None)
            action.pop("utility", None)
            action.pop("effort", None)
        return ranked
    except Exception:
        return raw_actions


def _infer_stage_from_state(state: dict[str, Any]) -> str:
    """从 metric_snapshot 中反推阶段，避免直接依赖 brand_context 字段不存在时报错。"""
    monthly_gmv = float(state.get("metric_snapshot", {}).get("monthly_gmv") or 0)
    if monthly_gmv <= 0:
        return "ramp_up"
    if monthly_gmv < 3000:
        return "cold_start"
    if monthly_gmv < 30000:
        return "ramp_up"
    if monthly_gmv < 100000:
        return "breakthrough"
    return "daily_ops"


def generate_execution_package(mission_id: str) -> dict[str, Any]:
    mission = read_artifact("mission_plan", mission_id)
    state = read_artifact("current_state", mission["state_id"])
    primary = mission["primary_mission"]
    mission_type = primary["mission_type"]
    actions = _actions_for_mission(mission_type, state)
    minimum_subset = [action["id"] for action in actions[: max(1, min(2, len(actions)))]]
    optional_extensions = [action["id"] for action in actions if action["id"] not in minimum_subset]
    dependency_graph = [
        {"action_id": action["id"], "depends_on": [] if action["id"] in minimum_subset else list(minimum_subset)}
        for action in actions
    ]
    roles = sorted({action["owner_role"] for action in actions})
    assets = sorted({asset for action in actions for asset in action.get("asset_dependencies", [])})
    success_metrics = CANONICAL_METRICS_BY_MISSION.get(mission_type, [state["primary_bottleneck"]])
    post_feedback_summary = state.get("post_feedback_summary", {})
    trigger_post_ids = list(post_feedback_summary.get("top_scale_post_ids", []))[:3]
    supporting_post_refs = [f"{state['post_feedback_report_id']}#{post_id}" for post_id in trigger_post_ids]

    package = {
        "schema_version": "1.0.0",
        "object_type": "execution_package",
        "package_id": deterministic_id("pkg", mission_id, mission_type),
        "mission_id": mission_id,
        "created_at": utc_now_iso(),
        "mission_type": mission_type,
        "title": primary["title"],
        "why_now": f"primary_bottleneck={state['primary_bottleneck']} and planner selected {mission_type}",
        "actions": actions,
        "minimum_shippable_subset": minimum_subset,
        "optional_extensions": optional_extensions,
        "dependency_graph": dependency_graph,
        "roles": roles,
        "assets": assets,
        "estimated_effort": primary.get("budget_class", state.get("recommended_intervention_budget", "M")),
        "budget_class": primary.get("budget_class", state.get("recommended_intervention_budget", "M")),
        "executable_window": "this_week",
        "success_metrics": success_metrics,
        "failure_risks": ["asset_delay", "capacity_shortfall", "weak_signal", "data_integrity_shift"],
        "brief_blocks": BRIEF_BLOCKS.get(mission_type, []),
        "kb_insights": retrieve_for_mission(
            mission_type,
            bottleneck=state.get("primary_bottleneck"),
            user_state={
                "stage": state.get("anomaly_gate", {}).get("planner_mode") or _infer_stage_from_state(state),
                "industry": state.get("brand_context", {}).get("industry", "通用"),
                "business_model": state.get("brand_context", {}).get("business_model", ["ecommerce"]),
                "weak_metrics": [
                    m["metric_name"]
                    for m in state.get("stabilized_metric_summary", [])
                    if m.get("sample_quality_status") in ("insufficient", "limited")
                ],
                "metrics": state.get("metric_snapshot", {}),
                "inferred": {"industry_weights": {}},
            },
            top_k=5,
        ),
        "trigger_post_ids": trigger_post_ids,
        "supporting_post_refs": supporting_post_refs,
        "source_of_truth": "mission_plan + specialist interventions",
        "freshness_policy": {"max_age_days": 14},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("execution_package", package)
    return package
