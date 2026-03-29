from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import list_artifacts, read_json, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        value = ts
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return None


def _recent_runs(days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    runs: list[dict[str, Any]] = []
    for path in list_artifacts("cadence_result"):
        payload = read_json(path)
        created = _parse_iso(payload.get("created_at"))
        if created and created >= cutoff:
            runs.append(payload)
    runs.sort(key=lambda item: item.get("created_at", ""))
    return runs


def build_cadence_stability_report(days: int = 14) -> dict[str, Any]:
    runs = _recent_runs(days)
    status_counts = Counter(item.get("status", "unknown") for item in runs)
    readiness_counts = Counter(item.get("acquisition_readiness_status", "unknown") for item in runs)

    by_mode: dict[str, dict[str, Any]] = {}
    mode_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in runs:
        mode_groups[str(item.get("mode", "unknown"))].append(item)

    for mode in ["daily", "weekly", "monthly"]:
        items = mode_groups.get(mode, [])
        total = len(items)
        mode_status = Counter(item.get("status", "unknown") for item in items)
        non_blocked = mode_status.get("success", 0) + mode_status.get("partial_success", 0)
        by_mode[mode] = {
            "total_runs": total,
            "success_runs": mode_status.get("success", 0),
            "partial_success_runs": mode_status.get("partial_success", 0),
            "blocked_runs": mode_status.get("blocked", 0),
            "non_blocked_runs": non_blocked,
            "success_rate": round((mode_status.get("success", 0) / total), 4) if total else 0.0,
            "blocked_rate": round((mode_status.get("blocked", 0) / total), 4) if total else 0.0,
        }

    total_runs = len(runs)
    blocked_rate = (status_counts.get("blocked", 0) / total_runs) if total_runs else 1.0
    red_readiness_rate = (readiness_counts.get("red", 0) / total_runs) if total_runs else 1.0

    checks = {
        "weekly_non_blocked_runs_ge_2": by_mode["weekly"]["non_blocked_runs"] >= 2,
        "monthly_non_blocked_runs_ge_1": by_mode["monthly"]["non_blocked_runs"] >= 1,
        "blocked_rate_le_0_15": blocked_rate <= 0.15,
        "red_readiness_rate_le_0_10": red_readiness_rate <= 0.10,
    }
    pass_status = "pass" if all(checks.values()) else "fail"

    actions: list[str] = []
    if not checks["weekly_non_blocked_runs_ge_2"]:
        actions.append("Increase weekly cadence reliability to at least 2 non-blocked runs in 14-day window.")
    if not checks["monthly_non_blocked_runs_ge_1"]:
        actions.append("Ensure at least 1 non-blocked monthly cadence run per 14-day window.")
    if not checks["blocked_rate_le_0_15"]:
        actions.append("Reduce blocked cadence runs by fixing acquisition readiness blockers before schedule time.")
    if not checks["red_readiness_rate_le_0_10"]:
        actions.append("Lower red readiness frequency with pre-run source freshness checks and resume policy.")
    if not actions:
        actions.append("Stability is within target. Continue daily/weekly/monthly cadence and monitor freshness SLA.")

    report = {
        "schema_version": "1.0.0",
        "object_type": "cadence_stability_report",
        "stability_id": deterministic_id("stability", f"{days}d", utc_now_iso()),
        "created_at": utc_now_iso(),
        "window_days": int(days),
        "total_runs": total_runs,
        "status_counts": dict(status_counts),
        "readiness_counts": dict(readiness_counts),
        "blocked_rate": round(blocked_rate, 4),
        "red_readiness_rate": round(red_readiness_rate, 4),
        "by_mode": by_mode,
        "checks": checks,
        "pass_status": pass_status,
        "recommended_actions": actions,
        "source_of_truth": "cadence_result artifacts in runtime window",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("cadence_stability_report", report)
    return report
