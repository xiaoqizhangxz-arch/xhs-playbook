from __future__ import annotations

import math
from statistics import mean
from typing import Any

from revenue_os.foundation.config import DEFAULT_THRESHOLDS
from revenue_os.modeling.calibration import calibration_ref


STABILIZER_VERSION = "p0.eb.v1"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(float(value), low), high)


def _safe_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_truth_policy(name: str, metadata: dict[str, Any] | None) -> str:
    metadata = metadata or {}
    if metadata.get("source_truth"):
        return str(metadata["source_truth"])
    if name.startswith("creator_") or name.startswith("recent_note_"):
        return "creator_freshness_content_truth"
    if name.startswith("search_"):
        return "qianfan_search_truth"
    if name.startswith("deal_") or name.startswith("aipl_"):
        return "qianfan_population_truth"
    return "qianfan_commerce_truth"


def _peer_family(name: str) -> str:
    if "freshness_days" in name:
        return "freshness_window"
    if name == "refund_rate":
        return "refund_rate_window"
    if name in {"repurchase_rate", "deal_new_to_returning_cvr", "aipl_new_to_returning_cvr"}:
        return "retention_rate_window"
    if name.startswith("search_"):
        return "search_rate_window"
    if name.startswith("creator_") and any(token in name for token in ("ctr", "rate")):
        return "creator_rate_window"
    if name.startswith("recent_note_") and "median_" in name:
        return "no_pool_continuous"
    if name in {"shop_visit_to_pay_cvr", "product_click_to_pay_cvr", "inquiry_to_pay_cvr", "deal_awareness_to_intent_cvr", "deal_intent_to_new_cvr", "aipl_interest_to_new_cvr"}:
        return "conversion_rate_window"
    if name == "aov":
        return "no_pool_continuous"
    if name.startswith("creator_") or name.startswith("recent_note_"):
        return "creator_count_window"
    return "no_pool_continuous"


def _threshold_for_metric(name: str) -> tuple[float | None, float | None]:
    floor_map = {
        "shop_visit_to_pay_cvr": DEFAULT_THRESHOLDS["shop_visit_to_pay_cvr_low"],
        "product_click_to_pay_cvr": DEFAULT_THRESHOLDS["product_click_to_pay_cvr_low"],
        "aov": DEFAULT_THRESHOLDS["aov_low"],
        "inquiry_to_pay_cvr": DEFAULT_THRESHOLDS["inquiry_to_pay_cvr_low"],
        "refund_rate": None,
        "repurchase_rate": 0.08,
        "search_ctr": DEFAULT_THRESHOLDS["search_opportunity_ctr"],
        "creator_cover_ctr_7d": 0.06,
        "creator_completion_rate_7d": 0.20,
        "recent_note_median_views": 300.0,
    }
    ceiling_map = {
        "refund_rate": DEFAULT_THRESHOLDS["refund_rate_high"],
        "creator_unfollows_7d": 20.0,
        "creator_note_data_freshness_days": DEFAULT_THRESHOLDS["creator_note_manager_stale_days"],
        "creator_home_data_freshness_days": DEFAULT_THRESHOLDS["creator_home_stale_days"],
    }
    return floor_map.get(name), ceiling_map.get(name)


def _ci_normal(mean_value: float, stdev: float, low: float | None = None, high: float | None = None, z: float = 1.28) -> list[float]:
    lo = mean_value - z * stdev
    hi = mean_value + z * stdev
    if low is not None:
        lo = max(low, lo)
    if high is not None:
        hi = min(high, hi)
    return [round(lo, 6), round(hi, 6)]


def _probability_above(mean_value: float, stdev: float, threshold: float) -> float:
    if stdev <= 1e-9:
        return 1.0 if mean_value > threshold else 0.0
    z = (threshold - mean_value) / stdev
    return round(_clamp(0.5 * (1.0 - math.erf(z / math.sqrt(2)))), 4)


def _beta_binomial_estimate(raw_value: float | None, numerator: float | None, denominator: float | None, pool_mean: float | None) -> tuple[float | None, list[float] | None, list[float] | None, float | None]:
    if numerator is None or denominator is None or denominator <= 0:
        return raw_value, None, None, None
    prior_strength = 8.0 if pool_mean is not None else 2.0
    prior_mean = pool_mean if pool_mean is not None else raw_value if raw_value is not None else 0.5
    alpha = max(0.5, prior_mean * prior_strength) + numerator
    beta = max(0.5, (1 - prior_mean) * prior_strength) + max(0.0, denominator - numerator)
    total = alpha + beta
    posterior = alpha / total if total else raw_value
    variance = (alpha * beta) / (((total ** 2) * (total + 1))) if total > 1 else 0.0
    stdev = math.sqrt(max(variance, 0.0))
    return posterior, _ci_normal(posterior, stdev, 0.0, 1.0, z=1.28), _ci_normal(posterior, stdev, 0.0, 1.0, z=1.96), float(denominator)


def _shrunk_continuous(raw_value: float | None, denominator: float | None, pool_mean: float | None) -> tuple[float | None, list[float] | None, list[float] | None, float | None]:
    if raw_value is None:
        return None, None, None, None
    effective_n = max(float(denominator or 0.0), 1.0)
    prior_strength = min(12.0, max(2.0, 10.0 / math.sqrt(effective_n)))
    target_mean = pool_mean if pool_mean is not None else raw_value
    posterior = ((raw_value * effective_n) + (target_mean * prior_strength)) / (effective_n + prior_strength)
    relative_noise = max(abs(raw_value), 1.0) / max(math.sqrt(effective_n), 1.0)
    stdev = max(1e-6, 0.35 * relative_noise)
    return posterior, _ci_normal(posterior, stdev, z=1.28), _ci_normal(posterior, stdev, z=1.96), effective_n


def apply_metric_stabilization(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family_values: dict[str, list[float]] = {}
    for metric in metrics:
        raw = _safe_number(metric.get("value"))
        if raw is None:
            continue
        family_values.setdefault(_peer_family(metric["name"]), []).append(raw)

    stabilized: list[dict[str, Any]] = []
    for metric in metrics:
        payload = dict(metric)
        name = payload["name"]
        raw_value = _safe_number(payload.get("value"))
        numerator = _safe_number(payload.get("numerator_value"))
        denominator = _safe_number(payload.get("denominator_value"))
        peer_family = _peer_family(name)
        pool_candidates = [] if peer_family == "no_pool_continuous" else family_values.get(peer_family, [])
        pool_mean = mean(pool_candidates) if len(pool_candidates) >= 2 else None
        floor, ceiling = _threshold_for_metric(name)
        alias_confidence = float((payload.get("metadata") or {}).get("alias_confidence", 1.0) or 1.0)

        if raw_value is not None and denominator is not None and denominator > 1 and 0.0 <= raw_value <= 1.0:
            estimator_family = "beta_binomial"
            posterior_mean, ci80, ci95, effective_n = _beta_binomial_estimate(raw_value, numerator, denominator, pool_mean)
            stdev = ((ci95[1] - ci95[0]) / 3.92) if ci95 else 0.0
        else:
            estimator_family = "normal_normal"
            posterior_mean, ci80, ci95, effective_n = _shrunk_continuous(raw_value, denominator, pool_mean)
            stdev = ((ci95[1] - ci95[0]) / 3.92) if ci95 else 0.0

        if alias_confidence < 0.6:
            estimator_family = "raw_fallback_alias_instability"
            posterior_mean = raw_value
            ci80 = None
            ci95 = None
            effective_n = denominator if denominator is not None else 1.0
            stdev = 0.0

        sample_quality_status = "strong"
        if effective_n is None or effective_n < DEFAULT_THRESHOLDS["sample_floor_orders"]:
            sample_quality_status = "insufficient"
        elif effective_n < DEFAULT_THRESHOLDS["min_orders_for_confidence"]:
            sample_quality_status = "limited"
        if alias_confidence < 0.6:
            sample_quality_status = "alias_unstable"

        payload.update(
            {
                "raw_value": raw_value,
                "estimated_value": None if posterior_mean is None else round(float(posterior_mean), 6),
                "posterior_mean": None if posterior_mean is None else round(float(posterior_mean), 6),
                "ci80": ci80,
                "ci95": ci95,
                "effective_n": None if effective_n is None else round(float(effective_n), 3),
                "prob_above_target": None
                if floor is None or posterior_mean is None
                else _probability_above(float(posterior_mean), stdev, float(floor)),
                "prob_below_floor": None
                if ceiling is None or posterior_mean is None
                else _probability_above(float(ceiling), stdev, float(posterior_mean)),
                "estimator_family": estimator_family,
                "peer_pool_used": peer_family if pool_mean is not None else "no_pool_fallback",
                "sample_quality_status": sample_quality_status,
                "truth_policy": _metric_truth_policy(name, payload.get("metadata")),
                "stabilizer_version": STABILIZER_VERSION,
                "calibration_artifact_ref": calibration_ref("metric_stabilizer"),
            }
        )
        stabilized.append(payload)
    return stabilized
