from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from revenue_os.acquisition.proof_registry import is_surface_proven


ARK_HOME_URL = "https://ark.xiaohongshu.com/app-system/home"
DATACENTER_OVERVIEW_URL = "https://ark.xiaohongshu.com/app-datacenter/overview"
FLOW_OVERVIEW_URL = "https://ark.xiaohongshu.com/app-datacenter/flow-overview"
BUSINESS_OVERVIEW_URL = "https://ark.xiaohongshu.com/app-datacenter/business-overview"
BUSINESS_ORDER_URL = "https://ark.xiaohongshu.com/app-datacenter/business-order"
BUSINESS_REFUND_URL = "https://ark.xiaohongshu.com/app-datacenter/business-refund/pay-time"
BUSINESS_ACCOUNT_URL = "https://ark.xiaohongshu.com/app-datacenter/business-account"
SEARCH_OVERVIEW_URL = "https://ark.xiaohongshu.com/app-datacenter/search-overview"
SEARCH_WORDS_URL = "https://ark.xiaohongshu.com/app-datacenter/search-overview/words"
HOMEPAGE_URL = "https://ark.xiaohongshu.com/app-datacenter/homepage"
GOODS_BASE_URL = "https://ark.xiaohongshu.com/app-datacenter/good-data"
GOODS_CATEGORY_URL = "https://ark.xiaohongshu.com/app-datacenter/good-data/category-analysis"
GOODS_REALTIME_URL = "https://ark.xiaohongshu.com/app-datacenter/good-data/real-time"
NOTE_GOODS_URL = "https://ark.xiaohongshu.com/app-datacenter/note-data/goods"
NOTE_BLUE_CHAIN_URL = "https://ark.xiaohongshu.com/app-datacenter/note-blue-chain"
NOTE_COOPERATE_URL = "https://ark.xiaohongshu.com/app-datacenter/note-cooperate"
COMMENT_URL = "https://ark.xiaohongshu.com/app-datacenter/comment-overview"
CUSTOMER_DATA_URL = "https://ark.xiaohongshu.com/app-datacenter/customer-data"
LOGISTICS_DATA_URL = "https://ark.xiaohongshu.com/app-datacenter/logistics-data"
AFTER_SALE_DATA_URL = "https://ark.xiaohongshu.com/app-datacenter/after-sale"
GROUP_CHAT_URL = "https://ark.xiaohongshu.com/app-datacenter/group-chat"
MARKET_NOTE_RANK_URL = "https://ark.xiaohongshu.com/app-datacenter/market/note-rank"
MARKET_LIVE_RANK_URL = "https://ark.xiaohongshu.com/app-datacenter/market/live-rank"
MARKETING_TOOL_URL = "https://ark.xiaohongshu.com/app-datacenter/marketing/tool"
MARKETING_PLAY_URL = "https://ark.xiaohongshu.com/app-datacenter/marketing/tool/play"
USER_ASSETS_URL = "https://ark.xiaohongshu.com/app-promotion/user-assets"
USER_DATA_URL = "https://ark.xiaohongshu.com/app-circle/user-data"
DISPATCHING_URL = "https://ark.xiaohongshu.com/app-order/partner/dispatching"
ORDER_QUERY_URL = "https://ark.xiaohongshu.com/app-order/order/query"
AFTERSALE_MANAGE_URL = "https://ark.xiaohongshu.com/app-order/aftersale/list"
SHELF_GOODS_URL = "https://ark.xiaohongshu.com/app-item/list/shelf"
SETTLEMENT_FUNDS_URL = "https://ark.xiaohongshu.com/app-merchant/third-settle/account"
PENDING_SETTLE_URL = "https://ark.xiaohongshu.com/app-merchant/pending-settle"
DEPOSIT_CATEGORY_URL = "https://ark.xiaohongshu.com/app-violation/deposit/category-base-list"


@dataclass(frozen=True)
class SurfaceSpec:
    name: str
    route_family: str
    route_subdir: str
    export_format: str
    default_window: str
    cadence_modes: tuple[str, ...]
    source_url: str
    navigation_hint: str
    expected_extensions: tuple[str, ...]
    priority: str
    business_role: str
    wave: str
    freshness_threshold_days: int
    blocking_severity: str
    proof_status: str
    selector_spec_key: str
    last_known_proof_run_id: str | None = None

    @property
    def eligible_for_cadence(self) -> bool:
        return self.proof_status == "proven"


def _s(
    name: str,
    route_family: str,
    route_subdir: str,
    export_format: str,
    default_window: str,
    cadence_modes: tuple[str, ...],
    source_url: str,
    navigation_hint: str,
    expected_extensions: tuple[str, ...],
    priority: str,
    business_role: str,
    wave: str,
    freshness_threshold_days: int,
    blocking_severity: str,
    proof_status: str,
    last_known_proof_run_id: str | None = None,
) -> SurfaceSpec:
    return SurfaceSpec(
        name=name,
        route_family=route_family,
        route_subdir=route_subdir,
        export_format=export_format,
        default_window=default_window,
        cadence_modes=cadence_modes,
        source_url=source_url,
        navigation_hint=navigation_hint,
        expected_extensions=expected_extensions,
        priority=priority,
        business_role=business_role,
        wave=wave,
        freshness_threshold_days=freshness_threshold_days,
        blocking_severity=blocking_severity,
        proof_status=proof_status,
        selector_spec_key=f"qianfan::{name}",
        last_known_proof_run_id=last_known_proof_run_id,
    )


SURFACES: tuple[SurfaceSpec, ...] = (
    _s("account_overview", "source_auto", "账号总览", "xlsx", "mtd", ("daily", "monthly"), BUSINESS_ACCOUNT_URL, "账号总览数据", (".xlsx",), "P0", "account overview", "core", 2, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("business_summary", "source_auto", "商家经营汇总", "xlsx", "mtd", ("daily", "monthly"), DATACENTER_OVERVIEW_URL, "商家经营核心数据汇总", (".xlsx",), "P0", "business summary", "core", 2, "red", "proven", "acqrun__87051f2bd2ad"),
    _s("business_orders", "source_auto", "商家成交", "xlsx", "natural_month", ("monthly",), BUSINESS_OVERVIEW_URL, "商家成交数据概览-all", (".xlsx",), "P0", "commerce overview", "core", 35, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("business_traffic", "source_auto", "商家流量", "xlsx", "natural_month", ("monthly",), FLOW_OVERVIEW_URL, "商家流量数据", (".xlsx",), "P1", "traffic summary", "core", 35, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("shop_overview", "source_auto", "店铺页", "xlsx", "last_30_days", ("daily", "weekly"), HOMEPAGE_URL, "店铺页数据总览", (".xlsx",), "P0", "shop overview", "core", 7, "red", "proven", "acqrun__87051f2bd2ad"),
    _s("shop_funnel", "source_auto", "店铺页", "xlsx", "last_30_days", ("weekly",), HOMEPAGE_URL, "店铺页转化漏斗", (".xlsx",), "P0", "conversion funnel", "core", 8, "red", "proven", "acqrun__87051f2bd2ad"),
    _s("shop_entry_source", "source_auto", "店铺页", "xlsx", "last_30_days", ("weekly",), HOMEPAGE_URL, "店铺页进店来源", (".xlsx",), "P1", "traffic source mix", "core", 8, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("search_overview", "source_auto", "搜索", "xlsx", "mtd", ("daily", "monthly"), SEARCH_OVERVIEW_URL, "搜索总览数据", (".xlsx",), "P1", "search overview", "core", 2, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("search_terms", "source_auto", "搜索", "xlsx", "last_30_days", ("weekly", "monthly"), SEARCH_WORDS_URL, "搜索词数据", (".xlsx",), "P0", "search keyword performance", "core", 8, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("sku_detail", "source_auto", "商品明细", "xlsx", "natural_month", ("monthly",), GOODS_BASE_URL, "商品明细数据下载", (".xlsx",), "P1", "sku performance", "core", 35, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("spec_detail", "source_auto", "规格明细", "xlsx", "natural_month", ("monthly",), GOODS_BASE_URL, "规格明细数据下载", (".xlsx",), "P1", "spec performance", "core", 35, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("order_detail", "source_auto", "订单明细", "xlsx", "natural_month", ("monthly",), BUSINESS_ORDER_URL, "订单明细数据", (".xlsx",), "P1", "order detail", "core", 35, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("refund_data", "source_auto", "退款数据", "xlsx", "last_30_days", ("weekly", "monthly"), BUSINESS_REFUND_URL, "商家退款数据数据-all", (".xlsx",), "P0", "refund health", "core", 8, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("refund_analysis", "source_auto", "退款分析", "xlsx", "natural_month", ("monthly",), BUSINESS_REFUND_URL, "退款分析(支付时间)-退款概览", (".xlsx",), "P0", "refund analysis", "core", 35, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("reviews", "source_auto", "评价", "xlsx", "last_30_days", ("weekly", "monthly"), COMMENT_URL, "评价数据商品明细下载", (".xlsx",), "P1", "reviews and proof", "core", 8, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("product_note_data", "source_auto", "商品笔记数据", "xlsx", "last_30_days", ("weekly", "monthly"), NOTE_GOODS_URL, "商品笔记数据-", (".xlsx",), "P1", "content to commerce", "core", 8, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("product_note_traffic", "source_auto", "商品笔记流量", "xlsx", "mtd", ("daily", "monthly"), NOTE_GOODS_URL, "商品笔记-账号流量数据列表", (".xlsx",), "P1", "note traffic", "core", 2, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("aipl_assets", "users_auto", "千帆AIPL", "pdf", "natural_month", ("monthly",), USER_ASSETS_URL, "用户资产/用户画像 AIPL", (".pdf",), "P2", "user asset portrait", "D", 35, "warning", "planned"),
    _s("deal_analysis", "users_auto", "成交分析", "pdf", "natural_month", ("monthly",), BUSINESS_OVERVIEW_URL, "成交分析 PDF", (".pdf",), "P1", "commerce pdf report", "core", 35, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("customer_data", "source_auto", "客服数据", "xlsx", "last_30_days", ("weekly", "monthly"), CUSTOMER_DATA_URL, "客服数据", (".xlsx",), "P0", "service conversion", "A", 8, "warning", "planned"),
    _s("logistics_data", "source_auto", "物流数据", "xlsx", "last_30_days", ("weekly", "monthly"), LOGISTICS_DATA_URL, "物流数据", (".xlsx",), "P0", "fulfillment risk", "A", 8, "warning", "planned"),
    _s("after_sale_data", "source_auto", "售后数据", "xlsx", "last_30_days", ("weekly", "monthly"), AFTER_SALE_DATA_URL, "售后数据", (".xlsx",), "P0", "after sale diagnosis", "A", 8, "warning", "planned"),
    _s("group_chat_data", "source_auto", "群聊数据", "xlsx", "last_30_days", ("weekly",), GROUP_CHAT_URL, "群聊数据", (".xlsx",), "P2", "community ops", "D", 8, "warning", "planned"),
    _s("market_note_rank", "source_auto", "市场行情", "xlsx", "last_30_days", ("weekly",), MARKET_NOTE_RANK_URL, "市场行情-笔记排行", (".xlsx",), "P1", "market benchmark notes", "B", 8, "warning", "planned"),
    _s("market_live_rank", "source_auto", "市场行情", "xlsx", "last_30_days", ("weekly",), MARKET_LIVE_RANK_URL, "市场行情-直播排行", (".xlsx",), "P2", "market benchmark live", "B", 8, "warning", "planned"),
    _s("marketing_tool", "source_auto", "营销数据", "xlsx", "mtd", ("daily", "weekly"), MARKETING_TOOL_URL, "营销数据工具", (".xlsx",), "P2", "marketing ops", "core", 2, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("marketing_tool_play", "source_auto", "营销数据", "xlsx", "last_30_days", ("weekly",), MARKETING_PLAY_URL, "营销数据-营销玩法", (".xlsx",), "P2", "marketing playbook", "core", 8, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("datacenter_overview", "source_auto", "数据总览", "xlsx", "mtd", ("daily", "weekly", "monthly"), DATACENTER_OVERVIEW_URL, "数据总览", (".xlsx",), "P1", "datacenter overview", "core", 2, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("category_analysis", "source_auto", "商家类目", "xlsx", "natural_month", ("monthly",), GOODS_CATEGORY_URL, "类目分析", (".xlsx",), "P1", "category analysis", "core", 35, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("good_data_realtime", "source_auto", "实时商品数据", "xlsx", "mtd", ("daily", "weekly"), GOODS_REALTIME_URL, "实时商品数据", (".xlsx",), "P1", "realtime sku health", "B", 2, "warning", "planned"),
    _s("note_blue_chain", "source_auto", "买手笔记", "xlsx", "last_30_days", ("weekly",), NOTE_BLUE_CHAIN_URL, "买手笔记", (".xlsx",), "P1", "buyer note leverage", "core", 8, "warning", "proven", "acqrun__87051f2bd2ad"),
    _s("note_cooperate", "source_auto", "买手笔记", "xlsx", "last_30_days", ("weekly",), NOTE_COOPERATE_URL, "买手笔记合作", (".xlsx",), "P1", "creator cooperation", "B", 8, "warning", "planned"),
    _s("user_data", "source_auto", "用户数据", "xlsx", "natural_month", ("monthly",), USER_DATA_URL, "用户数据", (".xlsx",), "P2", "retention cohort", "D", 35, "warning", "planned"),
    _s("dispatching_center", "source_auto", "发货中心", "xlsx", "last_30_days", ("weekly", "monthly"), DISPATCHING_URL, "发货中心", (".xlsx",), "P0", "dispatch status", "A", 8, "warning", "planned"),
    _s("order_query", "source_auto", "订单查询", "xlsx", "last_30_days", ("weekly",), ORDER_QUERY_URL, "订单查询", (".xlsx",), "P2", "merchant ops detail", "C", 8, "warning", "planned"),
    _s("shelf_goods", "source_auto", "售卖中商品", "xlsx", "mtd", ("daily", "weekly"), SHELF_GOODS_URL, "售卖中商品", (".xlsx",), "P1", "sku availability", "B", 2, "warning", "planned"),
    _s("aftersale_manage", "source_auto", "售后管理", "xlsx", "last_30_days", ("weekly", "monthly"), AFTERSALE_MANAGE_URL, "售后管理", (".xlsx",), "P0", "after-sale operations", "A", 8, "warning", "planned"),
    _s("settlement_funds", "source_auto", "货款资金", "xlsx", "natural_month", ("monthly",), SETTLEMENT_FUNDS_URL, "货款资金", (".xlsx",), "P2", "settlement risk", "C", 35, "warning", "planned"),
    _s("pending_settle_orders", "source_auto", "待结算订单", "xlsx", "natural_month", ("monthly",), PENDING_SETTLE_URL, "待结算订单", (".xlsx",), "P2", "settlement queue", "C", 35, "warning", "planned"),
    _s("deposit_category_base", "source_auto", "保证金明细", "xlsx", "natural_month", ("monthly",), DEPOSIT_CATEGORY_URL, "类目基础保证金明细", (".xlsx",), "P2", "merchant compliance", "C", 35, "warning", "planned")
)


def get_surface(name: str) -> SurfaceSpec:
    for surface in SURFACES:
        if surface.name == name:
            return surface
    raise KeyError(f"Unknown surface: {name}")


def surfaces_for_mode(mode: str) -> list[SurfaceSpec]:
    return [surface for surface in SURFACES if mode in surface.cadence_modes]


def cadence_surfaces_for_mode(mode: str) -> list[SurfaceSpec]:
    return [surface for surface in surfaces_for_mode(mode) if is_qianfan_surface_proven(surface)]


def route_root_name(surface: SurfaceSpec) -> str:
    return surface.route_family


def all_surface_names() -> list[str]:
    return [surface.name for surface in SURFACES]


def surface_names_by_wave(wave: str) -> list[str]:
    return [surface.name for surface in SURFACES if surface.wave == wave]


def iter_missing_surfaces() -> Iterable[SurfaceSpec]:
    return [surface for surface in SURFACES if not is_qianfan_surface_proven(surface)]


def is_qianfan_surface_proven(surface: SurfaceSpec) -> bool:
    return is_surface_proven("qianfan", surface.name, surface.proof_status)


def unproven_surfaces_for_mode(mode: str, wave: str = "all") -> list[SurfaceSpec]:
    items = [surface for surface in surfaces_for_mode(mode) if not is_qianfan_surface_proven(surface)]
    if wave == "all":
        return items
    return [surface for surface in items if surface.wave == wave]
