from __future__ import annotations

from pathlib import Path
from typing import Any

from revenue_os.acquisition.coverage import build_acquisition_coverage_report
from revenue_os.foundation.config import CONTRACTS_ROOT
from revenue_os.foundation.contracts import load_contract
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import latest_artifact, list_artifacts, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


def _artifact_exists(object_type: str) -> float:
    return 1.0 if latest_artifact(object_type) is not None else 0.0


def _score_from_components(milestone: str, components: dict[str, float]) -> dict[str, Any]:
    if not components:
        score = 0.0
    else:
        score = sum(components.values()) / len(components)
    if score >= 0.999:
        status = "done"
    elif score <= 0.0:
        status = "not_started"
    else:
        status = "in_progress"
    completed = sorted([name for name, value in components.items() if value >= 0.999])
    pending = sorted([name for name, value in components.items() if value < 0.999])
    return {
        "milestone": milestone,
        "score": round(score, 4),
        "status": status,
        "completed_components": completed,
        "pending_components": pending,
        "component_scores": {name: round(value, 4) for name, value in sorted(components.items())},
    }


def _mission_type_available(mission_type: str) -> float:
    contract = load_contract("mission_plan")
    allowed = (
        contract.get("field_shapes", {})
        .get("primary_mission", {})
        .get("properties", {})
        .get("mission_type", {})
        .get("enum", [])
    )
    return 1.0 if mission_type in allowed else 0.0


def _creator_metric_coverage() -> float:
    required = {
        "creator_exposure_7d",
        "creator_views_7d",
        "creator_cover_ctr_7d",
        "creator_completion_rate_7d",
        "creator_engagement_actions_7d",
        "creator_homepage_visitors_7d",
        "creator_net_followers_7d",
        "creator_new_follows_7d",
        "creator_unfollows_7d",
        "recent_note_count_30d",
        "recent_note_median_views",
        "recent_note_median_saves",
        "recent_note_median_comments",
        "recent_note_median_shares",
        "recent_note_top_view_note",
        "recent_note_top_save_note",
        "creator_note_data_freshness_days",
        "creator_event_active_count_mtd",
        "creator_event_start_within_7d_count",
        "creator_inspiration_topic_count_mtd",
        "creator_inspiration_high_heat_topic_count",
        "creator_events_data_freshness_days",
        "creator_inspiration_data_freshness_days",
    }
    registry = latest_artifact("metric_registry") or {}
    names = {metric.get("name") for metric in registry.get("metrics", []) if isinstance(metric, dict)}
    if not required:
        return 1.0
    return len(required.intersection(names)) / len(required)


def _has_monthly_cadence_result() -> float:
    return _artifact_exists("cadence_result")


def _latest_eval_component() -> float:
    eval_record = latest_artifact("planner_eval_record")
    if not eval_record:
        return 0.0
    return 1.0 if eval_record.get("pass_status") == "pass" else 0.5


def _phase_milestones(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    qianfan = coverage.get("qianfan_summary", {})
    creator = coverage.get("creator_summary", {})
    qianfan_visual = coverage.get("qianfan_visual_summary", {})
    creator_visual = coverage.get("creator_visual_summary", {})
    q_total = int(qianfan.get("total", 0) or 0)
    q_proven = int(qianfan.get("proven", 0) or 0)
    c_total = int(creator.get("total", 0) or 0)
    c_proven = int(creator.get("proven", 0) or 0)
    q_visual_required = int(qianfan_visual.get("required", 0) or 0)
    q_visual_ready = int(qianfan_visual.get("ready", 0) or 0)
    c_visual_required = int(creator_visual.get("required", 0) or 0)
    c_visual_ready = int(creator_visual.get("ready", 0) or 0)
    q_ratio = (q_proven / q_total) if q_total else 0.0
    c_ratio = (c_proven / c_total) if c_total else 0.0
    q_visual_ratio = (q_visual_ready / q_visual_required) if q_visual_required else 0.0
    c_visual_ratio = (c_visual_ready / c_visual_required) if c_visual_required else 0.0
    creator_metric_ratio = _creator_metric_coverage()

    milestones = [
        _score_from_components(
            "K0a",
            {
                "source_snapshot_manifest": _artifact_exists("source_snapshot_manifest"),
                "normalized_first_party": _artifact_exists("normalized_first_party"),
                "metric_registry": _artifact_exists("metric_registry"),
                "entity_registry": _artifact_exists("entity_registry"),
                "anomaly_gate_result": _artifact_exists("anomaly_gate_result"),
                "current_state": _artifact_exists("current_state"),
                "mission_plan": _artifact_exists("mission_plan"),
                "planner_decision_ledger": _artifact_exists("planner_decision_ledger"),
            },
        ),
        _score_from_components(
            "K0b",
            {
                "planner_bundle_manifest": _artifact_exists("planner_bundle_manifest"),
                "active_runtime_manifest": _artifact_exists("active_runtime_manifest"),
                "alias_resolution_report": _artifact_exists("alias_resolution_report"),
                "reconcile_report": _artifact_exists("reconcile_report"),
                "run_index_manifest": _artifact_exists("run_index_manifest"),
                "frozen_contracts_17_plus": 1.0 if len(list(Path(CONTRACTS_ROOT).glob("*.json"))) >= 17 else 0.0,
            },
        ),
        _score_from_components(
            "K1",
            {
                "execution_package": _artifact_exists("execution_package"),
                "experiment_record": _artifact_exists("experiment_record"),
                "execution_completion_record": _artifact_exists("execution_completion_record"),
                "experiment_result": _artifact_exists("experiment_result"),
                "pattern_object": _artifact_exists("pattern_object"),
                "promotion_decision": _artifact_exists("promotion_decision"),
            },
        ),
        _score_from_components(
            "K2",
            {
                "planner_eval_record": _artifact_exists("planner_eval_record"),
                "active_runtime_manifest": _artifact_exists("active_runtime_manifest"),
                "monthly_cadence_result": _has_monthly_cadence_result(),
                "release_gate_eval": _latest_eval_component(),
            },
        ),
        _score_from_components(
            "K3",
            {
                "qianfan_surface_coverage": q_ratio,
                "creator_surface_coverage": c_ratio,
                "qianfan_visual_coverage": q_visual_ratio,
                "creator_visual_coverage": c_visual_ratio,
                "creator_metric_registry_coverage": creator_metric_ratio,
                "search_mission_support": _mission_type_available("search_positioning"),
                "repurchase_mission_support": _mission_type_available("repurchase_activation"),
            },
        ),
    ]
    return milestones


def _overall_progress(milestones: list[dict[str, Any]]) -> float:
    weights = {
        "K0a": 0.25,
        "K0b": 0.20,
        "K1": 0.25,
        "K2": 0.20,
        "K3": 0.10,
    }
    weighted = 0.0
    total_weight = 0.0
    for milestone in milestones:
        name = milestone["milestone"]
        weight = weights.get(name, 0.0)
        weighted += weight * float(milestone["score"])
        total_weight += weight
    if total_weight <= 0:
        return 0.0
    return round((weighted / total_weight) * 100.0, 2)


def _artifact_health() -> dict[str, Any]:
    tracked = [
        "source_snapshot_manifest",
        "metric_registry",
        "entity_registry",
        "current_state",
        "mission_plan",
        "planner_decision_ledger",
        "execution_package",
        "experiment_record",
        "experiment_result",
        "planner_eval_record",
        "cadence_result",
        "acquisition_frontier_report",
    ]
    counts = {name: len(list_artifacts(name)) for name in tracked}
    return {
        "contracts_total": len(list(Path(CONTRACTS_ROOT).glob("*.json"))),
        "tracked_object_counts": counts,
        "latest_cadence_status": (latest_artifact("cadence_result") or {}).get("status"),
    }


def _build_blockers_and_actions(coverage: dict[str, Any], overall_pct: float) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    actions: list[str] = []

    missing = coverage.get("missing_surfaces", [])
    q_missing = [item["surface_name"] for item in missing if item.get("source_system") == "qianfan"]
    c_missing = [item["surface_name"] for item in missing if item.get("source_system") == "creator"]
    if q_missing:
        blockers.append(f"Qianfan missing proven surfaces: {len(q_missing)} ({', '.join(q_missing[:6])})")
        actions.append("Run wave proof jobs and close remaining Qianfan selector/export proofs before cadence promotion.")
    if c_missing:
        blockers.append(f"Creator missing proven surfaces: {len(c_missing)} ({', '.join(c_missing[:6])})")
        actions.append("Finish Creator full coverage by proving remaining surfaces and enabling export routing.")

    visual_missing = coverage.get("missing_visual_surfaces", [])
    if visual_missing:
        sample = [item.get("surface_name", "unknown") for item in visual_missing[:6]]
        blockers.append(f"Missing quantified visual capture on surfaces: {len(visual_missing)} ({', '.join(sample)})")
        actions.append("Run browser probe collection to satisfy per-surface visual volume policy before claiming 100% coverage.")
    baseline_alignment = coverage.get("baseline_alignment", {})
    if baseline_alignment and not bool(baseline_alignment.get("baseline_met", True)):
        blockers.append("Runtime visual capture volume is below Business Library screenshot PDF baseline.")
        actions.append("Run visual-fill and re-run source capture to keep runtime visual records >= legacy screenshot baseline.")
    extraction_baseline = coverage.get("qianfan_extraction_baseline", {})
    if extraction_baseline and not bool(extraction_baseline.get("met", True)):
        blockers.append("Qianfan auto extraction volume is below raw_data manual baseline (source/users families).")
        actions.append("Run missing Qianfan surfaces by daily/weekly/monthly tabs until source_auto/users_auto counts are >= raw_data baseline.")

    frontier = latest_artifact("acquisition_frontier_report") or {}
    governance = frontier.get("governance_summary", {})
    unknown_candidates = int(governance.get("unknown_api_candidates", 0) or 0)
    if unknown_candidates > 0:
        blockers.append(
            f"Hidden-entry frontier backlog exists: {unknown_candidates} unknown API candidates."
        )
        actions.append("Review `acquire frontier` unknown candidates and classify them into monitor/promote/ignore policy.")

    eval_record = latest_artifact("planner_eval_record") or {}
    if eval_record and eval_record.get("pass_status") != "pass":
        blockers.append("Release gate currently not passing replay thresholds.")
        actions.append("Tune planner/eval thresholds until replay gate passes for target bundle.")

    if overall_pct < 90:
        actions.append("Prioritize coverage closure and rerun weekly/monthly cadence with readiness green.")

    if not actions:
        actions.append("Maintain cadence stability and monitor freshness SLA.")
    return blockers, actions


def build_phase_progress_report(phase: str = "phase1") -> dict[str, Any]:
    if phase not in {"phase1", "phase2"}:
        raise ValueError(f"Unsupported phase: {phase}")

    coverage = build_acquisition_coverage_report("both")
    milestones = _phase_milestones(coverage)
    overall_pct = _overall_progress(milestones)
    blockers, actions = _build_blockers_and_actions(coverage, overall_pct)

    qianfan = coverage["qianfan_summary"]
    creator = coverage["creator_summary"]
    qianfan_visual = coverage.get("qianfan_visual_summary", {})
    creator_visual = coverage.get("creator_visual_summary", {})
    missing_total = len(coverage.get("missing_surfaces", []))
    visual_missing_total = len(coverage.get("missing_visual_surfaces", []))
    decision_complete_pct = float(coverage.get("decision_complete_coverage_pct", 0.0) or 0.0)
    coverage_v2_pct = float(coverage.get("coverage_v2_pct", decision_complete_pct) or 0.0)
    if overall_pct >= 90.0 and missing_total == 0 and visual_missing_total == 0 and coverage_v2_pct >= 99.99:
        status = "on_track"
    elif overall_pct >= 70.0:
        status = "in_progress"
    else:
        status = "at_risk"

    report = {
        "schema_version": "1.0.0",
        "object_type": "phase_progress_report",
        "progress_id": deterministic_id("progress", phase, utc_now_iso()),
        "phase": phase,
        "created_at": utc_now_iso(),
        "overall_progress_pct": overall_pct,
        "overall_status": status,
        "coverage_summary": {
            "qianfan_proven": int(qianfan.get("proven", 0) or 0),
            "qianfan_total": int(qianfan.get("total", 0) or 0),
            "creator_proven": int(creator.get("proven", 0) or 0),
            "creator_total": int(creator.get("total", 0) or 0),
            "missing_total": missing_total,
            "qianfan_visual_ready": int(qianfan_visual.get("ready", 0) or 0),
            "qianfan_visual_required": int(qianfan_visual.get("required", 0) or 0),
            "creator_visual_ready": int(creator_visual.get("ready", 0) or 0),
            "creator_visual_required": int(creator_visual.get("required", 0) or 0),
            "visual_missing_total": visual_missing_total,
            "decision_complete_coverage_pct": decision_complete_pct,
            "coverage_v2_pct": coverage_v2_pct,
            "frontier_governance_coverage_pct": float(coverage.get("frontier_governance_coverage_pct", 0.0) or 0.0),
            "frontier_p0p1_integration_pct": float(coverage.get("frontier_p0p1_integration_pct", 0.0) or 0.0),
        },
        "milestone_progress": milestones,
        "artifact_health": _artifact_health(),
        "blockers": blockers,
        "next_actions": actions,
        "source_of_truth": "runtime artifacts + acquisition coverage report",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("phase_progress_report", report)
    return report
