from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from revenue_os.acquisition.acquisition_manifest import build_reconcile_report, build_run_manifest
from revenue_os.foundation.config import CREATOR_AUTO_ROOT, RAW_DATA_ROOT, RAW_SOURCE_AUTO_ROOT, RAW_SOURCE_ROOT, USERS_AUTO_ROOT, USERS_ROOT
from revenue_os.foundation.ids import deterministic_id, short_hash
from revenue_os.foundation.io import write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


@dataclass(frozen=True)
class BootstrapSpec:
    family: str
    source_root: Path
    target_root: Path
    suffixes: tuple[str, ...]
    export_format: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_specs(source: str) -> list[BootstrapSpec]:
    specs: list[BootstrapSpec] = []
    if source in {"qianfan", "both"}:
        specs.extend(
            [
                BootstrapSpec(
                    family="qianfan_source_xlsx",
                    source_root=RAW_SOURCE_ROOT,
                    target_root=RAW_SOURCE_AUTO_ROOT,
                    suffixes=(".xlsx",),
                    export_format="xlsx",
                ),
                BootstrapSpec(
                    family="qianfan_users_pdf",
                    source_root=USERS_ROOT,
                    target_root=USERS_AUTO_ROOT,
                    suffixes=(".pdf",),
                    export_format="pdf",
                ),
            ]
        )
    if source in {"creator", "both"}:
        creator_manual = RAW_DATA_ROOT / "creator"
        if creator_manual.exists():
            specs.append(
                BootstrapSpec(
                    family="creator_manual_export",
                    source_root=creator_manual,
                    target_root=CREATOR_AUTO_ROOT,
                    suffixes=(".xlsx", ".csv", ".json", ".pdf"),
                    export_format="mixed",
                )
            )
    return specs


def _copy_bootstrap_file(spec: BootstrapSpec, run_id: str, source_path: Path) -> dict[str, Any]:
    rel_parent = source_path.relative_to(spec.source_root).parent
    target_dir = spec.target_root / rel_parent
    target_dir.mkdir(parents=True, exist_ok=True)

    sha256 = _sha256(source_path)
    target_name = f"{source_path.stem}__{short_hash([sha256])}{source_path.suffix.lower()}"
    target_path = target_dir / target_name
    if not target_path.exists():
        shutil.copy2(source_path, target_path)

    record = {
        "schema_version": "1.0.0",
        "object_type": "acquired_file_record",
        "file_id": deterministic_id("acqfile", run_id, spec.family, str(source_path), sha256),
        "run_id": run_id,
        "surface_name": f"bootstrap::{spec.family}",
        "export_format": spec.export_format,
        "downloaded_at": utc_now_iso(),
        "source_path": str(source_path),
        "route_target": str(target_path),
        "sha256": sha256,
        "filesize": source_path.stat().st_size,
        "browser_mode": "staged",
        "runner_mode": "native",
        "source_url": "bootstrap://raw_data",
        "retry_count": 0,
        "source_of_truth": "bootstrap sync from raw_data historical exports",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "blocking",
    }
    write_artifact("acquired_file_record", record)
    return record


def bootstrap_sync(source: str = "both") -> dict[str, Any]:
    if source not in {"qianfan", "creator", "both"}:
        raise ValueError(f"Unsupported source: {source}")

    specs = _iter_specs(source)
    run_id = deterministic_id("acqrun", "bootstrap", source, utc_now_iso())
    file_ids: list[str] = []
    completed: list[str] = []
    issues: list[str] = []
    imported = 0

    for spec in specs:
        if not spec.source_root.exists():
            issues.append(f"{spec.family}:missing_source_root")
            continue
        imported_for_family = 0
        for path in sorted(spec.source_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in spec.suffixes:
                continue
            try:
                record = _copy_bootstrap_file(spec, run_id, path)
            except Exception as exc:
                issues.append(f"{spec.family}:{path.name}:{exc.__class__.__name__}")
                continue
            file_ids.append(record["file_id"])
            imported += 1
            imported_for_family += 1
        if imported_for_family > 0:
            completed.append(spec.family)

    reconcile = build_reconcile_report(
        run_id=run_id,
        expected_surfaces=[spec.family for spec in specs],
        completed_surfaces=completed,
        file_ids=file_ids,
        issues=issues,
    )
    write_artifact("download_reconcile_report", reconcile)

    status = "success"
    if issues and completed:
        status = "partial_success"
    if issues and not completed:
        status = "error"

    manifest = build_run_manifest(
        run_id=run_id,
        mode=f"bootstrap_{source}",
        browser_mode="staged",
        runner_mode="native",
        browser_name=None,
        source_url="bootstrap://raw_data",
        download_dir=str(RAW_DATA_ROOT),
        surface_records=[],
        downloaded_files=file_ids,
        status=status,
        error_code=";".join(issues) if issues else None,
        runner_command_template=None,
    )
    write_artifact("acquisition_run_manifest", manifest)
    manifest["imported_file_count"] = imported
    manifest["completed_families"] = completed
    return manifest
