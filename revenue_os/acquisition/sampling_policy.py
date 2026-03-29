from __future__ import annotations

from typing import Any

from revenue_os.acquisition.creator_catalog import creator_cadence_surfaces_for_mode
from revenue_os.acquisition.surface_catalog import cadence_surfaces_for_mode
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.time_utils import utc_now_iso


WINDOW_PRIORITY = {
    "daily": ["1d", "7d"],
    "weekly": ["30d", "7d"],
    "monthly": ["natural_month", "mtd", "30d"],
}


def _surface_windows(default_window: str, mode: str) -> list[str]:
    if mode == "daily":
        if default_window in {"mtd", "natural_month"}:
            return ["1d", "7d", default_window]
        if default_window == "last_30_days":
            return ["7d", "30d"]
        if default_window == "last_7_days":
            return ["1d", "7d"]
    if mode == "weekly":
        if default_window in {"mtd", "natural_month"}:
            return ["7d", "30d", default_window]
        if default_window == "last_7_days":
            return ["7d", "30d"]
        if default_window == "last_30_days":
            return ["7d", "30d"]
    if mode == "monthly":
        if default_window == "natural_month":
            return ["natural_month", "mtd", "30d"]
        if default_window == "mtd":
            return ["mtd", "30d"]
        if default_window == "last_30_days":
            return ["30d", "natural_month"]
    return [default_window]


def _tier_policy(mode: str) -> dict[str, str]:
    if mode == "daily":
        return {
            "P0": "sample daily with 1d and 7d windows for alerting and volatility control",
            "P1": "sample daily only when tied to active mission; otherwise carry from weekly",
            "P2": "do not force daily refresh unless anomaly or campaign override",
        }
    if mode == "weekly":
        return {
            "P0": "sample weekly with 7d and 30d windows; this is planning truth",
            "P1": "sample weekly with 30d context for diagnosis",
            "P2": "sample weekly if available; otherwise reuse latest monthly",
        }
    return {
        "P0": "reconcile monthly against natural-month exports and MTD",
        "P1": "monthly deep-dive for drift and taxonomy changes",
        "P2": "monthly archival and governance review",
    }


def build_sampling_policy(mode: str) -> dict[str, Any]:
    if mode not in {"daily", "weekly", "monthly"}:
        raise ValueError(f"Unsupported mode: {mode}")

    q_surfaces = cadence_surfaces_for_mode(mode)
    c_surfaces = creator_cadence_surfaces_for_mode(mode)

    surface_rules: list[dict[str, Any]] = []
    for surface in q_surfaces:
        surface_rules.append(
            {
                "source_system": "qianfan",
                "surface_name": surface.name,
                "priority": surface.priority,
                "windows": _surface_windows(surface.default_window, mode),
                "default_window": surface.default_window,
            }
        )
    for surface in c_surfaces:
        surface_rules.append(
            {
                "source_system": "creator",
                "surface_name": surface.name,
                "priority": surface.priority,
                "windows": _surface_windows(surface.default_window, mode),
                "default_window": surface.default_window,
            }
        )

    recommendation = "hybrid"
    decision_window = "30d"
    freshness_window = "7d"
    mode_objective = "balanced"
    if mode == "daily":
        recommendation = "daily_for_freshness_weekly_for_decision"
        decision_window = "7d"
        freshness_window = "1d"
        mode_objective = "freshness_and_anomaly_watch"
    elif mode == "weekly":
        recommendation = "weekly_primary"
        decision_window = "30d"
        freshness_window = "7d"
        mode_objective = "mission_selection_and_packaging"
    elif mode == "monthly":
        recommendation = "monthly_reconcile"
        decision_window = "natural_month"
        freshness_window = "mtd"
        mode_objective = "reconcile_eval_release"

    return {
        "policy_id": deterministic_id("sampling", mode, utc_now_iso()),
        "standard_version": "sampling_standard_2026-03-23",
        "mode": mode,
        "created_at": utc_now_iso(),
        "recommendation": recommendation,
        "decision_window": decision_window,
        "freshness_window": freshness_window,
        "mode_objective": mode_objective,
        "window_priority": WINDOW_PRIORITY[mode],
        "tier_policy": _tier_policy(mode),
        "surface_rules": surface_rules,
        "note": "Locked cadence standard: daily(1d+7d) for freshness, weekly(30d+7d) for planning, monthly(natural_month+mtd+30d) for reconciliation and release.",
    }
