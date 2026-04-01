from __future__ import annotations

from statistics import median
from typing import Any

from revenue_os.foundation.config import DEFAULT_THRESHOLDS
from revenue_os.foundation.ids import deterministic_id, readable_id
from revenue_os.foundation.io import read_artifact, write_artifact
from revenue_os.foundation.time_utils import iso_week_label, utc_now_iso
from revenue_os.modeling.post_feedback import build_post_feedback_report


PRIMARY_GOALS = [
    "repair_purchase_conversion",
    "lift_aov",
    "activate_repurchase",
]


def infer_stage(monthly_gmv: float, monthly_orders: int = 0) -> str:
    """根据月GMV和订单量推断经营阶段"""
    if monthly_gmv < 3000 or monthly_orders < 10:
        return "cold_start"
    elif monthly_gmv < 30000:
        return "ramp_up"
    elif monthly_gmv < 100000:
        return "breakthrough"
    else:
        return "daily_ops"


def _metric_map(snapshot_id: str) -> dict[str, dict[str, Any]]:
    registry = read_artifact("metric_registry", deterministic_id("registry", snapshot_id, "metrics"))
    return {metric["name"]: metric for metric in registry.get("metrics", [])}


def _entity_map(snapshot_id: str) -> dict[str, list[dict[str, Any]]]:
    registry = read_artifact("entity_registry", deterministic_id("registry", snapshot_id, "entity"))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entity in registry.get("entities", []):
        grouped.setdefault(entity.get("entity_type", "unknown"), []).append(entity)
    return grouped


def _select_hero_sku(sku_rows: list[dict[str, Any]], sku_entities: list[dict[str, Any]]) -> dict[str, Any]:
    hero_row = max(
        sku_rows,
        key=lambda row: float(row.get("total_revenue", 0) or 0),
        default={},
    )
    display_name = str(hero_row.get("name") or "unknown")
    alias_set = {display_name, str(hero_row.get("canonical_name") or "")}
    entity = next(
        (
            item
            for item in sku_entities
            if item.get("display_name") in alias_set
            or item.get("canonical_name") in alias_set
            or alias_set.intersection(set(item.get("aliases", [])))
        ),
        None,
    )
    entity_id = entity.get("entity_id") if entity else readable_id("sku", display_name)
    canonical_name = entity.get("canonical_name") if entity else display_name
    total_visitors = float(hero_row.get("total_visitors", 0) or 0)
    first_buy_cvr = float(hero_row.get("avg_cvr", 0) or 0)
    cart_to_buy = float(hero_row.get("cart_to_buy", 0) or 0)
    return {
        "entity_id": entity_id,
        "display_name": entity.get("display_name", display_name) if entity else display_name,
        "canonical_name": canonical_name,
        "traffic": "strong" if total_visitors >= 200 else ("moderate" if total_visitors >= 80 else "weak"),
        "first_buy_cvr": "weak" if first_buy_cvr < DEFAULT_THRESHOLDS["hero_sku_first_buy_cvr_low"] else "healthy",
        "refund_risk": "high" if cart_to_buy < 0.12 else ("medium" if cart_to_buy < 0.20 else "low"),
        "total_revenue": float(hero_row.get("total_revenue", 0) or 0),
        "total_visitors": total_visitors,
    }


def _rank_goals(metric_map: dict[str, dict[str, Any]]) -> list[str]:
    goals = list(PRIMARY_GOALS)
    conversion_bad = metric_map.get("shop_visit_to_pay_cvr", {}).get("health_status") == "bad"
    aov_bad = metric_map.get("aov", {}).get("health_status") == "bad"
    refund_bad = metric_map.get("refund_rate", {}).get("health_status") == "bad"
    if aov_bad and not conversion_bad:
        goals = ["lift_aov", "repair_purchase_conversion", "activate_repurchase"]
    if refund_bad:
        goals = ["repair_purchase_conversion", "lift_aov", "activate_repurchase"]
    return goals


def _primary_bottleneck(metric_map: dict[str, dict[str, Any]]) -> str:
    priority = [
        "shop_visit_to_pay_cvr",
        "inquiry_to_pay_cvr",
        "deal_intent_to_new_cvr",
        "deal_new_to_returning_cvr",
        "aov",
        "refund_rate",
        "repurchase_rate",
    ]
    for metric_name in priority:
        if metric_map.get(metric_name, {}).get("health_status") == "bad":
            return metric_name
    return "shop_visit_to_pay_cvr"


def _stabilized_metric_summary(metric_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for name in [
        "shop_visit_to_pay_cvr",
        "aov",
        "refund_rate",
        "repurchase_rate",
        "creator_cover_ctr_7d",
        "recent_note_median_views",
    ]:
        metric = metric_map.get(name)
        if not metric:
            continue
        summary.append(
            {
                "metric_name": name,
                "raw_value": metric.get("raw_value", metric.get("value")),
                "estimated_value": metric.get("estimated_value", metric.get("value")),
                "prob_above_target": metric.get("prob_above_target"),
                "prob_below_floor": metric.get("prob_below_floor"),
                "sample_quality_status": metric.get("sample_quality_status", "unknown"),
                "estimator_family": metric.get("estimator_family", "raw_only"),
            }
        )
    return summary


def _creator_content_status(first_party: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    historical = first_party.get("content_performance", {})
    creator = first_party.get("creator_platform", {})
    note_inventory = creator.get("creator_note_inventory", {})
    events_board = creator.get("creator_events_board", {})
    inspiration_board = creator.get("creator_inspiration_board", {})
    visual = creator.get("visual_signals", {})
    home_visual = visual.get("creator_home", {})
    note_visual = visual.get("creator_note_manager", {})
    events_visual = visual.get("creator_events", {})
    inspiration_visual = visual.get("creator_inspiration", {})
    rows = note_inventory.get("rows", [])
    account_panel = creator.get("creator_account_panel", {})
    freshness = creator.get("freshness", {})
    historical_posts = historical.get("posts", [])

    historical_avg_views = median([float(post.get("views", 0) or 0) for post in historical_posts]) if historical_posts else 0.0
    recent_median_views = median([float(row.get("views", 0) or 0) for row in rows]) if rows else 0.0
    recent_median_saves = median([float(row.get("saves", 0) or 0) for row in rows]) if rows else 0.0
    recent_top_notes = [
        {"title": row.get("title", ""), "views": float(row.get("views", 0) or 0), "saves": float(row.get("saves", 0) or 0)}
        for row in rows[:3]
    ]

    if freshness.get("creator_home_days") is None and freshness.get("creator_note_manager_days") is None:
        creator_freshness = "missing"
    elif (freshness.get("creator_home_days") or 999) > DEFAULT_THRESHOLDS["creator_home_stale_days"] or (freshness.get("creator_note_manager_days") or 999) > DEFAULT_THRESHOLDS["creator_note_manager_stale_days"]:
        creator_freshness = "stale"
    else:
        creator_freshness = "fresh"

    if recent_median_views >= max(historical_avg_views * 1.1, 600):
        recent_note_output = "strong"
    elif recent_median_views >= max(historical_avg_views * 0.7, 250):
        recent_note_output = "mixed"
    elif rows:
        recent_note_output = "weak"
    else:
        recent_note_output = "missing"

    account_signal_score = sum(
        float(value or 0)
        for value in (
            account_panel.get("cover_ctr"),
            account_panel.get("completion_rate"),
            account_panel.get("homepage_visitors"),
            account_panel.get("engagement_actions"),
        )
    )
    if creator_freshness == "missing":
        creator_account_signal = "missing"
    elif account_signal_score >= 180:
        creator_account_signal = "strong"
    elif account_signal_score >= 60:
        creator_account_signal = "mixed"
    else:
        creator_account_signal = "weak"

    if not rows or not historical_posts:
        alignment = "unknown"
    elif recent_median_views >= historical_avg_views * 0.9 and recent_median_saves >= 5:
        alignment = "aligned"
    elif recent_median_views < historical_avg_views * 0.6:
        alignment = "diverging"
    else:
        alignment = "mixed"

    event_count = float(events_board.get("active_event_count", 0) or 0)
    event_soon = float(events_board.get("events_start_within_7d", 0) or 0)
    inspiration_topic_count = float(inspiration_board.get("topic_count", 0) or 0)
    high_heat_topic_count = float(inspiration_board.get("high_heat_topic_count", 0) or 0)

    if freshness.get("creator_events_days") is None:
        creator_event_signal = "missing"
    elif (freshness.get("creator_events_days") or 999) > 35:
        creator_event_signal = "weak"
    elif event_count >= 5 or event_soon >= 2:
        creator_event_signal = "strong"
    elif event_count >= 2:
        creator_event_signal = "mixed"
    else:
        creator_event_signal = "weak"

    if freshness.get("creator_inspiration_days") is None:
        creator_inspiration_signal = "missing"
    elif (freshness.get("creator_inspiration_days") or 999) > 35:
        creator_inspiration_signal = "weak"
    elif inspiration_topic_count >= 10 and high_heat_topic_count >= 1:
        creator_inspiration_signal = "strong"
    elif inspiration_topic_count >= 4:
        creator_inspiration_signal = "mixed"
    else:
        creator_inspiration_signal = "weak"

    content_status = {
        "narrative_video": "working" if float(historical.get("winning_formula", {}).get("video_pct", 0) or 0) >= 0.5 else ("mixed" if historical_posts else "weak"),
        "generic_product_posts": "weakening" if historical_posts else "unknown",
        "best_weekday": str(historical.get("winning_formula", {}).get("best_weekday", "unknown")),
        "best_hour": str(historical.get("winning_formula", {}).get("best_hour", "unknown")),
        "avg_ctr": historical.get("avg_ctr"),
        "avg_engagement": historical.get("avg_engagement"),
        "recent_note_output": recent_note_output,
        "creator_account_signal": creator_account_signal,
        "creator_freshness": creator_freshness,
        "creator_event_signal": creator_event_signal,
        "creator_inspiration_signal": creator_inspiration_signal,
        "recent_top_notes": recent_top_notes,
        "event_focus_titles": [str(item).strip() for item in (events_board.get("top_event_titles") or [])[:5] if str(item).strip()],
        "inspiration_top_topics": [str(item).strip() for item in (inspiration_board.get("top_topics") or [])[:5] if str(item).strip()],
    }
    creator_signal_summary = {
        "recent_note_count": len(rows),
        "recent_note_median_views": float(recent_median_views or 0),
        "recent_note_median_saves": float(recent_median_saves or 0),
        "creator_home_freshness_days": freshness.get("creator_home_days"),
        "creator_note_manager_freshness_days": freshness.get("creator_note_manager_days"),
        "creator_events_freshness_days": freshness.get("creator_events_days"),
        "creator_inspiration_freshness_days": freshness.get("creator_inspiration_days"),
        "account_signal": creator_account_signal,
        "active_event_count": event_count,
        "inspiration_topic_count": inspiration_topic_count,
        "visual_chart_nodes": (
            int(home_visual.get("chart_node_count", 0) or 0)
            + int(note_visual.get("chart_node_count", 0) or 0)
            + int(events_visual.get("chart_node_count", 0) or 0)
            + int(inspiration_visual.get("chart_node_count", 0) or 0)
        ),
        "visual_numeric_signal_count": (
            len(home_visual.get("numeric_text_samples", []) or [])
            + len(note_visual.get("numeric_text_samples", []) or [])
            + len(events_visual.get("numeric_text_samples", []) or [])
            + len(inspiration_visual.get("numeric_text_samples", []) or [])
        ),
    }
    return content_status, creator_signal_summary, alignment


def _search_opportunities(first_party: dict[str, Any], keyword_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    term_to_entity = {}
    for entity in keyword_entities:
        term_to_entity[entity.get("display_name", "")] = entity
        term_to_entity[entity.get("canonical_name", "")] = entity
        for alias in entity.get("aliases", []):
            term_to_entity[alias] = entity
    opportunities: list[dict[str, Any]] = []
    for item in first_party.get("search_terms", {}).get("top_terms", [])[:5]:
        term = str(item.get("term") or "unknown")
        entity = term_to_entity.get(term)
        opportunities.append(
            {
                "keyword_id": entity.get("entity_id") if entity else readable_id("keyword", term),
                "term": term,
                "ctr": item.get("click_rate"),
                "purchase_cvr": item.get("purchase_cvr"),
                "traffic": item.get("search_count"),
                "confidence": entity.get("confidence", 0.6) if entity else 0.5,
            }
        )
    return opportunities


def _confidence_breakdown(metric_map: dict[str, dict[str, Any]], anomaly: dict[str, Any], creator_freshness: str, alignment: str) -> dict[str, float]:
    completeness = float(anomaly.get("source_completeness", 0) or 0)
    orders = float(metric_map.get("shop_visit_to_pay_cvr", {}).get("denominator_value", 0) or 0)
    sample_size = min(1.0, orders / max(DEFAULT_THRESHOLDS["min_orders_for_confidence"], 1))
    bad_metrics = sum(1 for metric in metric_map.values() if metric.get("health_status") == "bad")
    tracked = max(len(metric_map), 1)
    signal_agreement = max(0.3, round(1.0 - (bad_metrics / tracked), 2))
    if creator_freshness == "stale":
        signal_agreement = min(signal_agreement, 0.7)
    if creator_freshness == "missing":
        signal_agreement = min(signal_agreement, 0.55)
    if alignment == "aligned":
        signal_agreement = min(1.0, signal_agreement + 0.1)
    elif alignment == "diverging":
        signal_agreement = max(0.3, signal_agreement - 0.15)
    return {
        "data_quality": round(completeness, 2),
        "sample_size": round(sample_size, 2),
        "signal_agreement": round(signal_agreement if anomaly.get("status") != "red" else min(signal_agreement, 0.45), 2),
    }


def _recommended_budget(primary_bottleneck: str, anomaly: dict[str, Any], confidence_breakdown: dict[str, float], creator_signal_summary: dict[str, Any]) -> str:
    if anomaly.get("planner_mode") == "audit_only":
        return "S"
    if primary_bottleneck in {"shop_visit_to_pay_cvr", "inquiry_to_pay_cvr", "deal_intent_to_new_cvr"} and confidence_breakdown["sample_size"] >= 0.8:
        return "L"
    if primary_bottleneck in {"aov", "repurchase_rate"}:
        return "M"
    if creator_signal_summary.get("recent_note_count", 0) >= 8:
        return "M"
    return "S"


def _structured_evidence(
    metric_map: dict[str, dict[str, Any]],
    hero_sku: dict[str, Any],
    content_status: dict[str, Any],
    search_opportunities: list[dict[str, Any]],
    anomaly: dict[str, Any],
    creator_signal_summary: dict[str, Any],
    alignment: str,
    stabilized_metric_summary: list[dict[str, Any]],
    post_feedback_report: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for code in [
        "shop_visit_to_pay_cvr",
        "aov",
        "refund_rate",
        "repurchase_rate",
        "deal_awareness_to_intent_cvr",
        "deal_intent_to_new_cvr",
        "deal_new_to_returning_cvr",
        "deal_returning_churn_rate",
        "aipl_interest_to_new_cvr",
        "aipl_new_to_returning_cvr",
        "service_after_sale_surface_rows",
        "fulfillment_logistics_surface_rows",
        "creator_cover_ctr_7d",
        "recent_note_median_views",
        "creator_visual_chart_nodes",
        "creator_visual_numeric_signals",
        "creator_event_active_count_mtd",
        "creator_event_start_within_7d_count",
        "creator_inspiration_topic_count_mtd",
        "creator_inspiration_high_heat_topic_count",
        "creator_events_data_freshness_days",
        "creator_inspiration_data_freshness_days",
    ]:
        metric = metric_map.get(code)
        if not metric:
            continue
        evidence.append(
            {
                "code": f"metric::{code}",
                "source_type": "metric_registry",
                "ref": code,
                "message": f"{code}={metric.get('value')}",
                "confidence": 0.9 if metric.get("planner_eligibility") else 0.6,
                "freshness": str(metric.get("window_policy") or "current_window"),
            }
        )
    evidence.append(
        {
            "code": "hero_sku",
            "source_type": "entity_registry",
            "ref": hero_sku["entity_id"],
            "message": f"hero_sku={hero_sku['display_name']}",
            "confidence": 0.85,
            "freshness": "current_window",
        }
    )
    evidence.append(
        {
            "code": "content_formula",
            "source_type": "content_performance",
            "ref": content_status["narrative_video"],
            "message": f"narrative_video={content_status['narrative_video']} recent_output={content_status['recent_note_output']}",
            "confidence": 0.72,
            "freshness": "rolling_posts_window",
        }
    )
    evidence.append(
        {
            "code": "creator_alignment",
            "source_type": "creator_platform",
            "ref": alignment,
            "message": f"creator_alignment={alignment} recent_note_count={creator_signal_summary['recent_note_count']}",
            "confidence": 0.75,
            "freshness": "creator_recent_window",
        }
    )
    if search_opportunities:
        top_term = search_opportunities[0]
        evidence.append(
            {
                "code": "search_top_term",
                "source_type": "search_terms",
                "ref": top_term["keyword_id"],
                "message": f"top_search_term={top_term['term']}",
                "confidence": top_term.get("confidence", 0.6),
                "freshness": "current_window",
            }
        )
    if anomaly.get("issues"):
        evidence.append(
            {
                "code": "anomaly_gate",
                "source_type": "anomaly_gate_result",
                "ref": anomaly.get("status", "warning"),
                "message": f"planner_mode={anomaly.get('planner_mode')} acquisition_readiness={anomaly.get('acquisition_readiness_status')}",
                "confidence": 1.0,
                "freshness": "current_run",
            }
        )
    for item in stabilized_metric_summary[:3]:
        evidence.append(
            {
                "code": f"stabilized::{item['metric_name']}",
                "source_type": "metric_registry",
                "ref": item["metric_name"],
                "message": f"estimated={item['estimated_value']} sample_quality={item['sample_quality_status']}",
                "confidence": 0.7 if item["sample_quality_status"] == "strong" else 0.55,
                "freshness": "current_window",
            }
        )
    if post_feedback_report.get("posts"):
        evidence.append(
            {
                "code": "post_feedback",
                "source_type": "post_feedback_report",
                "ref": post_feedback_report["report_id"],
                "message": f"scale_candidates={post_feedback_report['summary']['scale_candidate_count']} traffic_only={post_feedback_report['summary']['traffic_only_count']}",
                "confidence": 0.6,
                "freshness": "current_window",
            }
        )
    return evidence


def build_current_state(snapshot_id: str, bundle_id: str) -> dict[str, Any]:
    first_party = read_artifact("normalized_first_party", snapshot_id)
    brand_truth = read_artifact("normalized_brand_truth", snapshot_id)
    anomaly = read_artifact("anomaly_gate_result", deterministic_id("anomaly", snapshot_id))
    metric_map = _metric_map(snapshot_id)
    entities = _entity_map(snapshot_id)

    latest_month = first_party.get("monthly_business_health", {}).get("latest", {})
    hero_sku = _select_hero_sku(first_party.get("sku_performance", {}).get("rows", []), entities.get("sku", []))
    content_status, creator_signal_summary, creator_vs_historical_alignment = _creator_content_status(first_party)
    search_opportunities = _search_opportunities(first_party, entities.get("keyword", []))
    business_goal_ranked = _rank_goals(metric_map)
    primary_bottleneck = _primary_bottleneck(metric_map)
    confidence_breakdown = _confidence_breakdown(metric_map, anomaly, content_status["creator_freshness"], creator_vs_historical_alignment)
    confidence = round(sum(confidence_breakdown.values()) / 3, 2)
    recommended_budget = _recommended_budget(primary_bottleneck, anomaly, confidence_breakdown, creator_signal_summary)
    post_feedback_report = build_post_feedback_report(snapshot_id, bundle_id, first_party, metric_map, hero_sku)
    stabilized_metric_summary = _stabilized_metric_summary(metric_map)
    evidence_summary = _structured_evidence(
        metric_map,
        hero_sku,
        content_status,
        search_opportunities,
        anomaly,
        creator_signal_summary,
        creator_vs_historical_alignment,
        stabilized_metric_summary,
        post_feedback_report,
    )
    hero_story = brand_truth.get("hero_products", [])

    state = {
        "schema_version": "1.0.0",
        "object_type": "current_state",
        "state_id": deterministic_id("state", snapshot_id, bundle_id),
        "snapshot_id": snapshot_id,
        "bundle_id": bundle_id,
        "created_at": utc_now_iso(),
        "week": iso_week_label(),
        "business_goal_ranked": business_goal_ranked,
        "primary_bottleneck": primary_bottleneck,
        "hero_sku": {
            "entity_id": hero_sku["entity_id"],
            "display_name": hero_sku["display_name"],
            "canonical_name": hero_sku["canonical_name"],
        },
        "hero_sku_status": {
            "traffic": hero_sku["traffic"],
            "first_buy_cvr": hero_sku["first_buy_cvr"],
            "refund_risk": hero_sku["refund_risk"],
            "total_revenue": hero_sku["total_revenue"],
            "total_visitors": hero_sku["total_visitors"],
        },
        "content_status": content_status,
        "creator_signal_summary": creator_signal_summary,
        "creator_vs_historical_alignment": creator_vs_historical_alignment,
        "search_opportunities": search_opportunities,
        "data_quality": {
            "mtd_partial_month": str(latest_month.get("_month", "")).endswith("03月"),
            "live_fields_missing": True,
            "source_completeness": anomaly.get("source_completeness", 0),
            "missing_families": anomaly.get("missing_families", []),
            "reconcile_status": first_party.get("reconcile", {}).get("status", "unknown"),
        },
        "evidence_summary": evidence_summary,
        "stabilized_metric_summary": stabilized_metric_summary,
        "post_feedback_report_id": post_feedback_report["report_id"],
        "post_feedback_summary": post_feedback_report["summary"],
        "confidence": confidence,
        "confidence_breakdown": confidence_breakdown,
        "freshness": latest_month.get("_month", utc_now_iso()[:10]),
        "recommended_intervention_budget": recommended_budget,
        "anomaly_gate": {
            "status": anomaly.get("status"),
            "planner_mode": anomaly.get("planner_mode"),
            "issues": anomaly.get("issues", []),
            "acquisition_readiness_status": anomaly.get("acquisition_readiness_status"),
            "source_freshness_refs": anomaly.get("source_freshness_refs", []),
        },
        "planner_readiness": anomaly.get("planner_mode") != "audit_only",
        "metric_snapshot": {name: metric.get("value") for name, metric in metric_map.items()},
        "brand_context": {
            "hero_products": hero_story[:3],
            "priority_themes": brand_truth.get("priority_themes", []),
        },
        "source_of_truth": "normalized first-party + benchmark + brand truth + anomaly gate",
        "freshness_policy": {"max_age_days": 7},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("current_state", state)
    return state
