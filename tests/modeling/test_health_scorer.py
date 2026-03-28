from revenue_os.modeling.health_scorer import compute_health_score

BENCHMARKS = {
    "cover_ctr":             {"p50": 0.045},
    "engagement_rate":       {"p50": 0.040},
    "shop_visit_to_pay_cvr": {"p50": 0.018},
    "aov":                   {"p50": 200},
    "repurchase_rate":       {"p50": 0.12},
    "recent_note_median_views": {"p50": 1500},
    "recent_note_count_30d": {"p50": 12},
}

def _state(metrics, objective="conversion"):
    return {"metrics": metrics, "primary_objective": objective,
            "stage": "ramp_up", "business_model": ["ecommerce"]}

def test_conversion_bottleneck():
    s = _state({"cover_ctr": 0.05, "engagement_rate": 0.04,
                "shop_visit_to_pay_cvr": 0.004, "aov": 200})
    r = compute_health_score(s, BENCHMARKS)
    assert r["total_score"] < 70
    assert r["bottleneck"] is not None
    assert r["bottleneck"]["dimension"] == "conversion"

def test_healthy_account_no_bottleneck():
    s = _state({"cover_ctr": 0.06, "engagement_rate": 0.05,
                "shop_visit_to_pay_cvr": 0.03, "aov": 300, "repurchase_rate": 0.15})
    r = compute_health_score(s, BENCHMARKS)
    assert r["total_score"] > 55

def test_objective_changes_weights():
    metrics = {"cover_ctr": 0.07, "engagement_rate": 0.06, "shop_visit_to_pay_cvr": 0.008, "aov": 100}
    r_growth = compute_health_score(_state(metrics, "followers_growth"), BENCHMARKS)
    r_conv   = compute_health_score(_state(metrics, "conversion"), BENCHMARKS)
    assert r_growth["total_score"] != r_conv["total_score"]

def test_empty_metrics_returns_defaults():
    r = compute_health_score(_state({}), BENCHMARKS)
    assert r["total_score"] == 50  # all dims default to 50
    assert r["bottleneck"] is None
