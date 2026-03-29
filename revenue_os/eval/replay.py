from __future__ import annotations

import os
from typing import Any

from revenue_os.foundation.config import REPLAY_THRESHOLDS
from revenue_os.foundation.contracts import validate_contract_document
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import list_artifacts, read_artifact, read_json, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso
from revenue_os.modeling.baselines import simple_statistical_baseline
from revenue_os.planning.planner import score_missions_for_state


BUDGET_ORDER = {"S": 1, "M": 2, "L": 3}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _latest_paths(object_type: str, limit: int) -> list[Any]:
    paths = list_artifacts(object_type)
    if limit <= 0 or len(paths) <= limit:
        return paths
    paths.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return paths[:limit]


def _expected_primary(state: dict[str, Any]) -> str:
    planner_mode = state.get("anomaly_gate", {}).get("planner_mode")
    if planner_mode == "audit_only":
        return "audit_only"
    if planner_mode == "degraded" and state.get("anomaly_gate", {}).get("issues"):
        return "data_repair"
    bottleneck = state.get("primary_bottleneck")
    if bottleneck in {"shop_visit_to_pay_cvr", "inquiry_to_pay_cvr", "refund_rate"}:
        return "conversion_repair"
    if bottleneck == "aov":
        return "aov_lift"
    if bottleneck == "repurchase_rate":
        return "repurchase_activation"
    if state.get("search_opportunities"):
        return "search_positioning"
    return "content_formula_scaling"


def _simple_rule_baseline(state: dict[str, Any]) -> str:
    return _expected_primary(state)


def _last_week_repeat_baseline(states: list[dict[str, Any]], index: int, missions_by_state: dict[str, dict[str, Any]]) -> str:
    if index == 0:
        return "conversion_repair"
    previous_state = states[index - 1]
    previous_mission = missions_by_state.get(previous_state["state_id"])
    if previous_mission:
        return previous_mission.get("primary_mission", {}).get("mission_type", "conversion_repair")
    return "conversion_repair"


def _schema_validity() -> float:
    sample_limit = _env_int("REVENUE_OS_EVAL_SCHEMA_SAMPLE", 1, 1, 500)
    checked = 0
    valid = 0
    for object_type in [
        "source_snapshot_manifest",
        "planner_bundle_manifest",
        "active_runtime_manifest",
        "entity_registry",
        "metric_registry",
        "anomaly_gate_result",
        "current_state",
        "mission_plan",
        "planner_decision_ledger",
        "execution_package",
        "experiment_record",
        "execution_completion_record",
        "experiment_result",
        "post_feedback_report",
        "pattern_object",
        "promotion_decision",
        "planner_eval_record",
    ]:
        for path in _latest_paths(object_type, sample_limit):
            checked += 1
            try:
                validate_contract_document(object_type, read_json(path))
                valid += 1
            except Exception:
                pass
    return round(valid / checked, 2) if checked else 1.0


def run_replay_eval(bundle_id: str) -> dict[str, Any]:
    bundle = read_artifact("planner_bundle_manifest", bundle_id)
    state_limit = _env_int("REVENUE_OS_EVAL_STATE_LIMIT", 52, 4, 500)
    state_paths = list_artifacts("current_state")
    state_paths.sort(key=lambda path: (path.stat().st_mtime, path.name))
    if state_limit > 0:
        state_paths = state_paths[-state_limit:]
    states = sorted([read_json(path) for path in state_paths], key=lambda item: item.get("created_at", ""))
    missions = []
    for path in _latest_paths("mission_plan", _env_int("REVENUE_OS_EVAL_MISSION_LIMIT", 120, 10, 1000)):
        mission = read_json(path)
        if mission.get("bundle_id") == bundle_id:
            missions.append(mission)
    missions_by_state = {item["state_id"]: item for item in missions}
    experiments = [read_json(path) for path in _latest_paths("experiment_result", _env_int("REVENUE_OS_EVAL_EXPERIMENT_LIMIT", 120, 10, 2000))]
    promotions = [read_json(path) for path in _latest_paths("promotion_decision", _env_int("REVENUE_OS_EVAL_PROMOTION_LIMIT", 120, 10, 2000))]

    replay_rows = []
    simple_rows = []
    repeat_rows = []
    statistical_rows = []
    reproducibility_rows = []
    capacity_mismatches = 0
    guardrail_violations = 0
    brier_rows = []

    for index, state in enumerate(states):
        scored = score_missions_for_state(state, bundle)
        predicted = scored[0]["mission_type"] if scored else "audit_only"
        expected = _expected_primary(state)
        simple = _simple_rule_baseline(state)
        repeat = _last_week_repeat_baseline(states, index, missions_by_state)
        statistical = simple_statistical_baseline(state)
        mission = missions_by_state.get(state["state_id"])
        actual = mission.get("primary_mission", {}).get("mission_type") if mission else None
        target = actual or expected
        replay_rows.append(1.0 if predicted == target else 0.0)
        simple_rows.append(1.0 if simple == target else 0.0)
        repeat_rows.append(1.0 if repeat == target else 0.0)
        statistical_rows.append(1.0 if statistical == target else 0.0)
        if actual is not None:
            reproducibility_rows.append(1.0 if actual == predicted else 0.0)
        predicted_probability = min(max(float(state.get("confidence", 0.5) or 0.5), 0.0), 1.0)
        brier_rows.append((predicted_probability - (1.0 if predicted == target else 0.0)) ** 2)
        if scored and BUDGET_ORDER.get(scored[0].get("budget_class", "S"), 1) > BUDGET_ORDER.get(state.get("recommended_intervention_budget", "S"), 1):
            capacity_mismatches += 1
        if scored and float(scored[0].get("guardrail_multiplier", 1.0) or 0.0) == 0.0:
            guardrail_violations += 1

    planner_primary_mission_match = round(sum(replay_rows) / len(replay_rows), 2) if replay_rows else 0.0
    simple_baseline_match = round(sum(simple_rows) / len(simple_rows), 2) if simple_rows else 0.0
    repeat_baseline_match = round(sum(repeat_rows) / len(repeat_rows), 2) if repeat_rows else 0.0
    statistical_baseline_match = round(sum(statistical_rows) / len(statistical_rows), 2) if statistical_rows else 0.0
    guardrail_violation_rate = round(guardrail_violations / len(states), 2) if states else 0.0
    capacity_mismatch_rate = round(capacity_mismatches / len(states), 2) if states else 0.0
    snapshot_reproducibility = round(sum(reproducibility_rows) / len(reproducibility_rows), 2) if reproducibility_rows else 1.0
    probability_brier_score = round(sum(brier_rows) / len(brier_rows), 4) if brier_rows else 0.0

    workflow_with_completion = 0
    interval_hits = 0
    interval_total = 0
    rollback_count = 0
    for result in experiments:
        try:
            completion = read_artifact("execution_completion_record", deterministic_id("completion", result["experiment_id"]))
            if completion.get("minimum_subset_completed"):
                workflow_with_completion += 1
            if completion.get("status") in {"blocked", "skipped"}:
                rollback_count += 1
        except Exception:
            pass
        summary = result.get("posterior_lift_summary", {})
        raw_delta = summary.get("raw_delta")
        ci80 = summary.get("ci80")
        if isinstance(raw_delta, (int, float)) and isinstance(ci80, list) and len(ci80) == 2:
            interval_total += 1
            if float(ci80[0]) <= float(raw_delta) <= float(ci80[1]):
                interval_hits += 1
    workflow_execution_quality = round(workflow_with_completion / len(experiments), 2) if experiments else 0.0
    interval_coverage_80 = round(interval_hits / interval_total, 2) if interval_total else 0.0
    rollback_rate = round(rollback_count / len(experiments), 2) if experiments else 0.0

    false_promotions = 0
    promotion_approvals = 0
    for promotion in promotions:
        if promotion.get("decision") == "approve":
            promotion_approvals += 1
            try:
                pattern = read_artifact("pattern_object", promotion["pattern_id"])
            except Exception:
                false_promotions += 1
                continue
            if float(pattern.get("sample_sufficiency_avg", 0) or 0) < 0.6 or float(pattern.get("guardrail_pass_rate", 0) or 0) < 0.8:
                false_promotions += 1
    false_rule_promotion_rate = round(false_promotions / promotion_approvals, 2) if promotion_approvals else 0.0

    post_reports = [read_json(path) for path in _latest_paths("post_feedback_report", _env_int("REVENUE_OS_EVAL_POST_REPORT_LIMIT", 30, 1, 500))]
    directional_rows = []
    false_scale_rows = []
    for report in post_reports:
        for post in report.get("posts", []):
            recommendation = post.get("recommendation_class")
            observed = post.get("observed_direction_14d")
            if recommendation in {"sales_driver", "sales_assist"}:
                false_scale_rows.append(1.0 if observed != "up" else 0.0)
                directional_rows.append(1.0 if observed == "up" else 0.0)
            elif recommendation in {"commercial_drag", "refund_risk_high"}:
                directional_rows.append(1.0 if observed == "down" else 0.0)
    post_directional_accuracy_14d = round(sum(directional_rows) / len(directional_rows), 2) if directional_rows else 0.0
    false_scale_rate = round(sum(false_scale_rows) / len(false_scale_rows), 2) if false_scale_rows else 0.0

    scores = {
        "planner_primary_mission_match": planner_primary_mission_match,
        "secondary_mission_match": planner_primary_mission_match,
        "guardrail_violation_rate": guardrail_violation_rate,
        "capacity_mismatch_rate": capacity_mismatch_rate,
        "false_rule_promotion_rate": false_rule_promotion_rate,
        "schema_validity": _schema_validity(),
        "snapshot_reproducibility": snapshot_reproducibility,
        "workflow_execution_quality": workflow_execution_quality,
        "rule_promotion_safety": round(1.0 - false_rule_promotion_rate, 2),
        "probability_brier_score": probability_brier_score,
        "interval_coverage_80": interval_coverage_80,
        "post_directional_accuracy_14d": post_directional_accuracy_14d,
        "false_scale_rate": false_scale_rate,
        "rollback_rate": rollback_rate,
        "actionability_score": workflow_execution_quality,
    }
    thresholds = bundle.get("thresholds", {}).get("release", REPLAY_THRESHOLDS)
    pass_status = "pass" if (
        scores["planner_primary_mission_match"] >= thresholds["planner_primary_mission_match"]
        and scores["guardrail_violation_rate"] <= thresholds["guardrail_violation_rate"]
        and scores["capacity_mismatch_rate"] <= thresholds["capacity_mismatch_rate"]
        and scores["false_rule_promotion_rate"] <= thresholds["false_rule_promotion_rate"]
        and scores["schema_validity"] >= thresholds["schema_validity"]
        and scores["snapshot_reproducibility"] >= thresholds["snapshot_reproducibility"]
    ) else "fail"

    record = {
        "schema_version": "1.0.0",
        "object_type": "planner_eval_record",
        "eval_id": deterministic_id("eval", bundle_id),
        "bundle_id": bundle_id,
        "created_at": utc_now_iso(),
        "dataset_type": "release_gate_pack",
        "scores": scores,
        "pass_thresholds": thresholds,
        "pass_status": pass_status,
        "baseline_comparison": {
            "simple_rule_baseline_match": simple_baseline_match,
            "last_week_repeat_baseline_match": repeat_baseline_match,
            "simple_statistical_baseline_match": statistical_baseline_match,
            "vs_simple_rule_baseline_gain": round(planner_primary_mission_match - simple_baseline_match, 2),
            "vs_last_week_repeat_baseline_gain": round(planner_primary_mission_match - repeat_baseline_match, 2),
            "vs_statistical_baseline_gain": round(planner_primary_mission_match - statistical_baseline_match, 2),
        },
        "historical_replay_set": {"rows": len(states), "score": planner_primary_mission_match},
        "workflow_execution_set": {"rows": len(experiments), "score": workflow_execution_quality},
        "rule_promotion_safety_set": {"rows": promotion_approvals, "score": round(1.0 - false_rule_promotion_rate, 2)},
        "source_of_truth": "historical replay + workflow execution + promotion safety",
        "freshness_policy": {"max_age_days": 30},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("planner_eval_record", record)
    return record
