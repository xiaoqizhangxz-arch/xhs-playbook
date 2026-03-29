from __future__ import annotations

from dataclasses import dataclass

from revenue_os.acquisition.proof_registry import is_surface_proven


CREATOR_HOME_URL = "https://creator.xiaohongshu.com/new/home"
CREATOR_NOTE_MANAGER_URL = "https://creator.xiaohongshu.com/new/note-manager"
CREATOR_EVENTS_URL = "https://creator.xiaohongshu.com/new/events"
CREATOR_INSPIRATION_URL = "https://creator.xiaohongshu.com/new/inspiration"


@dataclass(frozen=True)
class CreatorSurfaceSpec:
    name: str
    route_family: str
    route_subdir: str
    export_format: str
    default_window: str
    cadence_modes: tuple[str, ...]
    source_url: str
    navigation_hint: str
    expected_extensions: tuple[str, ...]
    route_url: str
    priority: str
    business_role: str
    capture_mode: str
    freshness_threshold_days: int
    blocking_severity: str
    proof_status: str
    selector_spec_key: str
    notes: str

    @property
    def eligible_for_cadence(self) -> bool:
        return self.proof_status == "proven"


@dataclass(frozen=True)
class CreatorApiSpec:
    name: str
    path: str
    priority: str
    business_role: str
    requires_browser_context: bool
    notes: str


CREATOR_SURFACES: tuple[CreatorSurfaceSpec, ...] = (
    CreatorSurfaceSpec(
        name="creator_home",
        route_family="creator_auto",
        route_subdir="creator_home",
        export_format="mixed",
        default_window="last_7_days",
        cadence_modes=("daily", "weekly", "monthly"),
        source_url=CREATOR_HOME_URL,
        navigation_hint="创作服务平台首页",
        expected_extensions=(".json", ".xlsx"),
        route_url=CREATOR_HOME_URL,
        priority="P0",
        business_role="account and note performance dashboard",
        capture_mode="browser_context",
        freshness_threshold_days=2,
        blocking_severity="warning",
        proof_status="proven",
        selector_spec_key="creator::creator_home",
        notes="Confirmed reachable with Chrome cookie reuse; contains exposure, views, CTR, completion rate, likes, comments, saves, shares, follower and homepage visitor metrics.",
    ),
    CreatorSurfaceSpec(
        name="creator_note_manager",
        route_family="creator_auto",
        route_subdir="note_manager",
        export_format="mixed",
        default_window="last_30_days",
        cadence_modes=("weekly", "monthly"),
        source_url=CREATOR_NOTE_MANAGER_URL,
        navigation_hint="创作服务平台笔记管理",
        expected_extensions=(".json", ".xlsx"),
        route_url=CREATOR_NOTE_MANAGER_URL,
        priority="P0",
        business_role="note-level content performance inventory",
        capture_mode="browser_context",
        freshness_threshold_days=8,
        blocking_severity="warning",
        proof_status="proven",
        selector_spec_key="creator::creator_note_manager",
        notes="Confirmed reachable; contains note rows with publish time, duration, views, likes, saves, comments, and shares. Phase 1 stores page_count_captured and truncation state.",
    ),
    CreatorSurfaceSpec(
        name="creator_events",
        route_family="creator_auto",
        route_subdir="events",
        export_format="mixed",
        default_window="mtd",
        cadence_modes=("monthly",),
        source_url=CREATOR_EVENTS_URL,
        navigation_hint="创作服务平台活动中心",
        expected_extensions=(".json", ".xlsx"),
        route_url=CREATOR_EVENTS_URL,
        priority="P2",
        business_role="campaign and activity discovery",
        capture_mode="browser_context",
        freshness_threshold_days=35,
        blocking_severity="none",
        proof_status="planned",
        selector_spec_key="creator::creator_events",
        notes="Confirmed reachable via sidebar click, but not yet promoted into cadence until capture proofs and normalization land.",
    ),
    CreatorSurfaceSpec(
        name="creator_inspiration",
        route_family="creator_auto",
        route_subdir="inspiration",
        export_format="mixed",
        default_window="mtd",
        cadence_modes=("monthly",),
        source_url=CREATOR_INSPIRATION_URL,
        navigation_hint="创作服务平台笔记灵感",
        expected_extensions=(".json", ".xlsx"),
        route_url=CREATOR_INSPIRATION_URL,
        priority="P2",
        business_role="content ideation and topic discovery",
        capture_mode="browser_context",
        freshness_threshold_days=35,
        blocking_severity="none",
        proof_status="planned",
        selector_spec_key="creator::creator_inspiration",
        notes="Reachable, but not yet a planner-facing input surface.",
    ),
)


CREATOR_APIS: tuple[CreatorApiSpec, ...] = (
    CreatorApiSpec(
        name="user_info",
        path="/api/galaxy/user/info",
        priority="P0",
        business_role="identity, permissions, account metadata",
        requires_browser_context=False,
        notes="Direct requests with Chrome cookies returned 200.",
    ),
    CreatorApiSpec(
        name="account_base",
        path="/api/galaxy/v2/creator/datacenter/account/base",
        priority="P0",
        business_role="account-level KPI panel",
        requires_browser_context=True,
        notes="Observed 200 in browser context, but direct requests returned 406 due to request-signing headers.",
    ),
    CreatorApiSpec(
        name="latest_note_data",
        path="/api/galaxy/creator/home/latest_note_data",
        priority="P0",
        business_role="latest note summary for home panel",
        requires_browser_context=False,
        notes="Direct requests with Chrome cookies returned 200.",
    ),
    CreatorApiSpec(
        name="note_detail_new",
        path="/api/galaxy/creator/data/note_detail_new",
        priority="P0",
        business_role="note-level detail enrichment",
        requires_browser_context=True,
        notes="Observed from home route network traffic.",
    ),
    CreatorApiSpec(
        name="note_user_posted",
        path="/api/galaxy/v2/creator/note/user/posted",
        priority="P0",
        business_role="posted note list for note manager",
        requires_browser_context=True,
        notes="Observed 200 in browser context; capture should aggregate page responses when multiple page requests are visible.",
    ),
    CreatorApiSpec(
        name="livedata_overview",
        path="/api/galaxy/v2/creator/datacenter/livedata/overview",
        priority="P1",
        business_role="creator-side live data summary",
        requires_browser_context=True,
        notes="Observed from home route network traffic.",
    ),
    CreatorApiSpec(
        name="growthrights_batchquery",
        path="/api/galaxy/v2/creator/rightscenter/growthrights/batchquery",
        priority="P1",
        business_role="creator rights and eligibility inventory",
        requires_browser_context=True,
        notes="Useful for creator capability gating, not a core Revenue OS metric source.",
    ),
    CreatorApiSpec(
        name="activity_center_list",
        path="/api/galaxy/v2/creator/activity_center/list",
        priority="P2",
        business_role="campaign opportunities",
        requires_browser_context=True,
        notes="Useful for content opportunity radar.",
    ),
    CreatorApiSpec(
        name="create_guidance",
        path="/api/galaxy/creator/data/create_guidance",
        priority="P2",
        business_role="topic and content guidance",
        requires_browser_context=True,
        notes="Useful as supplemental ideation, not a core decision metric source.",
    ),
    CreatorApiSpec(
        name="leaderboard_recommend",
        path="/api/galaxy/v2/creator/datacenter/leaderboard/recommend",
        priority="P2",
        business_role="peer learning and trend spotting",
        requires_browser_context=True,
        notes="Potential benchmark input, not a direct business KPI source.",
    ),
)


def creator_surface_names() -> list[str]:
    return [surface.name for surface in CREATOR_SURFACES]


def creator_api_names() -> list[str]:
    return [api.name for api in CREATOR_APIS]


def get_creator_surface(name: str) -> CreatorSurfaceSpec:
    for surface in CREATOR_SURFACES:
        if surface.name == name:
            return surface
    raise KeyError(f"Unknown creator surface: {name}")


def creator_surfaces_for_mode(mode: str) -> list[CreatorSurfaceSpec]:
    return [surface for surface in CREATOR_SURFACES if mode in surface.cadence_modes]


def creator_cadence_surfaces_for_mode(mode: str) -> list[CreatorSurfaceSpec]:
    return [surface for surface in creator_surfaces_for_mode(mode) if is_creator_surface_proven(surface)]


def is_creator_surface_proven(surface: CreatorSurfaceSpec) -> bool:
    return is_surface_proven("creator", surface.name, surface.proof_status)


def creator_unproven_surfaces_for_mode(mode: str) -> list[CreatorSurfaceSpec]:
    return [surface for surface in creator_surfaces_for_mode(mode) if not is_creator_surface_proven(surface)]
