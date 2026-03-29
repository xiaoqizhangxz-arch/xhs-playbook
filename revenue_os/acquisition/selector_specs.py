from __future__ import annotations

from dataclasses import asdict, dataclass

from revenue_os.acquisition.creator_catalog import CREATOR_SURFACES
from revenue_os.acquisition.proof_registry import is_surface_proven
from revenue_os.acquisition.surface_catalog import SURFACES


@dataclass(frozen=True)
class SelectorSpec:
    source_system: str
    surface_name: str
    route_url: str
    selector_status: str
    export_strategy: str
    date_window_strategy: str
    expected_filename_signatures: tuple[str, ...]
    parser_target: str
    cadence_gate: str
    proof_status: str
    last_known_proof: str | None
    notes: str


_PARSER_TARGET_OVERRIDES: dict[str, str] = {
    "business_summary": "monthly_business_health",
    "shop_overview": "shop_overview",
    "shop_funnel": "shop_funnel",
    "shop_entry_source": "shop_entry_source",
    "search_overview": "search_overview",
    "search_terms": "search_terms",
    "sku_detail": "sku_performance",
    "spec_detail": "sku_spec_performance",
    "order_detail": "order_detail",
    "refund_data": "refund_data",
    "refund_analysis": "refund_analysis",
    "reviews": "reviews",
    "product_note_data": "product_note_data",
    "product_note_traffic": "product_note_traffic",
    "creator_home": "creator_account_panel",
    "creator_note_manager": "creator_note_inventory",
    "creator_events": "creator_events",
    "creator_inspiration": "creator_inspiration",
}

_SIGNATURE_OVERRIDES: dict[str, tuple[str, ...]] = {
    "business_summary": ("商家经营核心数据汇总",),
    "shop_overview": ("店铺页数据总览",),
    "shop_funnel": ("店铺页转化漏斗",),
    "shop_entry_source": ("店铺页进店来源",),
    "search_terms": ("搜索词",),
    "product_note_data": ("商品笔记数据",),
    "product_note_traffic": ("商品笔记流量",),
    "deal_analysis": ("成交分析",),
    "aipl_assets": ("用户资产", "AIPL"),
    "creator_home": ("创作中心", "数据总览"),
    "creator_note_manager": ("笔记管理", "作品数据"),
    "creator_events": ("活动中心",),
    "creator_inspiration": ("创作灵感",),
}


def _window_strategy(window: str) -> str:
    mapping = {
        "mtd": "mtd_picker",
        "last_7_days": "rolling_7d_picker",
        "last_30_days": "rolling_30d_picker",
        "natural_month": "natural_month_picker",
    }
    return mapping.get(window, "default_picker")


def _export_strategy(export_format: str) -> str:
    if export_format == "pdf":
        return "official_pdf_export"
    if export_format == "json":
        return "browser_context_capture"
    if export_format == "mixed":
        return "official_export_or_browser_capture"
    return "official_export_button"


def _fallback_signatures(surface_name: str, route_subdir: str) -> tuple[str, ...]:
    normalized = surface_name.replace("_", "")
    return (route_subdir, surface_name, normalized)


def _parser_target(surface_name: str, business_role: str) -> str:
    override = _PARSER_TARGET_OVERRIDES.get(surface_name)
    if override:
        return override
    cleaned = (
        business_role.lower()
        .replace("/", "_")
        .replace("-", "_")
        .replace(" ", "_")
    )
    return cleaned


def _qianfan_selector_specs() -> list[SelectorSpec]:
    specs: list[SelectorSpec] = []
    for surface in SURFACES:
        specs.append(
            SelectorSpec(
                source_system="qianfan",
                surface_name=surface.name,
                route_url=surface.source_url,
                selector_status="mapped" if surface.proof_status == "proven" else "planned",
                export_strategy=_export_strategy(surface.export_format),
                date_window_strategy=_window_strategy(surface.default_window),
                expected_filename_signatures=_SIGNATURE_OVERRIDES.get(
                    surface.name,
                    _fallback_signatures(surface.name, surface.route_subdir),
                ),
                parser_target=_parser_target(surface.name, surface.business_role),
                cadence_gate="requires_live_proof",
                proof_status=surface.proof_status,
                last_known_proof=surface.last_known_proof_run_id,
                notes=f"{surface.navigation_hint}; wave={surface.wave}; priority={surface.priority}",
            )
        )
    return specs


def _creator_selector_specs() -> list[SelectorSpec]:
    specs: list[SelectorSpec] = []
    for surface in CREATOR_SURFACES:
        specs.append(
            SelectorSpec(
                source_system="creator",
                surface_name=surface.name,
                route_url=surface.route_url,
                selector_status="mapped" if surface.proof_status == "proven" else "planned",
                export_strategy=_export_strategy(surface.export_format),
                date_window_strategy=_window_strategy(surface.default_window),
                expected_filename_signatures=_SIGNATURE_OVERRIDES.get(
                    surface.name,
                    _fallback_signatures(surface.name, surface.route_subdir),
                ),
                parser_target=_parser_target(surface.name, surface.business_role),
                cadence_gate="requires_live_proof",
                proof_status=surface.proof_status,
                last_known_proof=None,
                notes=surface.notes,
            )
        )
    return specs


SELECTOR_SPECS: tuple[SelectorSpec, ...] = tuple(_qianfan_selector_specs() + _creator_selector_specs())


def get_selector_spec(surface_name: str) -> SelectorSpec | None:
    for spec in SELECTOR_SPECS:
        if spec.surface_name == surface_name:
            return spec
    return None


def selector_specs_for_source(source_system: str) -> list[SelectorSpec]:
    return [spec for spec in SELECTOR_SPECS if spec.source_system == source_system]


def selector_coverage_report() -> dict[str, dict[str, int]]:
    report: dict[str, dict[str, int]] = {}
    for source in ("qianfan", "creator"):
        specs = selector_specs_for_source(source)
        report[source] = {
            "total": len(specs),
            "mapped": sum(1 for spec in specs if spec.selector_status == "mapped"),
            "planned": sum(1 for spec in specs if spec.selector_status == "planned"),
            "proven": sum(
                1
                for spec in specs
                if is_surface_proven(spec.source_system, spec.surface_name, spec.proof_status)
            ),
        }
    return report


def selector_specs_as_dicts(source_system: str | None = None) -> list[dict[str, object]]:
    items = SELECTOR_SPECS if source_system is None else tuple(selector_specs_for_source(source_system))
    return [asdict(item) for item in items]
