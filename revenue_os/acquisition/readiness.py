from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from revenue_os.acquisition.creator_catalog import CreatorSurfaceSpec, creator_cadence_surfaces_for_mode, creator_surfaces_for_mode, is_creator_surface_proven
from revenue_os.acquisition.surface_catalog import SurfaceSpec, cadence_surfaces_for_mode, is_qianfan_surface_proven, surfaces_for_mode
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import list_artifacts, read_artifact, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except ValueError:
        return None


def _days_since(ts: str | None) -> float | None:
    parsed = _parse_iso(ts)
    if parsed is None:
        return None
    return max(0.0, round((datetime.now(timezone.utc) - parsed).total_seconds() / 86400, 2))


def _surface_records() -> list[dict[str, Any]]:
    return [read_artifact("surface_export_record", path.stem) for path in list_artifacts("surface_export_record")]


def _latest_surface_record(surface_name: str) -> dict[str, Any] | None:
    records = [record for record in _surface_records() if record.get("surface_name") == surface_name]
    if not records:
        return None
    records.sort(key=lambda item: item.get("finished_at") or "")
    return records[-1]


def _classify_surface(surface: SurfaceSpec | CreatorSurfaceSpec, latest_record: dict[str, Any] | None, snapshot_id: str, source_system: str) -> dict[str, Any]:
    latest_capture_at = latest_record.get("finished_at") if latest_record else None
    freshness_days = _days_since(latest_capture_at)
    latest_status = latest_record.get("status") if latest_record else None
    latest_run_id = latest_record.get("run_id") if latest_record else None

    if latest_record is None:
        freshness_status = "missing"
    elif freshness_days is not None and freshness_days > surface.freshness_threshold_days:
        freshness_status = "stale"
    elif latest_status in {"warning", "error", "partial_success"}:
        freshness_status = "stale"
    else:
        freshness_status = "fresh"

    resume_required = latest_status in {"warning", "error", "partial_success"}
    planner_impact = "additive"
    blocking_severity = surface.blocking_severity
    if freshness_status == "missing" and surface.blocking_severity == "red":
        planner_impact = "blocking"
    elif freshness_status in {"missing", "stale"} and surface.blocking_severity == "warning":
        planner_impact = "warning"
    elif freshness_status in {"missing", "stale"} and surface.blocking_severity == "none":
        planner_impact = "none"

    record = {
        "schema_version": "1.0.0",
        "object_type": "source_freshness_record",
        "freshness_id": deterministic_id("freshness", snapshot_id, source_system, surface.name),
        "snapshot_id": snapshot_id,
        "source_name": surface.name,
        "source_system": source_system,
        "surface_family": surface.route_subdir,
        "surface_name": surface.name,
        "latest_capture_at": latest_capture_at,
        "freshness_days": freshness_days,
        "freshness_status": freshness_status,
        "planner_impact": planner_impact,
        "resume_required": resume_required,
        "blocking_severity": blocking_severity if freshness_status != "fresh" else "none",
        "proof_status": surface.proof_status,
        "latest_run_id": latest_run_id,
        "source_of_truth": "surface export records + catalog freshness thresholds",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("source_freshness_record", record)
    return record


def build_acquisition_readiness(snapshot_id: str, mode: str) -> dict[str, Any]:
    qianfan_surfaces = cadence_surfaces_for_mode(mode)
    creator_surfaces = creator_cadence_surfaces_for_mode(mode)
    qianfan_optional = [surface for surface in surfaces_for_mode(mode) if not is_qianfan_surface_proven(surface)]
    creator_optional = [surface for surface in creator_surfaces_for_mode(mode) if not is_creator_surface_proven(surface)]

    qianfan_records = [_classify_surface(surface, _latest_surface_record(surface.name), snapshot_id, "qianfan") for surface in qianfan_surfaces]
    creator_records = [_classify_surface(surface, _latest_surface_record(surface.name), snapshot_id, "creator") for surface in creator_surfaces]
    optional_records = [
        _classify_surface(surface, _latest_surface_record(surface.name), snapshot_id, "qianfan")
        for surface in qianfan_optional
    ] + [
        _classify_surface(surface, _latest_surface_record(surface.name), snapshot_id, "creator")
        for surface in creator_optional
    ]

    def _group_status(records: list[dict[str, Any]]) -> str:
        if not records:
            return "green"
        if any(record["planner_impact"] == "blocking" for record in records):
            return "red"
        if any(record["freshness_status"] != "fresh" for record in records):
            return "warning"
        return "green"

    qianfan_status = _group_status(qianfan_records)
    creator_status = _group_status(creator_records)
    if "red" in {qianfan_status, creator_status}:
        status = "red"
    elif "warning" in {qianfan_status, creator_status}:
        status = "warning"
    else:
        status = "green"

    blocking_reasons = [record["source_name"] for record in qianfan_records + creator_records if record["planner_impact"] == "blocking"]
    partial_failures = [record["source_name"] for record in qianfan_records + creator_records if record["resume_required"]]

    return {
        "status": status,
        "qianfan_status": qianfan_status,
        "creator_status": creator_status,
        "source_freshness_refs": [record["freshness_id"] for record in qianfan_records + creator_records + optional_records],
        "partial_failures": partial_failures,
        "blocking_reasons": blocking_reasons,
        "optional_backlog": [record["source_name"] for record in optional_records if record["proof_status"] != "proven"],
    }
