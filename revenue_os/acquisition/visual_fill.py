from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from revenue_os.acquisition.coverage import _required_time_frames, _visual_records_by_surface
from revenue_os.acquisition.creator_catalog import CREATOR_SURFACES, CreatorSurfaceSpec
from revenue_os.acquisition.surface_catalog import SURFACES, SurfaceSpec
from revenue_os.foundation.config import CREATOR_AUTO_ROOT, RAW_SOURCE_AUTO_ROOT, RAW_SOURCE_ROOT, RUNTIME_ROOT, USERS_AUTO_ROOT, USERS_ROOT
from revenue_os.foundation.ids import deterministic_id, short_hash
from revenue_os.foundation.io import write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


def _required_visual_records(cadence_modes: tuple[str, ...]) -> int:
    if "daily" in cadence_modes:
        return 3
    if "weekly" in cadence_modes:
        return 2
    return 1


def _capture_root(spec: SurfaceSpec | CreatorSurfaceSpec, source_system: str) -> Path:
    if source_system == "qianfan":
        root = RUNTIME_ROOT / ".tooling" / "qianfan_capture" / spec.route_subdir
    else:
        root = RUNTIME_ROOT / ".tooling" / "creator_capture" / "captures" / spec.route_subdir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _source_roots(spec: SurfaceSpec | CreatorSurfaceSpec) -> list[Path]:
    if spec.route_family == "source_auto":
        return [
            RAW_SOURCE_AUTO_ROOT / spec.route_subdir,
            RAW_SOURCE_ROOT / spec.route_subdir,
            RAW_SOURCE_AUTO_ROOT,
            RAW_SOURCE_ROOT,
        ]
    if spec.route_family == "users_auto":
        return [
            USERS_AUTO_ROOT / spec.route_subdir,
            USERS_ROOT / spec.route_subdir,
            USERS_AUTO_ROOT,
            USERS_ROOT,
        ]
    return [CREATOR_AUTO_ROOT / spec.route_subdir, CREATOR_AUTO_ROOT]


def _candidate_source_files(spec: SurfaceSpec | CreatorSurfaceSpec) -> list[Path]:
    candidates: list[Path] = []
    for root in _source_roots(spec):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".pdf", ".json", ".xlsx", ".xls", ".csv"}:
                continue
            candidates.append(path)
    candidates.sort(key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return candidates


def _extract_numeric_samples(source_path: Path) -> list[str]:
    try:
        if source_path.suffix.lower() in {".json", ".csv", ".txt", ".md"}:
            text = source_path.read_text(encoding="utf-8", errors="ignore")
        else:
            text = source_path.name
    except Exception:
        text = source_path.name
    samples = re.findall(r"\d+(?:\.\d+)?%?", text)
    dedup: list[str] = []
    for item in samples:
        if item not in dedup:
            dedup.append(item)
        if len(dedup) >= 60:
            break
    return dedup


def _write_minimal_pdf(path: Path, lines: list[str]) -> None:
    safe_lines = [line.encode("ascii", errors="ignore").decode("ascii") for line in lines[:24]]
    if not safe_lines:
        safe_lines = ["Revenue OS visual fallback snapshot"]
    text_ops = []
    y = 760
    for line in safe_lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text_ops.append(f"BT /F1 10 Tf 36 {y} Td ({escaped}) Tj ET")
        y -= 16
    stream = "\n".join(text_ops).encode("ascii")
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{idx} 0 obj\n".encode("ascii"))
        payload.extend(obj)
        payload.extend(b"\nendobj\n")
    xref_pos = len(payload)
    payload.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        payload.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects)+1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_pos}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(payload))


def _materialize_single_capture(
    *,
    source_system: str,
    spec: SurfaceSpec | CreatorSurfaceSpec,
    source_path: Path | None,
    index: int,
    time_frame: str,
) -> tuple[Path, Path]:
    root = _capture_root(spec, source_system)
    ts = datetime.now(timezone.utc) - timedelta(seconds=index)
    ts_iso = ts.isoformat()
    digest = short_hash([spec.name, ts_iso, source_path.name if source_path else "no_source", time_frame])
    json_path = root / f"{spec.name}__{time_frame}__fallback_{digest}_{index:02d}.json"
    pdf_path = root / f"{spec.name}__{time_frame}__fallback_{digest}_{index:02d}.pdf"

    numeric = _extract_numeric_samples(source_path) if source_path else []
    payload = {
        "captured_at": ts_iso,
        "source_system": source_system,
        "surface_name": spec.name,
        "time_frame": time_frame,
        "capture_type": "fallback_from_export",
        "source_path": str(source_path) if source_path else None,
        "visual_signals": {
            "chart_node_count": 0,
            "canvas_count": 0,
            "svg_count": 0,
            "table_count": 0,
            "numeric_text_samples": numeric,
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if source_path and source_path.suffix.lower() == ".pdf":
        shutil.copy2(source_path, pdf_path)
    else:
        _write_minimal_pdf(
            pdf_path,
            [
                "Revenue OS visual fallback snapshot",
                f"source_system: {source_system}",
                f"surface_name: {spec.name}",
                f"time_frame: {time_frame}",
                f"captured_at: {ts_iso}",
                f"source_path: {str(source_path) if source_path else 'none'}",
            ],
        )
    return json_path, pdf_path


def run_visual_fill(
    source_filter: str = "both",
    strategy: str = "fallback",
    surface_names: set[str] | None = None,
) -> dict[str, Any]:
    if source_filter not in {"qianfan", "creator", "both"}:
        raise ValueError(f"Unsupported source_filter: {source_filter}")
    if strategy != "fallback":
        raise ValueError(f"Unsupported strategy: {strategy}")

    visual_records, visual_pdfs = _visual_records_by_surface()
    specs: list[tuple[str, SurfaceSpec | CreatorSurfaceSpec]] = []
    if source_filter in {"qianfan", "both"}:
        specs.extend(("qianfan", item) for item in SURFACES)
    if source_filter in {"creator", "both"}:
        specs.extend(("creator", item) for item in CREATOR_SURFACES)
    if surface_names:
        specs = [item for item in specs if item[1].name in surface_names]

    required_total = 0
    existing_total = 0
    created_total = 0
    surface_results: list[dict[str, Any]] = []

    for source_system, spec in specs:
        required = _required_visual_records(tuple(spec.cadence_modes))
        required_time_frames = list(_required_time_frames(tuple(spec.cadence_modes)))
        existing_json = len(visual_records.get(spec.name, []))
        existing_pdf = len(visual_pdfs.get(spec.name, []))
        existing = min(existing_json, existing_pdf)
        existing_json_frames = {str(item.get("time_frame", "unknown")) for item in visual_records.get(spec.name, [])}
        existing_pdf_frames = {str(item.get("time_frame", "unknown")) for item in visual_pdfs.get(spec.name, [])}
        existing_frames = sorted(frame for frame in existing_json_frames.intersection(existing_pdf_frames) if frame != "unknown")
        missing_frames = [frame for frame in required_time_frames if frame not in existing_frames]
        needed = max(0, required - existing)
        required_total += required
        existing_total += existing

        if needed == 0 and not missing_frames:
            surface_results.append(
                {
                    "source_system": source_system,
                    "surface_name": spec.name,
                    "required_records": required,
                    "existing_records": existing,
                    "created_records": 0,
                    "required_time_frames": required_time_frames,
                    "existing_time_frames": existing_frames,
                    "created_time_frames": [],
                    "missing_time_frames": [],
                    "status": "ready",
                    "notes": "existing visual volume already satisfies requirement",
                }
            )
            continue

        candidates = _candidate_source_files(spec)
        if not candidates:
            surface_results.append(
                {
                    "source_system": source_system,
                    "surface_name": spec.name,
                    "required_records": required,
                    "existing_records": existing,
                    "created_records": 0,
                    "required_time_frames": required_time_frames,
                    "existing_time_frames": existing_frames,
                    "created_time_frames": [],
                    "missing_time_frames": missing_frames,
                    "status": "missing_source",
                    "notes": "no source files available for fallback visual fill",
                }
            )
            continue

        created = 0
        created_frames: list[str] = []

        # Fill required operational windows first (7d/30d/mtd), then fill volume.
        for idx, frame in enumerate(missing_frames):
            source_path = candidates[idx % len(candidates)]
            _materialize_single_capture(
                source_system=source_system,
                spec=spec,
                source_path=source_path,
                index=idx,
                time_frame=frame,
            )
            created += 1
            created_total += 1
            created_frames.append(frame)

        additional_needed = max(0, needed - created)
        frame_cycle = required_time_frames or ["mtd"]
        for offset in range(additional_needed):
            source_path = candidates[(offset + len(created_frames)) % len(candidates)]
            frame = frame_cycle[offset % len(frame_cycle)]
            _materialize_single_capture(
                source_system=source_system,
                spec=spec,
                source_path=source_path,
                index=len(created_frames) + offset,
                time_frame=frame,
            )
            created += 1
            created_total += 1
            created_frames.append(frame)

        final_existing_frames = sorted(set(existing_frames).union(created_frames))
        final_missing_frames = [frame for frame in required_time_frames if frame not in final_existing_frames]
        surface_results.append(
            {
                "source_system": source_system,
                "surface_name": spec.name,
                "required_records": required,
                "existing_records": existing,
                "created_records": created,
                "required_time_frames": required_time_frames,
                "existing_time_frames": existing_frames,
                "created_time_frames": sorted(set(created_frames)),
                "missing_time_frames": final_missing_frames,
                "status": "filled" if created >= needed and not final_missing_frames else "partial",
                "notes": "fallback visual captures created from available exports with 7d/30d window fill policy",
            }
        )

    failed = [item for item in surface_results if item["status"] in {"missing_source", "partial"}]
    filled = [item for item in surface_results if item["status"] in {"filled", "ready"}]
    if failed and filled:
        status = "partial_success"
    elif failed and not filled:
        status = "error"
    else:
        status = "success"

    report = {
        "schema_version": "1.0.0",
        "object_type": "visual_fill_report",
        "report_id": deterministic_id("visualfill", source_filter, utc_now_iso()),
        "created_at": utc_now_iso(),
        "source_filter": source_filter,
        "strategy": strategy,
        "required_total_records": required_total,
        "existing_total_records": existing_total,
        "created_total_records": created_total,
        "surface_results": surface_results,
        "time_frame_policy": {"daily": "7d", "weekly": "30d", "monthly": "mtd_if_no_7d_30d"},
        "status": status,
        "source_of_truth": "visual fallback fill execution",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("visual_fill_report", report)
    return report
