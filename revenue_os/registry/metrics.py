from __future__ import annotations

from statistics import median
from typing import Any

from revenue_os.foundation.config import DEFAULT_THRESHOLDS
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import object_path, read_json, write_artifact
from revenue_os.modeling.stabilizer import apply_metric_stabilization


def _safe_float(value: Any) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _health_status(value: float | None, threshold_low: float | None = None, threshold_high: float | None = None) -> str:
    if value is None:
        return "unknown"
    if threshold_low is not None and value < threshold_low:
        return "bad"
    if threshold_high is not None and value > threshold_high:
        return "bad"
    return "healthy"


def _aggregate_shop_funnel(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    visits = sum(_safe_float(item.get("店铺页访问人数")) or 0.0 for item in rows)
    clicks = sum(_safe_float(item.get("商品点击人数")) or 0.0 for item in rows)
    pays = sum(_safe_float(item.get("店铺页支付人数")) or 0.0 for item in rows)
    return {
        "visits": visits,
        "clicks": clicks,
        "pays": pays,
        "shop_visit_to_pay_cvr": pays / visits if visits else None,
        "product_click_to_pay_cvr": pays / clicks if clicks else None,
    }


def _metric(
    name: str,
    tier: str,
    formula: str,
    numerator_source: str,
    denominator_source: str,
    numerator_value: float | int | None,
    denominator_value: float | int | None,
    window_policy: str,
    value: float | None,
    health_status: str,
    planner_eligibility: bool,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "metric_id": f"metric__{name}",
        "name": name,
        "tier": tier,
        "formula": formula,
        "numerator_source": numerator_source,
        "denominator_source": denominator_source,
        "numerator_value": None if numerator_value is None else float(numerator_value),
        "denominator_value": None if denominator_value is None else float(denominator_value),
        "window_policy": window_policy,
        "value": None if value is None else float(value),
        "health_status": health_status,
        "planner_eligibility": planner_eligibility,
        "metadata": metadata,
    }


def _median(rows: list[float]) -> float | None:
    values = [value for value in rows if value is not None]
    return float(median(values)) if values else None


def build_metric_registry(snapshot_id: str) -> dict[str, Any]:
    first_party = read_json(object_path("normalized_first_party", snapshot_id))
    monthly = first_party.get("monthly_business_health", {})
    latest = monthly.get("latest", {})
    funnel = _aggregate_shop_funnel(first_party.get("shop_funnel", {}).get("rows", []))
    search_rows = first_party.get("search_terms", {}).get("rows", [])
    search_ctrs = [_safe_float(item.get("click_rate")) for item in search_rows]
    search_cvrs = [_safe_float(item.get("purchase_cvr")) for item in search_rows]
    user_portrait = first_party.get("user_portrait", {})
    funnel_profile = user_portrait.get("funnel", {})
    repurchase_rate = _safe_float((funnel_profile.get("conversion_rates") or {}).get("N_to_R"))
    service_domain = first_party.get("service_after_sale", {})
    fulfillment_domain = first_party.get("fulfillment_logistics", {})
    settlement_domain = first_party.get("settlement_ops", {})
    user_asset_signals = first_party.get("user_asset_signals", {})
    deal_flow = user_asset_signals.get("deal_population_flow", {})
    aipl_assets = user_asset_signals.get("aipl_assets", {})
    deal_stages = deal_flow.get("stages", {})
    aipl_stages = aipl_assets.get("stages", {})
    deal_awareness = _safe_float((deal_stages.get("认知") or {}).get("count"))
    deal_intent = _safe_float((deal_stages.get("意向") or {}).get("count"))
    deal_new = _safe_float((deal_stages.get("新客") or {}).get("count"))
    deal_returning = _safe_float((deal_stages.get("老客") or {}).get("count"))
    deal_churn = _safe_float((deal_stages.get("流失") or {}).get("count"))
    aipl_awareness = _safe_float((aipl_stages.get("A") or {}).get("count"))
    aipl_interest = _safe_float((aipl_stages.get("I") or {}).get("count"))
    aipl_new = _safe_float((aipl_stages.get("N") or {}).get("count"))
    aipl_returning = _safe_float((aipl_stages.get("R") or {}).get("count"))

    creator = first_party.get("creator_platform", {})
    creator_panel = creator.get("creator_account_panel", {})
    creator_inventory = creator.get("creator_note_inventory", {})
    creator_events = creator.get("creator_events_board", {})
    creator_inspiration = creator.get("creator_inspiration_board", {})
    creator_visual = creator.get("visual_signals", {})
    creator_home_visual = creator_visual.get("creator_home", {})
    creator_note_visual = creator_visual.get("creator_note_manager", {})
    creator_events_visual = creator_visual.get("creator_events", {})
    creator_inspiration_visual = creator_visual.get("creator_inspiration", {})
    note_rows = creator_inventory.get("rows", [])
    note_views = [_safe_float(item.get("views")) for item in note_rows]
    note_saves = [_safe_float(item.get("saves")) for item in note_rows]
    note_comments = [_safe_float(item.get("comments")) for item in note_rows]
    note_shares = [_safe_float(item.get("shares")) for item in note_rows]
    top_view_note = note_rows[0] if note_rows else None
    top_save_note = sorted(note_rows, key=lambda item: float(item.get("saves", 0) or 0), reverse=True)[0] if note_rows else None
    creator_note_freshness_days = creator.get("freshness", {}).get("creator_note_manager_days")
    creator_home_freshness_days = creator.get("freshness", {}).get("creator_home_days")
    creator_events_freshness_days = creator.get("freshness", {}).get("creator_events_days")
    creator_inspiration_freshness_days = creator.get("freshness", {}).get("creator_inspiration_days")
    creator_chart_nodes = (
        float(creator_home_visual.get("chart_node_count", 0) or 0)
        + float(creator_note_visual.get("chart_node_count", 0) or 0)
        + float(creator_events_visual.get("chart_node_count", 0) or 0)
        + float(creator_inspiration_visual.get("chart_node_count", 0) or 0)
    )
    creator_numeric_signal_count = (
        float(len(creator_home_visual.get("numeric_text_samples", []) or []))
        + float(len(creator_note_visual.get("numeric_text_samples", []) or []))
        + float(len(creator_events_visual.get("numeric_text_samples", []) or []))
        + float(len(creator_inspiration_visual.get("numeric_text_samples", []) or []))
    )

    metrics = [
        _metric(
            "shop_visit_to_pay_cvr",
            "P0",
            "sum(store_pay_users) / sum(store_visit_users)",
            "shop_funnel.rows.店铺页支付人数",
            "shop_funnel.rows.店铺页访问人数",
            funnel["pays"],
            funnel["visits"],
            "latest_available_store_window",
            funnel["shop_visit_to_pay_cvr"],
            _health_status(funnel["shop_visit_to_pay_cvr"], threshold_low=DEFAULT_THRESHOLDS["shop_visit_to_pay_cvr_low"]),
            True,
        ),
        _metric(
            "product_click_to_pay_cvr",
            "P1",
            "sum(store_pay_users) / sum(product_click_users)",
            "shop_funnel.rows.店铺页支付人数",
            "shop_funnel.rows.商品点击人数",
            funnel["pays"],
            funnel["clicks"],
            "latest_available_store_window",
            funnel["product_click_to_pay_cvr"],
            _health_status(funnel["product_click_to_pay_cvr"], threshold_low=DEFAULT_THRESHOLDS["product_click_to_pay_cvr_low"]),
            True,
        ),
        _metric(
            "aov",
            "P0",
            "支付金额 / 支付买家数",
            "monthly_business_health.latest.支付金额",
            "monthly_business_health.latest.支付买家数",
            _safe_float(latest.get("支付金额")),
            _safe_float(latest.get("支付买家数")),
            latest.get("_month", "unknown"),
            _safe_float(latest.get("客单价")),
            _health_status(_safe_float(latest.get("客单价")), threshold_low=DEFAULT_THRESHOLDS["aov_low"]),
            True,
        ),
        _metric(
            "refund_rate",
            "P0",
            "退款订单数 / 支付订单数",
            "monthly_business_health.latest.退款订单数（退款时间）",
            "monthly_business_health.latest.支付订单数",
            _safe_float(latest.get("退款订单数（退款时间）")),
            _safe_float(latest.get("支付订单数")),
            latest.get("_month", "unknown"),
            _safe_float(latest.get("退款订单占比（退款时间）")),
            _health_status(_safe_float(latest.get("退款订单占比（退款时间）")), threshold_high=DEFAULT_THRESHOLDS["refund_rate_high"]),
            True,
        ),
        _metric(
            "inquiry_to_pay_cvr",
            "P0",
            "询购转化订单数 / 会话量 proxy",
            "monthly_business_health.latest.cs_询购转化订单数",
            "monthly_business_health.latest.cs_会话量",
            _safe_float(latest.get("cs_询购转化订单数")),
            _safe_float(latest.get("cs_会话量")),
            latest.get("_month", "unknown"),
            _safe_float(latest.get("cs_询购转化率")),
            _health_status(_safe_float(latest.get("cs_询购转化率")), threshold_low=DEFAULT_THRESHOLDS["inquiry_to_pay_cvr_low"]),
            True,
        ),
        _metric(
            "repurchase_rate",
            "P0",
            "user_portrait.funnel.conversion_rates.N_to_R",
            "user_portrait.funnel.conversion_rates.N_to_R",
            "user_portrait.funnel.N_new_customer",
            repurchase_rate,
            _safe_float((funnel_profile.get("N_new_customer") or {}).get("count")),
            "latest_profile_window",
            repurchase_rate,
            _health_status(repurchase_rate, threshold_low=0.08),
            True,
            {
                "proxy_source": "user_portrait",
                "returning_count": _safe_float((funnel_profile.get("R_returning") or {}).get("count")),
            },
        ),
        _metric(
            "deal_awareness_to_intent_cvr",
            "P1",
            "deal_population_flow.intent / deal_population_flow.awareness",
            "user_asset_signals.deal_population_flow.stages.意向.count",
            "user_asset_signals.deal_population_flow.stages.认知.count",
            deal_intent,
            deal_awareness,
            "deal_analysis_population_flow_latest_30d",
            (deal_intent / deal_awareness) if (deal_intent and deal_awareness) else None,
            _health_status((deal_intent / deal_awareness) if (deal_intent and deal_awareness) else None, threshold_low=0.45),
            True,
            {"status": deal_flow.get("status"), "data_date": deal_flow.get("data_date")},
        ),
        _metric(
            "deal_intent_to_new_cvr",
            "P1",
            "deal_population_flow.new_customer / deal_population_flow.intent",
            "user_asset_signals.deal_population_flow.stages.新客.count",
            "user_asset_signals.deal_population_flow.stages.意向.count",
            deal_new,
            deal_intent,
            "deal_analysis_population_flow_latest_30d",
            (deal_new / deal_intent) if (deal_new and deal_intent) else None,
            _health_status((deal_new / deal_intent) if (deal_new and deal_intent) else None, threshold_low=0.01),
            True,
            {"status": deal_flow.get("status"), "data_date": deal_flow.get("data_date")},
        ),
        _metric(
            "deal_new_to_returning_cvr",
            "P1",
            "deal_population_flow.returning / deal_population_flow.new_customer",
            "user_asset_signals.deal_population_flow.stages.老客.count",
            "user_asset_signals.deal_population_flow.stages.新客.count",
            deal_returning,
            deal_new,
            "deal_analysis_population_flow_latest_30d",
            (deal_returning / deal_new) if (deal_returning is not None and deal_new) else None,
            _health_status((deal_returning / deal_new) if (deal_returning is not None and deal_new) else None, threshold_low=0.03),
            True,
            {"status": deal_flow.get("status"), "data_date": deal_flow.get("data_date")},
        ),
        _metric(
            "deal_returning_churn_rate",
            "P1",
            "deal_population_flow.churn / (deal_population_flow.returning + deal_population_flow.churn)",
            "user_asset_signals.deal_population_flow.stages.流失.count",
            "user_asset_signals.deal_population_flow.stages.老客.count + 流失.count",
            deal_churn,
            (deal_returning or 0.0) + (deal_churn or 0.0),
            "deal_analysis_population_flow_latest_30d",
            (deal_churn / ((deal_returning or 0.0) + (deal_churn or 0.0)))
            if (deal_churn is not None and ((deal_returning or 0.0) + (deal_churn or 0.0)) > 0)
            else None,
            _health_status(
                (deal_churn / ((deal_returning or 0.0) + (deal_churn or 0.0)))
                if (deal_churn is not None and ((deal_returning or 0.0) + (deal_churn or 0.0)) > 0)
                else None,
                threshold_high=0.30,
            ),
            False,
            {"status": deal_flow.get("status"), "data_date": deal_flow.get("data_date")},
        ),
        _metric(
            "aipl_interest_to_new_cvr",
            "P2",
            "aipl_assets.new / aipl_assets.interest",
            "user_asset_signals.aipl_assets.stages.N.count",
            "user_asset_signals.aipl_assets.stages.I.count",
            aipl_new,
            aipl_interest,
            "aipl_assets_latest_30d",
            (aipl_new / aipl_interest) if (aipl_new and aipl_interest) else None,
            _health_status((aipl_new / aipl_interest) if (aipl_new and aipl_interest) else None, threshold_low=0.01),
            False,
            {"status": aipl_assets.get("status"), "data_date": aipl_assets.get("data_date")},
        ),
        _metric(
            "aipl_new_to_returning_cvr",
            "P2",
            "aipl_assets.returning / aipl_assets.new",
            "user_asset_signals.aipl_assets.stages.R.count",
            "user_asset_signals.aipl_assets.stages.N.count",
            aipl_returning,
            aipl_new,
            "aipl_assets_latest_30d",
            (aipl_returning / aipl_new) if (aipl_returning is not None and aipl_new) else None,
            _health_status((aipl_returning / aipl_new) if (aipl_returning is not None and aipl_new) else None, threshold_low=0.03),
            False,
            {"status": aipl_assets.get("status"), "data_date": aipl_assets.get("data_date")},
        ),
        _metric(
            "search_ctr",
            "P1",
            "avg(search.click_rate)",
            "search_terms.rows.click_rate",
            "search_terms.rows.exposure",
            len([value for value in search_ctrs if value is not None]),
            len(search_rows),
            "all_available",
            _median([value for value in search_ctrs if value is not None]),
            _health_status(_median([value for value in search_ctrs if value is not None]), threshold_low=DEFAULT_THRESHOLDS["search_opportunity_ctr"]),
            False,
        ),
        _metric(
            "search_purchase_cvr",
            "P2",
            "avg(search.purchase_cvr)",
            "search_terms.rows.purchase_cvr",
            "search_terms.rows.clicks",
            len([value for value in search_cvrs if value is not None]),
            len(search_rows),
            "all_available",
            _median([value for value in search_cvrs if value is not None]),
            _health_status(_median([value for value in search_cvrs if value is not None]), threshold_low=0.02),
            False,
        ),
        _metric(
            "service_after_sale_surface_rows",
            "P1",
            "sum(latest_rows(service_after_sale.surfaces.*))",
            "service_after_sale.surfaces.*.row_count",
            "service_after_sale.total_surfaces",
            service_domain.get("total_rows"),
            service_domain.get("total_surfaces"),
            "latest_surface_exports",
            _safe_float(service_domain.get("total_rows")),
            _health_status(_safe_float(service_domain.get("total_rows")), threshold_low=1.0),
            False,
            {"status": service_domain.get("status"), "available_surfaces": service_domain.get("available_surfaces")},
        ),
        _metric(
            "fulfillment_logistics_surface_rows",
            "P1",
            "sum(latest_rows(fulfillment_logistics.surfaces.*))",
            "fulfillment_logistics.surfaces.*.row_count",
            "fulfillment_logistics.total_surfaces",
            fulfillment_domain.get("total_rows"),
            fulfillment_domain.get("total_surfaces"),
            "latest_surface_exports",
            _safe_float(fulfillment_domain.get("total_rows")),
            _health_status(_safe_float(fulfillment_domain.get("total_rows")), threshold_low=1.0),
            False,
            {"status": fulfillment_domain.get("status"), "available_surfaces": fulfillment_domain.get("available_surfaces")},
        ),
        _metric(
            "settlement_ops_surface_rows",
            "P2",
            "sum(latest_rows(settlement_ops.surfaces.*))",
            "settlement_ops.surfaces.*.row_count",
            "settlement_ops.total_surfaces",
            settlement_domain.get("total_rows"),
            settlement_domain.get("total_surfaces"),
            "latest_surface_exports",
            _safe_float(settlement_domain.get("total_rows")),
            _health_status(_safe_float(settlement_domain.get("total_rows")), threshold_low=1.0),
            False,
            {"status": settlement_domain.get("status"), "available_surfaces": settlement_domain.get("available_surfaces")},
        ),
        _metric(
            "creator_exposure_7d",
            "P1",
            "creator_account_panel.exposure",
            "creator_platform.creator_account_panel.exposure",
            "fixed_window_7d",
            creator_panel.get("exposure"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("exposure"),
            _health_status(creator_panel.get("exposure"), threshold_low=10000.0),
            False,
        ),
        _metric(
            "creator_views_7d",
            "P1",
            "creator_account_panel.views",
            "creator_platform.creator_account_panel.views",
            "fixed_window_7d",
            creator_panel.get("views"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("views"),
            _health_status(creator_panel.get("views"), threshold_low=1000.0),
            False,
        ),
        _metric(
            "creator_cover_ctr_7d",
            "P1",
            "creator_account_panel.cover_ctr",
            "creator_platform.creator_account_panel.cover_ctr",
            "fixed_window_7d",
            creator_panel.get("cover_ctr"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("cover_ctr"),
            _health_status(creator_panel.get("cover_ctr"), threshold_low=0.06),
            True,
        ),
        _metric(
            "creator_completion_rate_7d",
            "P1",
            "creator_account_panel.completion_rate",
            "creator_platform.creator_account_panel.completion_rate",
            "fixed_window_7d",
            creator_panel.get("completion_rate"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("completion_rate"),
            _health_status(creator_panel.get("completion_rate"), threshold_low=0.20),
            True,
        ),
        _metric(
            "creator_engagement_actions_7d",
            "P1",
            "likes + comments + saves + shares",
            "creator_platform.creator_account_panel.engagement_actions",
            "fixed_window_7d",
            creator_panel.get("engagement_actions"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("engagement_actions"),
            _health_status(creator_panel.get("engagement_actions"), threshold_low=50.0),
            True,
        ),
        _metric(
            "creator_homepage_visitors_7d",
            "P1",
            "creator_account_panel.homepage_visitors",
            "creator_platform.creator_account_panel.homepage_visitors",
            "fixed_window_7d",
            creator_panel.get("homepage_visitors"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("homepage_visitors"),
            _health_status(creator_panel.get("homepage_visitors"), threshold_low=100.0),
            True,
        ),
        _metric(
            "creator_net_followers_7d",
            "P1",
            "creator_account_panel.net_followers",
            "creator_platform.creator_account_panel.net_followers",
            "fixed_window_7d",
            creator_panel.get("net_followers"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("net_followers"),
            _health_status(creator_panel.get("net_followers"), threshold_low=-5.0),
            False,
        ),
        _metric(
            "creator_new_follows_7d",
            "P1",
            "creator_account_panel.new_follows",
            "creator_platform.creator_account_panel.new_follows",
            "fixed_window_7d",
            creator_panel.get("new_follows"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("new_follows"),
            _health_status(creator_panel.get("new_follows"), threshold_low=5.0),
            False,
        ),
        _metric(
            "creator_unfollows_7d",
            "P1",
            "creator_account_panel.unfollows",
            "creator_platform.creator_account_panel.unfollows",
            "fixed_window_7d",
            creator_panel.get("unfollows"),
            1,
            "creator_home_last_7_days",
            creator_panel.get("unfollows"),
            _health_status(creator_panel.get("unfollows"), threshold_high=20.0),
            False,
        ),
        _metric(
            "recent_note_count_30d",
            "P1",
            "count(creator_note_inventory.rows)",
            "creator_platform.creator_note_inventory.rows",
            "fixed_window_30d",
            len(note_rows),
            1,
            "creator_note_manager_last_30_days",
            float(len(note_rows)),
            _health_status(float(len(note_rows)), threshold_low=4.0),
            True,
        ),
        _metric(
            "recent_note_median_views",
            "P1",
            "median(creator_note_inventory.rows.views)",
            "creator_platform.creator_note_inventory.rows.views",
            "recent_note_count_30d",
            len(note_rows),
            max(len(note_rows), 1),
            "creator_note_manager_last_30_days",
            _median([value for value in note_views if value is not None]),
            _health_status(_median([value for value in note_views if value is not None]), threshold_low=300.0),
            True,
        ),
        _metric(
            "recent_note_median_saves",
            "P2",
            "median(creator_note_inventory.rows.saves)",
            "creator_platform.creator_note_inventory.rows.saves",
            "recent_note_count_30d",
            len(note_rows),
            max(len(note_rows), 1),
            "creator_note_manager_last_30_days",
            _median([value for value in note_saves if value is not None]),
            _health_status(_median([value for value in note_saves if value is not None]), threshold_low=5.0),
            True,
        ),
        _metric(
            "recent_note_median_comments",
            "P2",
            "median(creator_note_inventory.rows.comments)",
            "creator_platform.creator_note_inventory.rows.comments",
            "recent_note_count_30d",
            len(note_rows),
            max(len(note_rows), 1),
            "creator_note_manager_last_30_days",
            _median([value for value in note_comments if value is not None]),
            _health_status(_median([value for value in note_comments if value is not None]), threshold_low=1.0),
            True,
        ),
        _metric(
            "recent_note_median_shares",
            "P2",
            "median(creator_note_inventory.rows.shares)",
            "creator_platform.creator_note_inventory.rows.shares",
            "recent_note_count_30d",
            len(note_rows),
            max(len(note_rows), 1),
            "creator_note_manager_last_30_days",
            _median([value for value in note_shares if value is not None]),
            _health_status(_median([value for value in note_shares if value is not None]), threshold_low=1.0),
            True,
        ),
        _metric(
            "recent_note_top_view_note",
            "P2",
            "top note by views",
            "creator_platform.creator_note_inventory.rows.views",
            "recent_note_count_30d",
            top_view_note.get("views") if top_view_note else None,
            len(note_rows),
            "creator_note_manager_last_30_days",
            top_view_note.get("views") if top_view_note else None,
            _health_status(top_view_note.get("views") if top_view_note else None, threshold_low=500.0),
            False,
            {"note_title": (top_view_note or {}).get("title"), "published_at": (top_view_note or {}).get("published_at")},
        ),
        _metric(
            "recent_note_top_save_note",
            "P2",
            "top note by saves",
            "creator_platform.creator_note_inventory.rows.saves",
            "recent_note_count_30d",
            top_save_note.get("saves") if top_save_note else None,
            len(note_rows),
            "creator_note_manager_last_30_days",
            top_save_note.get("saves") if top_save_note else None,
            _health_status(top_save_note.get("saves") if top_save_note else None, threshold_low=5.0),
            False,
            {"note_title": (top_save_note or {}).get("title"), "published_at": (top_save_note or {}).get("published_at")},
        ),
        _metric(
            "creator_note_data_freshness_days",
            "P1",
            "days_since(creator_note_manager_capture)",
            "creator_platform.freshness.creator_note_manager_days",
            "clock.now",
            creator_note_freshness_days,
            1,
            "current_run",
            creator_note_freshness_days,
            _health_status(creator_note_freshness_days, threshold_high=DEFAULT_THRESHOLDS["creator_note_manager_stale_days"]),
            True,
        ),
        _metric(
            "creator_home_data_freshness_days",
            "P1",
            "days_since(creator_home_capture)",
            "creator_platform.freshness.creator_home_days",
            "clock.now",
            creator_home_freshness_days,
            1,
            "current_run",
            creator_home_freshness_days,
            _health_status(creator_home_freshness_days, threshold_high=DEFAULT_THRESHOLDS["creator_home_stale_days"]),
            True,
        ),
        _metric(
            "creator_visual_chart_nodes",
            "P2",
            "sum(creator_platform.visual_signals.*.chart_node_count)",
            "creator_platform.visual_signals.*.chart_node_count",
            "clock.now",
            creator_chart_nodes,
            1,
            "current_run",
            creator_chart_nodes,
            _health_status(creator_chart_nodes, threshold_low=1.0),
            False,
            {
                "creator_home_chart_nodes": float(creator_home_visual.get("chart_node_count", 0) or 0),
                "creator_note_manager_chart_nodes": float(creator_note_visual.get("chart_node_count", 0) or 0),
                "creator_events_chart_nodes": float(creator_events_visual.get("chart_node_count", 0) or 0),
                "creator_inspiration_chart_nodes": float(creator_inspiration_visual.get("chart_node_count", 0) or 0),
            },
        ),
        _metric(
            "creator_visual_numeric_signals",
            "P2",
            "len(creator_home.numeric_text_samples) + len(creator_note_manager.numeric_text_samples)",
            "creator_platform.visual_signals.*.numeric_text_samples",
            "clock.now",
            creator_numeric_signal_count,
            1,
            "current_run",
            creator_numeric_signal_count,
            _health_status(creator_numeric_signal_count, threshold_low=3.0),
            False,
        ),
        _metric(
            "creator_event_active_count_mtd",
            "P1",
            "count(creator_events_board.events)",
            "creator_platform.creator_events_board.events",
            "fixed_window_mtd",
            creator_events.get("active_event_count"),
            1,
            "creator_events_current_window",
            _safe_float(creator_events.get("active_event_count")),
            _health_status(_safe_float(creator_events.get("active_event_count")), threshold_low=1.0),
            True,
        ),
        _metric(
            "creator_event_start_within_7d_count",
            "P1",
            "count(events with start date within 7 days)",
            "creator_platform.creator_events_board.events_start_within_7d",
            "fixed_window_7d",
            creator_events.get("events_start_within_7d"),
            1,
            "creator_events_current_window",
            _safe_float(creator_events.get("events_start_within_7d")),
            _health_status(_safe_float(creator_events.get("events_start_within_7d")), threshold_low=1.0),
            True,
        ),
        _metric(
            "creator_inspiration_topic_count_mtd",
            "P1",
            "count(creator_inspiration_board.topics)",
            "creator_platform.creator_inspiration_board.topics",
            "fixed_window_mtd",
            creator_inspiration.get("topic_count"),
            1,
            "creator_inspiration_current_window",
            _safe_float(creator_inspiration.get("topic_count")),
            _health_status(_safe_float(creator_inspiration.get("topic_count")), threshold_low=3.0),
            True,
        ),
        _metric(
            "creator_inspiration_high_heat_topic_count",
            "P2",
            "count(topic.views>=1e8 or participants>=1e5)",
            "creator_platform.creator_inspiration_board.high_heat_topic_count",
            "fixed_window_mtd",
            creator_inspiration.get("high_heat_topic_count"),
            1,
            "creator_inspiration_current_window",
            _safe_float(creator_inspiration.get("high_heat_topic_count")),
            _health_status(_safe_float(creator_inspiration.get("high_heat_topic_count")), threshold_low=1.0),
            True,
        ),
        _metric(
            "creator_events_data_freshness_days",
            "P1",
            "days_since(creator_events_capture)",
            "creator_platform.freshness.creator_events_days",
            "clock.now",
            creator_events_freshness_days,
            1,
            "current_run",
            creator_events_freshness_days,
            _health_status(creator_events_freshness_days, threshold_high=35.0),
            True,
        ),
        _metric(
            "creator_inspiration_data_freshness_days",
            "P1",
            "days_since(creator_inspiration_capture)",
            "creator_platform.freshness.creator_inspiration_days",
            "clock.now",
            creator_inspiration_freshness_days,
            1,
            "current_run",
            creator_inspiration_freshness_days,
            _health_status(creator_inspiration_freshness_days, threshold_high=35.0),
            True,
        ),
    ]

    metrics = apply_metric_stabilization(metrics)

    registry = {
        "schema_version": "1.0.0",
        "object_type": "metric_registry",
        "registry_id": deterministic_id("registry", snapshot_id, "metrics"),
        "created_at": latest.get("_month", snapshot_id),
        "metrics": metrics,
        "source_of_truth": "normalized first_party business health, funnel, search, creator_platform",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("metric_registry", registry)
    return registry
