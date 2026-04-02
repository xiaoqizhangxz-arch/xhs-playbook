from __future__ import annotations

from typing import Any

from revenue_os.foundation.ids import deterministic_id, idempotency_key
from revenue_os.foundation.io import list_artifacts, object_path, read_artifact, read_json, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso
from revenue_os.modeling.experiment_bayes import score_experiment_bayesian


EXPERIMENT_STATES = {
    "planned": {"running", "rolled_back"},
    "running": {"awaiting_window", "rolled_back"},
    "awaiting_window": {"scored", "rolled_back"},
    "scored": {"governed", "rolled_back"},
    "governed": {"promoted", "rolled_back"},
    "promoted": set(),
    "rolled_back": set(),
}


def _transition(experiment: dict[str, Any], target_status: str) -> None:
    current = experiment.get("status", "planned")
    allowed = EXPERIMENT_STATES.get(current, set())
    if current != target_status and target_status not in allowed:
        raise ValueError(f"invalid experiment transition {current} -> {target_status}")
    experiment["status"] = target_status
    experiment.setdefault("status_history", []).append({"status": target_status, "at": utc_now_iso()})


def register_experiment(mission_id: str) -> dict[str, Any]:
    mission = read_artifact("mission_plan", mission_id)
    package_id = deterministic_id("pkg", mission_id, mission["primary_mission"]["mission_type"])
    package = read_artifact("execution_package", package_id)
    experiment_id = deterministic_id("exp", mission_id, package_id)
    if object_path("experiment_record", experiment_id).exists():
        return read_artifact("experiment_record", experiment_id)
    state = read_artifact("current_state", mission["state_id"])
    experiment = {
        "schema_version": "1.0.0",
        "object_type": "experiment_record",
        "experiment_id": experiment_id,
        "mission_id": mission_id,
        "package_id": package_id,
        "created_at": utc_now_iso(),
        "status": "planned",
        "status_history": [{"status": "planned", "at": utc_now_iso()}],
        "window_days": 7,
        "idempotency_key": idempotency_key(mission_id, package_id),
        "hypothesis": f"Executing {package['title']} should improve {package['success_metrics'][0]} without violating guardrails",
        "primary_metric": package["success_metrics"][0],
        "secondary_metrics": package["success_metrics"][1:],
        "start_state_id": mission["state_id"],
        "start_snapshot_id": state["snapshot_id"],
        "end_state_id": None,
        "end_snapshot_id": None,
        "action_families": sorted({action["action_family"] for action in package["actions"]}),
        "source_of_truth": "execution_package generated experiment",
        "freshness_policy": {"max_age_days": 30},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("experiment_record", experiment)
    return experiment


def complete_experiment(
    experiment_id: str,
    status: str = "shipped_full",
    completed_actions: list[str] | None = None,
    operator_notes: str | None = None,
) -> dict[str, Any]:
    experiment = read_artifact("experiment_record", experiment_id)
    package = read_artifact("execution_package", experiment["package_id"])
    all_actions = [action["id"] for action in package["actions"]]
    minimum_subset = list(package["minimum_shippable_subset"])

    if completed_actions is None:
        if status == "shipped_full":
            completed_actions = all_actions
        elif status == "shipped_partial":
            completed_actions = minimum_subset
        else:
            completed_actions = []

    blocked_actions = [action for action in all_actions if action not in completed_actions]
    minimum_subset_completed = all(action in completed_actions for action in minimum_subset)
    completion = {
        "schema_version": "1.0.0",
        "object_type": "execution_completion_record",
        "completion_id": deterministic_id("completion", experiment_id),
        "experiment_id": experiment_id,
        "created_at": utc_now_iso(),
        "status": status,
        "minimum_subset_completed": minimum_subset_completed,
        "completed_actions": completed_actions,
        "blocked_actions": blocked_actions,
        "operator_notes": operator_notes,
        "source_of_truth": "operator completion tracking",
        "freshness_policy": {"max_age_days": 30},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    if status in {"shipped_full", "shipped_partial"} and minimum_subset_completed:
        if experiment["status"] == "planned":
            _transition(experiment, "running")
        _transition(experiment, "awaiting_window")
    else:
        _transition(experiment, "rolled_back")
    write_artifact("experiment_record", experiment)
    write_artifact("execution_completion_record", completion)
    return completion


_MIN_WINDOW_HOURS = 24  # 实验窗口最短间隔（小时），低于此判为重复快照


def _latest_state_after(start_state_id: str, min_window_hours: int = _MIN_WINDOW_HOURS) -> str | None:
    """查找实验窗口后的 end_state，附加窗口对齐规则避免拿到重复快照。

    规则：
      1. 必须是不同 state_id
      2. snapshot_id 不同（防止同一次采集被重复写入两次）
      3. created_at 至少比 start 晚 min_window_hours 小时
    """
    import re
    from datetime import datetime, timezone, timedelta

    start_state = read_artifact("current_state", start_state_id)
    start_ts_raw = start_state.get("created_at", "")

    # 解析起始时间
    def _parse(ts: str) -> datetime | None:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

    start_dt = _parse(start_ts_raw)
    min_dt = (start_dt + timedelta(hours=min_window_hours)) if start_dt else None
    start_snapshot = start_state.get("snapshot_id", "")

    candidates = []
    for path in list_artifacts("current_state"):
        try:
            state = read_json(path)
        except Exception:
            continue
        if state.get("state_id") == start_state_id:
            continue
        if state.get("snapshot_id") and state["snapshot_id"] == start_snapshot:
            continue  # 同批次快照，skip
        end_dt = _parse(state.get("created_at", ""))
        if end_dt is None:
            continue
        if min_dt and end_dt < min_dt:
            continue  # 窗口不足
        candidates.append((end_dt, state["state_id"]))

    if not candidates:
        return None
    return sorted(candidates)[-1][1]  # 取最新的


# AINRL 代理映射：ETL ainrl_*_cvr 字段 → 标准 metric 名
_AINRL_PROXY_MAP: dict[str, list[str]] = {
    "repurchase_rate":          ["ainrl_n_to_r_cvr"],
    "deal_intent_to_new_cvr":  ["ainrl_i_to_n_cvr"],
    "aipl_interest_to_new_cvr":["ainrl_i_to_n_cvr"],
    "deal_new_to_returning_cvr": ["ainrl_n_to_r_cvr"],
}


def _lookup_metric_value(state: dict[str, Any], metric_name: str) -> float | None:
    """多源查找指标值：metric_snapshot → ETL proxy 字段 → None"""
    snapshot = state.get("metric_snapshot", {})
    val = snapshot.get(metric_name)
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    # 尝试代理字段
    for proxy in _AINRL_PROXY_MAP.get(metric_name, []):
        val = snapshot.get(proxy)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _metric_delta(start_state: dict[str, Any], end_state: dict[str, Any] | None, metric_name: str) -> float | None:
    if end_state is None:
        return None
    start_value = _lookup_metric_value(start_state, metric_name)
    end_value = _lookup_metric_value(end_state, metric_name)
    # 避免拿到同一快照造成 delta≈0 的伪中性
    start_snap = start_state.get("snapshot_id", "")
    end_snap   = end_state.get("snapshot_id", "")
    if start_snap and end_snap and start_snap == end_snap:
        return None
    if isinstance(start_value, float) and isinstance(end_value, float):
        delta = round(end_value - start_value, 6)
        return delta
    return None


def _evidence_class(outcome: str, sample_sufficiency: float, guardrail_pass: bool) -> str:
    if outcome == "positive" and sample_sufficiency >= 0.8 and guardrail_pass:
        return "E2"
    if outcome == "positive" and guardrail_pass:
        return "E1"
    if outcome == "negative":
        return "E1"
    return "E0"


def _cap_evidence_class(evidence_class: str, evidence_cap: str) -> str:
    order = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}
    reverse = {value: key for key, value in order.items()}
    return reverse[min(order.get(evidence_class, 0), order.get(evidence_cap, 0))]


def _legacy_outcome(completion: dict[str, Any], end_state: dict[str, Any] | None, primary_delta: float | None) -> tuple[str, str]:
    if not completion.get("minimum_subset_completed"):
        return "incomplete_execution", "negative"
    if end_state is None:
        return "insufficient_window", "inconclusive"
    if primary_delta is not None and primary_delta > 0:
        return "complete", "positive"
    if primary_delta is not None and primary_delta < 0:
        return "complete", "negative"
    return "complete", "neutral"


def score_experiment(experiment_id: str, end_state_id: str | None = None) -> dict[str, Any]:
    experiment = read_artifact("experiment_record", experiment_id)
    mission = read_artifact("mission_plan", experiment["mission_id"])
    bundle = read_artifact("planner_bundle_manifest", mission["bundle_id"])
    scorer_mode = bundle.get("activation_mode_by_component", {}).get("completion_aware_scorer", "shadow")
    completion = read_artifact("execution_completion_record", deterministic_id("completion", experiment_id))
    start_state = read_artifact("current_state", experiment["start_state_id"])
    resolved_end_state_id = end_state_id or experiment.get("end_state_id") or _latest_state_after(experiment["start_state_id"])
    end_state = read_artifact("current_state", resolved_end_state_id) if resolved_end_state_id else None

    existing_path = object_path("experiment_result", deterministic_id("result", experiment_id))
    if existing_path.exists():
        existing = read_json(existing_path)
        if existing.get("end_state_id") == resolved_end_state_id:
            return existing

    metrics = [experiment["primary_metric"], *experiment.get("secondary_metrics", [])]
    metric_deltas = {metric: _metric_delta(start_state, end_state, metric) for metric in metrics}
    guardrail_deltas = {
        "refund_rate": _metric_delta(start_state, end_state, "refund_rate"),
        "aov": _metric_delta(start_state, end_state, "aov"),
    }
    sample_sufficiency = float((end_state or start_state).get("confidence_breakdown", {}).get("sample_size", 0) or 0)
    primary_delta = metric_deltas.get(experiment["primary_metric"])
    guardrail_pass = guardrail_deltas["refund_rate"] is None or guardrail_deltas["refund_rate"] <= 0.02

    bayes = score_experiment_bayesian(
        experiment=experiment,
        completion=completion,
        start_state=start_state,
        end_state=end_state,
        metric_deltas=metric_deltas,
        guardrail_deltas=guardrail_deltas,
        sample_sufficiency=sample_sufficiency,
    )
    if scorer_mode == "active":
        status = bayes["status"]
        outcome = bayes["outcome"]
        evidence_class = _cap_evidence_class(_evidence_class(outcome, sample_sufficiency, guardrail_pass), bayes["evidence_cap"])
    else:
        status, outcome = _legacy_outcome(completion, end_state, primary_delta)
        evidence_class = _evidence_class(outcome, sample_sufficiency, guardrail_pass)

    # relative delta（付加，用于治理层判断商业幅度，不替换 Bayes 输入）
    primary_relative_delta: float | None = None
    start_primary = _lookup_metric_value(start_state, experiment["primary_metric"])
    if primary_delta is not None and start_primary is not None and abs(start_primary) > 1e-9:
        primary_relative_delta = round(primary_delta / abs(start_primary), 4)

    result = {
        "schema_version": "1.0.0",
        "object_type": "experiment_result",
        "result_id": deterministic_id("result", experiment_id),
        "experiment_id": experiment_id,
        "created_at": utc_now_iso(),
        "status": status,
        "outcome": outcome,
        "evidence_class": evidence_class,
        "metric_deltas": metric_deltas,
        "primary_relative_delta": primary_relative_delta,
        "guardrail_deltas": guardrail_deltas,
        "guardrail_status": "pass" if guardrail_pass else "warning",
        "sample_sufficiency": sample_sufficiency,
        "completion_weight": bayes["completion_weight"],
        "practical_significance_met": bayes["practical_significance_met"],
        "prob_lift_gt_min_effect": bayes["prob_lift_gt_min_effect"],
        "posterior_lift_summary": bayes["posterior_lift_summary"],
        "prob_guardrail_breach": bayes["prob_guardrail_breach"],
        "evidence_cap": bayes["evidence_cap"],
        "learnable": bayes["learnable"],
        "counterfactual_method": bayes["counterfactual_method"],
        "calibration_bucket": bayes["calibration_bucket"],
        "statistical_baseline_comparison": bayes["statistical_baseline_comparison"],
        "start_state_id": experiment["start_state_id"],
        "start_snapshot_id": experiment["start_snapshot_id"],
        "end_state_id": resolved_end_state_id,
        "end_snapshot_id": end_state.get("snapshot_id") if end_state else None,
        "source_of_truth": "completion-aware bayesian scoring from current_state snapshots",
        "freshness_policy": {"max_age_days": 60},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    if status == "complete":
        if experiment["status"] == "awaiting_window":
            _transition(experiment, "scored")
        experiment["end_state_id"] = resolved_end_state_id
        experiment["end_snapshot_id"] = end_state.get("snapshot_id") if end_state else None
    write_artifact("experiment_record", experiment)
    write_artifact("experiment_result", result)
    return result
