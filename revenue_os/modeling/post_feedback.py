from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any

from revenue_os.foundation.config import LE_FOND_CONTENT_START_DATE
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


def _safe_number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, f"{text}+00:00" if "T" in text and "+" not in text else text):
        try:
            return datetime.fromisoformat(candidate).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _age_days(value: str | None) -> int | None:
    parsed = _parse_dt(value)
    if parsed is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() // 86400))


def _join_historical(title: str, historical_posts: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    exact = next((post for post in historical_posts if str(post.get("title") or "").strip() == title.strip()), None)
    if exact:
        return exact, 0.9
    lowered = title.strip().lower()
    loose = next((post for post in historical_posts if lowered and lowered in str(post.get("title") or "").strip().lower()), None)
    if loose:
        return loose, 0.65
    return None, 0.35


def build_post_feedback_report(
    snapshot_id: str,
    bundle_id: str,
    first_party: dict[str, Any],
    metric_map: dict[str, dict[str, Any]],
    hero_sku: dict[str, Any],
) -> dict[str, Any]:
    creator_rows = list(first_party.get("creator_platform", {}).get("creator_note_inventory", {}).get("rows", []))
    historical_posts = list(first_party.get("content_performance", {}).get("posts", []))
    creator_rows = [row for row in creator_rows if str(row.get("published_at") or "")[:10] >= LE_FOND_CONTENT_START_DATE]
    median_views = median([_safe_number(row.get("views")) for row in creator_rows]) if creator_rows else 0.0
    median_saves = median([_safe_number(row.get("saves")) for row in creator_rows]) if creator_rows else 0.0
    global_refund_bad = metric_map.get("refund_rate", {}).get("health_status") == "bad"
    global_conversion_bad = metric_map.get("shop_visit_to_pay_cvr", {}).get("health_status") == "bad"
    global_aov_bad = metric_map.get("aov", {}).get("health_status") == "bad"

    posts: list[dict[str, Any]] = []
    class_counts = {
        "sales_driver": 0,
        "sales_assist": 0,
        "traffic_only": 0,
        "neutral": 0,
        "commercial_drag": 0,
        "refund_risk_high": 0,
        "hold_pending_sample": 0,
    }
    scale_ids: list[str] = []

    for row in creator_rows:
        title = str(row.get("title") or "").strip()
        post_id = str(row.get("note_id") or deterministic_id("post", title, row.get("published_at") or "unknown"))
        historical, join_confidence = _join_historical(title, historical_posts)
        views = _safe_number(row.get("views"))
        saves = _safe_number(row.get("saves"))
        comments = _safe_number(row.get("comments"))
        shares = _safe_number(row.get("shares"))
        engagement = saves + comments + shares
        save_rate = saves / views if views else 0.0
        traffic_diagnosis = "strong" if views >= max(600.0, median_views * 1.25) else "mixed" if views >= max(180.0, median_views * 0.7) else "weak"
        bridge_efficiency_diagnosis = "strong" if save_rate >= 0.035 else "mixed" if save_rate >= 0.012 else "weak"
        inefficiency_reasons: list[str] = []
        if join_confidence < 0.55:
            inefficiency_reasons.append("weak_commerce_join")
        if bridge_efficiency_diagnosis == "weak":
            inefficiency_reasons.append("weak_bridge_efficiency")
        if traffic_diagnosis == "weak":
            inefficiency_reasons.append("weak_distribution")
        age_days = _age_days(row.get("published_at"))
        if age_days is not None and age_days < 2:
            inefficiency_reasons.append("fresh_post_pending_sample")

        refund_risk_status = "low"
        if global_refund_bad and hero_sku.get("display_name", "").lower()[:4] in title.lower():
            refund_risk_status = "high"
        elif global_refund_bad and traffic_diagnosis == "strong":
            refund_risk_status = "medium"

        if age_days is not None and age_days < 2:
            recommendation_class = "hold_pending_sample"
            commerce_judgment = "insufficient_sample"
            recommended_action = "Hold for another capture window before scaling or suppressing."
        elif refund_risk_status == "high":
            recommendation_class = "refund_risk_high"
            commerce_judgment = "risk_to_commerce"
            recommended_action = "Keep distribution but review bridge copy, expectation setting, and after-sale handling."
        elif traffic_diagnosis == "strong" and bridge_efficiency_diagnosis == "strong" and join_confidence >= 0.75 and not global_conversion_bad:
            recommendation_class = "sales_driver"
            commerce_judgment = "strong_commerce_support"
            recommended_action = "Scale this angle, keep the bridge to hero SKU explicit, and reuse the opening hook."
        elif traffic_diagnosis == "strong" and bridge_efficiency_diagnosis in {"strong", "mixed"} and join_confidence >= 0.65:
            recommendation_class = "sales_assist"
            commerce_judgment = "assistive_commerce_support"
            recommended_action = "Reuse this angle as supporting content and tighten CTA or pinned comment bridge."
        elif traffic_diagnosis == "strong" and join_confidence < 0.55:
            recommendation_class = "traffic_only"
            commerce_judgment = "creator_only_signal"
            recommended_action = "Do not scale blindly. Add stronger commerce bridge before using as a template."
        elif traffic_diagnosis == "weak" and bridge_efficiency_diagnosis == "weak":
            recommendation_class = "commercial_drag"
            commerce_judgment = "weak_commercial_signal"
            recommended_action = "Suppress this angle next week unless it serves a specific lifecycle purpose."
        else:
            recommendation_class = "neutral"
            commerce_judgment = "mixed_signal"
            recommended_action = "Hold, gather one more window, and compare against stronger notes before changing the formula."

        if recommendation_class in {"sales_driver", "sales_assist"}:
            scale_ids.append(post_id)
        class_counts[recommendation_class] += 1

        historical_views = _safe_number((historical or {}).get("views"))
        observed_direction_14d = "up" if views >= max(historical_views, median_views) else "down"
        posts.append(
            {
                "post_id": post_id,
                "post_date": str(row.get("published_at") or "")[:10],
                "join_confidence": round(join_confidence, 2),
                "traffic_diagnosis": traffic_diagnosis,
                "bridge_efficiency_diagnosis": bridge_efficiency_diagnosis,
                "commerce_judgment": commerce_judgment,
                "refund_risk_status": refund_risk_status,
                "inefficiency_reasons": inefficiency_reasons,
                "recommended_action": recommended_action,
                "recommendation_class": recommendation_class,
                "creator_signal_summary": {
                    "title": title,
                    "views": views,
                    "saves": saves,
                    "comments": comments,
                    "shares": shares,
                    "engagement_actions": engagement,
                    "type": str(row.get("type") or ""),
                },
                "qianfan_signal_summary": {
                    "commerce_truth_available": False,
                    "global_conversion_bad": global_conversion_bad,
                    "global_aov_bad": global_aov_bad,
                    "global_refund_bad": global_refund_bad,
                },
                "supporting_metric_refs": [
                    "metric__creator_cover_ctr_7d",
                    "metric__recent_note_median_views",
                    "metric__shop_visit_to_pay_cvr",
                ],
                "observed_direction_14d": observed_direction_14d,
                "age_days": age_days,
            }
        )

    posts.sort(key=lambda item: (item["recommendation_class"] not in {"sales_driver", "sales_assist"}, -item["creator_signal_summary"]["views"]))
    report = {
        "schema_version": "1.0.0",
        "object_type": "post_feedback_report",
        "report_id": deterministic_id("post_feedback", snapshot_id, bundle_id),
        "snapshot_id": snapshot_id,
        "bundle_id": bundle_id,
        "created_at": utc_now_iso(),
        "summary": {
            "post_count": len(posts),
            "scale_candidate_count": class_counts["sales_driver"] + class_counts["sales_assist"],
            "weak_join_count": sum(1 for item in posts if item["join_confidence"] < 0.55),
            "traffic_only_count": class_counts["traffic_only"],
            "top_scale_post_ids": scale_ids[:5],
        },
        "posts": posts,
        "source_of_truth": "creator freshness + historical content truth + qianfan truth policy guardrails",
        "freshness_policy": {"max_age_days": 7},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("post_feedback_report", report)
    return report
