from __future__ import annotations

from typing import Any

from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import list_artifacts, read_artifact, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


def _proof_type_from_mode(browser_mode: str) -> str:
    if browser_mode == "browser":
        return "browser_context"
    if browser_mode == "staged":
        return "staged_download"
    return "manual_export"


def record_surface_proof(
    source_system: str,
    surface_name: str,
    selector_spec_key: str,
    run_id: str,
    status: str,
    browser_mode: str,
    route_targets: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    proof_status = "proven" if status == "success" else "failed"
    proof = {
        "schema_version": "1.0.0",
        "object_type": "surface_proof_record",
        "proof_id": deterministic_id("proof", source_system, surface_name, run_id),
        "source_system": source_system,
        "surface_name": surface_name,
        "selector_spec_key": selector_spec_key,
        "run_id": run_id,
        "status": proof_status,
        "proven_at": utc_now_iso(),
        "proof_type": _proof_type_from_mode(browser_mode),
        "route_targets": route_targets or [],
        "notes": notes or "",
        "source_of_truth": "acquisition proof recording",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("surface_proof_record", proof)
    return proof


def latest_surface_proof(source_system: str, surface_name: str) -> dict[str, Any] | None:
    items = []
    for path in list_artifacts("surface_proof_record"):
        proof = read_artifact("surface_proof_record", path.stem)
        if proof.get("source_system") == source_system and proof.get("surface_name") == surface_name:
            items.append(proof)
    if not items:
        return None
    items.sort(key=lambda item: item.get("proven_at") or "")
    return items[-1]


def is_surface_proven(source_system: str, surface_name: str, static_proof_status: str) -> bool:
    if static_proof_status == "proven":
        return True
    latest = latest_surface_proof(source_system, surface_name)
    return bool(latest and latest.get("status") == "proven")


def build_proof_batch_report(
    source_system: str,
    mode: str,
    wave: str,
    attempted_surfaces: list[str],
    proven_surfaces: list[str],
    failed_surfaces: list[str],
    run_ids: list[str],
) -> dict[str, Any]:
    status = "success"
    if failed_surfaces and proven_surfaces:
        status = "partial_success"
    elif failed_surfaces and not proven_surfaces:
        status = "error"
    report = {
        "schema_version": "1.0.0",
        "object_type": "proof_batch_report",
        "batch_id": deterministic_id("proofbatch", source_system, mode, wave, utc_now_iso()),
        "source_system": source_system,
        "mode": mode,
        "wave": wave,
        "created_at": utc_now_iso(),
        "attempted_surfaces": attempted_surfaces,
        "proven_surfaces": proven_surfaces,
        "failed_surfaces": failed_surfaces,
        "run_ids": run_ids,
        "status": status,
        "source_of_truth": "acquisition proof batch execution",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("proof_batch_report", report)
    return report
