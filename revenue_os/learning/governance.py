from __future__ import annotations

from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import read_artifact, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


EVIDENCE_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}


def decide_promotion(pattern_id: str, evidence_class: str | None = None, maturity: str | None = None) -> dict:
    pattern = read_artifact("pattern_object", pattern_id)
    evidence = evidence_class or pattern.get("evidence_class", "E0")
    maturity = maturity or pattern.get("maturity", "observation")
    sample_sufficient = float(pattern.get("sample_sufficiency_avg", 0) or 0) >= 0.6
    repeated_success = int(pattern.get("repeated_success_count", 0) or 0) >= 2
    guardrail_pass = float(pattern.get("guardrail_pass_rate", 0) or 0) >= 0.8
    completion_sufficient = float(pattern.get("completion_weight_avg", 0) or 0) >= 0.65
    posterior_support = float(pattern.get("posterior_support_avg", 0) or 0)
    seasonality_fit = bool(pattern.get("seasonality_fit", True))
    negative_pressure = int(pattern.get("negative_count", 0) or 0) >= 2

    if negative_pressure and maturity == "promoted_rule":
        decision = "downgrade"
        target = "hypothesis"
    elif repeated_success and guardrail_pass and sample_sufficient and completion_sufficient and posterior_support >= 0.65 and EVIDENCE_ORDER.get(evidence, 0) >= EVIDENCE_ORDER["E2"]:
        decision = "approve"
        target = "promoted_rule"
    elif sample_sufficient and completion_sufficient and EVIDENCE_ORDER.get(evidence, 0) >= EVIDENCE_ORDER["E1"]:
        decision = "defer"
        target = "hypothesis"
    else:
        decision = "reject"
        target = "observation"

    promotion = {
        "schema_version": "1.0.0",
        "object_type": "promotion_decision",
        "promotion_id": deterministic_id("promotion", pattern_id),
        "pattern_id": pattern_id,
        "created_at": utc_now_iso(),
        "decision": decision,
        "target_maturity": target,
        "completion_sufficiency": round(float(pattern.get("completion_weight_avg", 0) or 0), 3),
        "posterior_support": round(posterior_support, 3),
        "evidence_cap": pattern.get("evidence_class", "E0"),
        "reason_codes": [
            f"sample_sufficient={sample_sufficient}",
            f"repeated_success={repeated_success}",
            f"guardrail_pass={guardrail_pass}",
            f"completion_sufficient={completion_sufficient}",
            f"posterior_support={round(posterior_support, 3)}",
            f"seasonality_fit={seasonality_fit}",
            f"negative_pressure={negative_pressure}",
        ],
        "source_of_truth": "governed promotion queue",
        "freshness_policy": {"max_age_days": 60},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("promotion_decision", promotion)
    return promotion
