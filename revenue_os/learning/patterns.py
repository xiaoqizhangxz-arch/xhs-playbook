from __future__ import annotations

from typing import Any

from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import list_artifacts, read_artifact, read_json, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


EVIDENCE_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}


def _better_evidence(left: str, right: str) -> str:
    return left if EVIDENCE_ORDER.get(left, 0) >= EVIDENCE_ORDER.get(right, 0) else right


def _maturity(best_evidence: str, positive_count: int, negative_count: int, repeated_success_count: int) -> str:
    if repeated_success_count >= 2 and EVIDENCE_ORDER.get(best_evidence, 0) >= EVIDENCE_ORDER["E3"] and negative_count == 0:
        return "promoted_rule"
    if positive_count >= 1 and EVIDENCE_ORDER.get(best_evidence, 0) >= EVIDENCE_ORDER["E1"]:
        return "hypothesis"
    return "observation"


def update_learning(window: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for path in sorted(list_artifacts("experiment_result")):
        result = read_json(path)
        if result.get("status") != "complete":
            continue
        experiment = read_artifact("experiment_record", result["experiment_id"])
        mission = read_artifact("mission_plan", experiment["mission_id"])
        action_key = ",".join(sorted(experiment.get("action_families", [])))
        aggregate_key = f"{mission['primary_mission']['mission_type']}||{experiment['primary_metric']}||{action_key}"
        bucket = grouped.setdefault(
            aggregate_key,
            {
                "mission_type": mission["primary_mission"]["mission_type"],
                "primary_metric": experiment["primary_metric"],
                "action_families": sorted(experiment.get("action_families", [])),
                "supporting_results": [],
                "supporting_post_refs": [],
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "repeated_success_count": 0,
                "guardrail_pass_count": 0,
                "sample_sufficiency_total": 0.0,
                "completion_weight_total": 0.0,
                "posterior_support_total": 0.0,
                "learnable_count": 0,
                "best_evidence": "E0",
            },
        )
        bucket["supporting_results"].append(result["result_id"])
        package = read_artifact("execution_package", experiment["package_id"])
        bucket["supporting_post_refs"].extend(package.get("supporting_post_refs", []))
        bucket["best_evidence"] = _better_evidence(bucket["best_evidence"], result.get("evidence_class", "E0"))
        bucket["sample_sufficiency_total"] += float(result.get("sample_sufficiency", 0) or 0)
        bucket["completion_weight_total"] += float(result.get("completion_weight", 0) or 0)
        bucket["posterior_support_total"] += float(result.get("prob_lift_gt_min_effect", 0) or 0)
        if result.get("guardrail_status") == "pass":
            bucket["guardrail_pass_count"] += 1
        if result.get("learnable"):
            bucket["learnable_count"] += 1
        outcome = result.get("outcome")
        if outcome == "positive":
            bucket["positive_count"] += 1
            if float(result.get("sample_sufficiency", 0) or 0) >= 0.6:
                bucket["repeated_success_count"] += 1
        elif outcome == "negative":
            bucket["negative_count"] += 1
        else:
            bucket["neutral_count"] += 1

    patterns: list[dict[str, Any]] = []
    for key, bucket in grouped.items():
        support_count = len(bucket["supporting_results"])
        avg_sample = round(bucket["sample_sufficiency_total"] / support_count, 3) if support_count else 0.0
        guardrail_pass_rate = round(bucket["guardrail_pass_count"] / support_count, 3) if support_count else 0.0
        completion_weight_avg = round(bucket["completion_weight_total"] / support_count, 3) if support_count else 0.0
        posterior_support_avg = round(bucket["posterior_support_total"] / support_count, 3) if support_count else 0.0
        maturity = _maturity(bucket["best_evidence"], bucket["positive_count"], bucket["negative_count"], bucket["repeated_success_count"])
        pattern = {
            "schema_version": "1.0.0",
            "object_type": "pattern_object",
            "pattern_id": deterministic_id("pattern", key),
            "created_at": utc_now_iso(),
            "window": window,
            "mission_type": bucket["mission_type"],
            "primary_metric": bucket["primary_metric"],
            "action_families": bucket["action_families"],
            "maturity": maturity,
            "evidence_class": bucket["best_evidence"],
            "statement": f"{bucket['mission_type']} improves {bucket['primary_metric']} via {','.join(bucket['action_families'])}",
            "supporting_results": bucket["supporting_results"],
            "supporting_post_refs": sorted(set(bucket["supporting_post_refs"]))[:10],
            "positive_count": bucket["positive_count"],
            "negative_count": bucket["negative_count"],
            "neutral_count": bucket["neutral_count"],
            "repeated_success_count": bucket["repeated_success_count"],
            "sample_sufficiency_avg": avg_sample,
            "completion_weight_avg": completion_weight_avg,
            "posterior_support_avg": posterior_support_avg,
            "learnable_result_count": bucket["learnable_count"],
            "guardrail_pass_rate": guardrail_pass_rate,
            "seasonality_fit": True,
            "source_of_truth": "aggregated experiment results",
            "freshness_policy": {"max_age_days": 120},
            "validator": "revenue_os.foundation.contracts.validate_contract_document",
            "failure_mode": "warning",
        }
        write_artifact("pattern_object", pattern)
        patterns.append(pattern)
    return patterns
