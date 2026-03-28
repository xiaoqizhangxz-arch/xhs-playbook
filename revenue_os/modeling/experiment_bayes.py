from __future__ import annotations

from typing import Any

from revenue_os.modeling.calibration import CALIBRATION_BUCKET


def _min_effect(metric_name: str) -> float:
    if metric_name in {"shop_visit_to_pay_cvr", "product_click_to_pay_cvr", "inquiry_to_pay_cvr", "repurchase_rate"}:
        return 0.005
    if metric_name == "refund_rate":
        return 0.01
    if metric_name == "aov":
        return 10.0
    return 1.0


def _completion_weight(completion: dict[str, Any]) -> float:
    status = completion.get("status")
    completed = len(completion.get("completed_actions", []) or [])
    blocked = len(completion.get("blocked_actions", []) or [])
    total = max(completed + blocked, 1)
    ratio = completed / total
    if status == "shipped_full":
        return 1.0
    if status == "shipped_partial":
        return round(max(0.35, 0.65 * ratio), 3)
    return 0.0


def score_experiment_bayesian(
    experiment: dict[str, Any],
    completion: dict[str, Any],
    start_state: dict[str, Any],
    end_state: dict[str, Any] | None,
    metric_deltas: dict[str, float | None],
    guardrail_deltas: dict[str, float | None],
    sample_sufficiency: float,
) -> dict[str, Any]:
    primary_metric = experiment["primary_metric"]
    primary_delta = metric_deltas.get(primary_metric)
    completion_weight = _completion_weight(completion)
    min_effect = _min_effect(primary_metric)
    learnable = bool(end_state) and completion_weight >= 0.35 and completion.get("minimum_subset_completed", False)

    if primary_delta is None:
        posterior_mean = 0.0
        stdev = min_effect * 1.5
    else:
        posterior_mean = float(primary_delta) * max(sample_sufficiency, 0.2) * max(completion_weight, 0.1)
        stdev = max(min_effect * 0.5, abs(float(primary_delta)) * (1.0 - min(sample_sufficiency, 0.95)) + min_effect * 0.5)

    prob_lift_gt_min_effect = 0.5 if not learnable else max(0.0, min(1.0, 0.5 + (posterior_mean - min_effect) / max(stdev * 4.0, 1e-6)))
    refund_delta = float(guardrail_deltas.get("refund_rate") or 0.0)
    prob_guardrail_breach = max(0.0, min(1.0, 0.5 + (refund_delta - 0.01) / 0.08))
    practical_significance_met = bool(primary_delta is not None and abs(float(primary_delta)) >= min_effect and completion_weight >= 0.5)

    if not completion.get("minimum_subset_completed", False):
        status = "incomplete_execution"
        outcome = "inconclusive"
        evidence_cap = "E0"
    elif end_state is None:
        status = "insufficient_window"
        outcome = "inconclusive"
        evidence_cap = "E0"
    else:
        status = "complete"
        if prob_guardrail_breach >= 0.65:
            outcome = "negative"
        elif prob_lift_gt_min_effect >= 0.7 and practical_significance_met:
            outcome = "positive"
        elif primary_delta is not None and float(primary_delta) <= -min_effect:
            outcome = "negative"
        elif practical_significance_met:
            outcome = "neutral"
        else:
            outcome = "inconclusive"

        if completion_weight >= 0.85 and sample_sufficiency >= 0.8 and prob_lift_gt_min_effect >= 0.75 and prob_guardrail_breach <= 0.2:
            evidence_cap = "E3"
        elif completion_weight >= 0.6 and sample_sufficiency >= 0.6:
            evidence_cap = "E2"
        elif learnable:
            evidence_cap = "E1"
        else:
            evidence_cap = "E0"

    ci80 = [round(posterior_mean - 1.28 * stdev, 6), round(posterior_mean + 1.28 * stdev, 6)]
    ci95 = [round(posterior_mean - 1.96 * stdev, 6), round(posterior_mean + 1.96 * stdev, 6)]
    return {
        "status": status,
        "outcome": outcome,
        "completion_weight": round(completion_weight, 3),
        "practical_significance_met": practical_significance_met,
        "prob_lift_gt_min_effect": round(prob_lift_gt_min_effect, 4),
        "posterior_lift_summary": {
            "metric": primary_metric,
            "posterior_mean": round(posterior_mean, 6),
            "min_effect": min_effect,
            "ci80": ci80,
            "ci95": ci95,
            "raw_delta": primary_delta,
        },
        "prob_guardrail_breach": round(prob_guardrail_breach, 4),
        "evidence_cap": evidence_cap,
        "learnable": learnable,
        "counterfactual_method": "stabilized_state_delta",
        "calibration_bucket": CALIBRATION_BUCKET,
        "statistical_baseline_comparison": {
            "raw_window_delta": primary_delta,
            "simple_statistical_baseline": 0.0,
            "stabilized_counterfactual": round(posterior_mean, 6),
            "vs_statistical_baseline_gain": round(posterior_mean - 0.0, 6),
        },
    }
