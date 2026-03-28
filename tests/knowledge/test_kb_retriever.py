from revenue_os.knowledge.kb_retriever import retrieve_for_mission

def test_returns_results():
    results = retrieve_for_mission("conversion_repair", top_k=5)
    assert isinstance(results, list)
    assert len(results) > 0

def test_result_fields():
    results = retrieve_for_mission("content_formula_scaling", top_k=3)
    for r in results:
        assert "insight" in r
        assert "detail" in r
        assert "score" in r

def test_semantic_boost_reranks():
    """有 user_state 时排名应与无 user_state 时不同"""
    plain = retrieve_for_mission("conversion_repair", top_k=10)
    boosted = retrieve_for_mission(
        "conversion_repair",
        bottleneck="shop_visit_to_pay_cvr",
        user_state={"stage": "ramp_up", "business_model": ["ecommerce"],
                    "industry": "珠宝配饰", "weak_metrics": ["shop_visit_to_pay_cvr"],
                    "inferred": {"industry_weights": {"珠宝配饰": 1.6, "通用": 1.3}}},
        top_k=10,
    )
    plain_ids   = [r["insight"][:20] for r in plain]
    boosted_ids = [r["insight"][:20] for r in boosted]
    assert plain_ids != boosted_ids

def test_all_missions_return_results():
    missions = ["conversion_repair","aov_lift","repurchase_activation",
                "search_positioning","content_formula_scaling"]
    for m in missions:
        r = retrieve_for_mission(m, top_k=3)
        assert len(r) > 0, f"Mission {m} returned no results"
