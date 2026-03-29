from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from revenue_os.acquisition.creator_catalog import CREATOR_SURFACES
from revenue_os.acquisition.proof_registry import is_surface_proven
from revenue_os.acquisition.selector_specs import selector_specs_as_dicts, selector_coverage_report
from revenue_os.acquisition.surface_catalog import SURFACES
from revenue_os.foundation.config import RAW_DATA_ROOT, RAW_SOURCE_AUTO_ROOT, RAW_SOURCE_ROOT, RUNTIME_ROOT, USERS_AUTO_ROOT, USERS_ROOT
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import latest_artifact, write_artifact
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


def _required_visual_volume(cadence_modes: tuple[str, ...]) -> tuple[int, int]:
    # Quantified capture policy:
    # daily surfaces need denser sampling than weekly/monthly.
    if "daily" in cadence_modes:
        return 3, 14
    if "weekly" in cadence_modes:
        return 2, 35
    return 1, 45


def _required_time_frames(cadence_modes: tuple[str, ...]) -> tuple[str, ...]:
    # Enforce operational windows used by Qianfan/Creator dashboards.
    frames: list[str] = []
    if "daily" in cadence_modes:
        frames.append("7d")
    if "weekly" in cadence_modes:
        frames.append("30d")
    if "monthly" in cadence_modes and not frames:
        frames.append("mtd")
    return tuple(frames or ["mtd"])


def _normalize_text_token(value: str) -> str:
    lowered = value.lower()
    parts = re.findall(r"[a-z0-9\u4e00-\u9fff]+", lowered)
    return "".join(parts)


def _infer_time_frame(text: str | None) -> str:
    token = _normalize_text_token(text or "")
    if not token:
        return "unknown"
    if any(item in token for item in ("7d", "7day", "last7", "近7天", "最近7天", "7天")):
        return "7d"
    if any(item in token for item in ("30d", "30day", "last30", "近30天", "最近30天", "30天")):
        return "30d"
    if any(item in token for item in ("mtd", "当月", "本月", "monthtodate")):
        return "mtd"
    if any(item in token for item in ("naturalmonth", "自然月")):
        return "natural_month"
    return "unknown"


def _visual_payload(path: Path) -> tuple[bool, int, int, str]:
    if path.suffix.lower() != ".json" or not path.exists():
        return False, 0, 0, "unknown"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, 0, 0, "unknown"
    visual = payload.get("visual_signals")
    if not isinstance(visual, dict):
        visual = ((payload.get("parsed") or {}).get("visual_signals") if isinstance(payload.get("parsed"), dict) else None)
    if not isinstance(visual, dict):
        return False, 0, 0, "unknown"
    chart_nodes = int(visual.get("chart_node_count", 0) or 0)
    numeric_signals = len(visual.get("numeric_text_samples", []) or [])
    tf_raw = payload.get("time_frame") or payload.get("time_window")
    if tf_raw is None and isinstance(payload.get("parsed"), dict):
        tf_raw = payload["parsed"].get("time_frame") or payload["parsed"].get("time_window")
    time_frame = _infer_time_frame(str(tf_raw or ""))
    return True, chart_nodes, numeric_signals, time_frame


def _visual_records_by_surface(max_age_days: float | None = 60.0) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    pdf_grouped: dict[str, list[dict[str, Any]]] = {}
    stem_time_frame: dict[tuple[str, str], str] = {}
    max_scan = int(os.environ.get("REVENUE_OS_VISUAL_COVERAGE_MAX_SCAN", "5000") or 5000)
    roots = [
        RUNTIME_ROOT / ".tooling" / "qianfan_capture",
        RUNTIME_ROOT / ".tooling" / "creator_capture" / "captures",
    ]
    json_paths: list[Path] = []
    pdf_paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        json_paths.extend(root.rglob("*.json"))
        pdf_paths.extend(root.rglob("*.pdf"))
    json_paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0.0)
    pdf_paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0.0)
    if max_scan > 0:
        json_paths = json_paths[-max_scan:]
        pdf_paths = pdf_paths[-max_scan:]

    for path in json_paths:
        stem = path.stem
        surface_name = stem.split("__", 1)[0]
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        days = _days_since(ts)
        if days is None:
            continue
        if max_age_days is not None and days > max_age_days:
            continue
        ok, chart_nodes, numeric_signals, time_frame = _visual_payload(path)
        if not ok:
            continue
        inferred = time_frame if time_frame != "unknown" else _infer_time_frame(path.stem)
        if inferred != "unknown":
            stem_time_frame[(str(path.parent), path.stem)] = inferred
        grouped.setdefault(surface_name, []).append(
            {
                "downloaded_at": ts,
                "days_since": days,
                "chart_nodes": chart_nodes,
                "numeric_signals": numeric_signals,
                "time_frame": inferred,
            }
        )

    for path in pdf_paths:
        stem = path.stem
        surface_name = stem.split("__", 1)[0]
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        days = _days_since(ts)
        if days is None:
            continue
        if max_age_days is not None and days > max_age_days:
            continue
        time_frame = _infer_time_frame(path.stem)
        if time_frame == "unknown":
            time_frame = stem_time_frame.get((str(path.parent), path.stem), "unknown")
        pdf_grouped.setdefault(surface_name, []).append({"downloaded_at": ts, "days_since": days, "time_frame": time_frame})

    for items in grouped.values():
        items.sort(key=lambda item: item.get("days_since") if item.get("days_since") is not None else 99999.0)
    for items in pdf_grouped.values():
        items.sort(key=lambda item: item.get("days_since") if item.get("days_since") is not None else 99999.0)
    return grouped, pdf_grouped


def _surface_specs_by_source() -> dict[str, list[Any]]:
    return {
        "qianfan": list(SURFACES),
        "creator": list(CREATOR_SURFACES),
    }


def _surface_match_tokens(spec: Any, signature_map: dict[str, list[str]]) -> list[str]:
    raw = [
        str(getattr(spec, "name", "")),
        str(getattr(spec, "route_subdir", "")),
        str(getattr(spec, "navigation_hint", "")),
        str(getattr(spec, "source_url", "")),
    ]
    raw.extend(signature_map.get(str(getattr(spec, "selector_spec_key", "")), []))
    normalized = {_normalize_text_token(item) for item in raw if item}
    normalized.discard("")
    return sorted(normalized, key=len, reverse=True)


def _legacy_pdf_baseline() -> dict[str, Any]:
    surface_specs = _surface_specs_by_source()
    signature_map = {
        str(item.get("surface_key", "")): [str(sig) for sig in item.get("expected_filename_signatures", [])]
        for item in selector_specs_as_dicts()
    }
    tokens_by_source: dict[str, dict[str, list[str]]] = {
        source: {spec.name: _surface_match_tokens(spec, signature_map) for spec in specs}
        for source, specs in surface_specs.items()
    }
    baseline: dict[str, Any] = {
        "qianfan": {"total_pdf_count": 0, "matched_pdf_count": 0, "unmatched_pdf_count": 0, "surface_pdf_counts": {}},
        "creator": {"total_pdf_count": 0, "matched_pdf_count": 0, "unmatched_pdf_count": 0, "surface_pdf_counts": {}},
        "unclassified_pdf_count": 0,
    }
    for path in RAW_DATA_ROOT.rglob("*.pdf"):
        path_token = _normalize_text_token(str(path.relative_to(RAW_DATA_ROOT)))
        parts = [item.lower() for item in path.parts]
        if "creator_auto" in parts or "pdfs" in parts:
            source = "creator"
        elif any(item in parts for item in ("source", "source_auto", "users", "users_auto")):
            source = "qianfan"
        else:
            source = "unknown"
        if source == "unknown":
            baseline["unclassified_pdf_count"] += 1
            continue
        baseline[source]["total_pdf_count"] += 1
        best_surface = ""
        best_score = 0
        for surface_name, tokens in tokens_by_source[source].items():
            score = 0
            for token in tokens:
                if token and token in path_token:
                    score += max(1, len(token) // 4)
            if score > best_score:
                best_score = score
                best_surface = surface_name
        if best_surface and best_score > 0:
            counts = baseline[source]["surface_pdf_counts"]
            counts[best_surface] = int(counts.get(best_surface, 0) or 0) + 1
            baseline[source]["matched_pdf_count"] += 1
        else:
            baseline[source]["unmatched_pdf_count"] += 1
    return baseline


def _count_family_files(root: Path, suffix: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not root.exists():
        return counts
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() != suffix:
            continue
        family = path.relative_to(root).parts[0] if path.relative_to(root).parts else "_root"
        counts[family] = int(counts.get(family, 0) or 0) + 1
    return counts


def _qianfan_manual_auto_baseline() -> dict[str, Any]:
    source_manual = _count_family_files(RAW_SOURCE_ROOT, ".xlsx")
    source_auto = _count_family_files(RAW_SOURCE_AUTO_ROOT, ".xlsx")
    users_manual = _count_family_files(USERS_ROOT, ".pdf")
    users_auto = _count_family_files(USERS_AUTO_ROOT, ".pdf")

    source_manual_total = sum(source_manual.values())
    source_auto_total = sum(source_auto.values())
    users_manual_total = sum(users_manual.values())
    users_auto_total = sum(users_auto.values())

    source_ratio = 1.0 if source_manual_total <= 0 else min(1.0, source_auto_total / float(source_manual_total))
    users_ratio = 1.0 if users_manual_total <= 0 else min(1.0, users_auto_total / float(users_manual_total))
    overall_ratio = min(source_ratio, users_ratio)

    return {
        "source_xlsx_manual_total": int(source_manual_total),
        "source_xlsx_auto_total": int(source_auto_total),
        "users_pdf_manual_total": int(users_manual_total),
        "users_pdf_auto_total": int(users_auto_total),
        "source_ratio": round(source_ratio, 4),
        "users_ratio": round(users_ratio, 4),
        "overall_ratio": round(overall_ratio, 4),
        "met": source_auto_total >= source_manual_total and users_auto_total >= users_manual_total,
        "source_family_counts": {
            "manual": source_manual,
            "auto": source_auto,
        },
        "users_family_counts": {
            "manual": users_manual,
            "auto": users_auto,
        },
    }


def _build_visual_summary(source_filter: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    specs_by_source = _surface_specs_by_source()
    records_by_surface, pdf_records_by_surface = _visual_records_by_surface()
    _, pdf_records_all_age = _visual_records_by_surface(max_age_days=None)
    baseline = _legacy_pdf_baseline()
    missing_visual: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, int]] = {
        "qianfan": {"required": 0, "ready": 0, "missing": 0, "time_frame_slots_required": 0, "time_frame_slots_ready": 0},
        "creator": {"required": 0, "ready": 0, "missing": 0, "time_frame_slots_required": 0, "time_frame_slots_ready": 0},
    }

    for source_system, specs in specs_by_source.items():
        for spec in specs:
            if source_filter != "both" and source_filter != source_system:
                continue
            required_records, max_age_days = _required_visual_volume(tuple(getattr(spec, "cadence_modes", ())))
            required_frames = _required_time_frames(tuple(getattr(spec, "cadence_modes", ())))
            history = records_by_surface.get(spec.name, [])
            pdf_history = pdf_records_by_surface.get(spec.name, [])
            recent = [item for item in history if item.get("days_since") is not None and float(item["days_since"]) <= max_age_days]
            recent_pdf = [item for item in pdf_history if item.get("days_since") is not None and float(item["days_since"]) <= max_age_days]
            frame_counts = {frame: len([item for item in recent if item.get("time_frame") == frame]) for frame in required_frames}
            frame_pdf_counts = {frame: len([item for item in recent_pdf if item.get("time_frame") == frame]) for frame in required_frames}
            missing_frames = [frame for frame in required_frames if frame_counts.get(frame, 0) <= 0 or frame_pdf_counts.get(frame, 0) <= 0]
            summaries[source_system]["required"] += 1
            summaries[source_system]["time_frame_slots_required"] += len(required_frames)
            summaries[source_system]["time_frame_slots_ready"] += len(required_frames) - len(missing_frames)
            if len(recent) >= required_records and len(recent_pdf) >= required_records and not missing_frames:
                summaries[source_system]["ready"] += 1
                continue
            summaries[source_system]["missing"] += 1
            latest = history[0] if history else None
            missing_visual.append(
                {
                    "source_system": source_system,
                    "surface_name": spec.name,
                    "required_recent_records": required_records,
                    "recent_records": len(recent),
                    "recent_pdf_records": len(recent_pdf),
                    "max_age_days": max_age_days,
                    "latest_visual_capture_at": latest.get("downloaded_at") if latest else None,
                    "latest_chart_nodes": int(latest.get("chart_nodes", 0) if latest else 0),
                    "latest_numeric_signals": int(latest.get("numeric_signals", 0) if latest else 0),
                    "required_time_frames": list(required_frames),
                    "missing_time_frames": missing_frames,
                    "time_frame_record_counts": frame_counts,
                    "time_frame_pdf_record_counts": frame_pdf_counts,
                }
            )

    qianfan_summary = dict(summaries["qianfan"])
    creator_summary = dict(summaries["creator"])
    qianfan_summary["time_frame_slots_missing"] = (
        qianfan_summary["time_frame_slots_required"] - qianfan_summary["time_frame_slots_ready"]
    )
    creator_summary["time_frame_slots_missing"] = (
        creator_summary["time_frame_slots_required"] - creator_summary["time_frame_slots_ready"]
    )
    for source_system, specs in specs_by_source.items():
        runtime_pdf_total = sum(len(pdf_records_all_age.get(spec.name, [])) for spec in specs)
        baseline_pdf_total = int(baseline[source_system]["total_pdf_count"] or 0)
        ratio = 1.0 if baseline_pdf_total <= 0 else min(1.0, runtime_pdf_total / float(baseline_pdf_total))
        summary = qianfan_summary if source_system == "qianfan" else creator_summary
        summary["runtime_pdf_total"] = int(runtime_pdf_total)
        summary["baseline_pdf_total"] = baseline_pdf_total
        summary["baseline_met"] = runtime_pdf_total >= baseline_pdf_total
        summary["baseline_ratio"] = round(ratio, 4)
    return qianfan_summary, creator_summary, missing_visual, baseline


def build_acquisition_coverage_report(source_filter: str = "both") -> dict[str, Any]:
    if source_filter not in {"qianfan", "creator", "both"}:
        raise ValueError(f"Unsupported source filter: {source_filter}")
    coverage = selector_coverage_report()
    all_specs = selector_specs_as_dicts()
    missing = [
        {
            "source_system": item["source_system"],
            "surface_name": item["surface_name"],
            "proof_status": "planned",
            "selector_status": item["selector_status"],
            "route_url": item["route_url"],
        }
        for item in all_specs
        if not is_surface_proven(
            str(item["source_system"]),
            str(item["surface_name"]),
            str(item["proof_status"]),
        )
    ]
    if source_filter != "both":
        missing = [item for item in missing if item["source_system"] == source_filter]

    qianfan_visual_summary, creator_visual_summary, missing_visual, legacy_pdf_baseline = _build_visual_summary(source_filter)
    proof_total = coverage["qianfan"]["total"] + coverage["creator"]["total"]
    proof_ready = coverage["qianfan"]["proven"] + coverage["creator"]["proven"]
    visual_total = qianfan_visual_summary["required"] + creator_visual_summary["required"]
    visual_ready = qianfan_visual_summary["ready"] + creator_visual_summary["ready"]
    proof_ratio = (proof_ready / proof_total) if proof_total else 0.0
    visual_ratio = (visual_ready / visual_total) if visual_total else 0.0
    selected_sources = ("qianfan", "creator") if source_filter == "both" else (source_filter,)
    baseline_ratios = [
        float((qianfan_visual_summary if source == "qianfan" else creator_visual_summary).get("baseline_ratio", 1.0) or 1.0)
        for source in selected_sources
    ]
    baseline_ratio = min(baseline_ratios) if baseline_ratios else 1.0
    qianfan_auto_baseline = _qianfan_manual_auto_baseline()
    qianfan_auto_ratio = float(qianfan_auto_baseline.get("overall_ratio", 1.0) or 1.0)
    frontier = latest_artifact("acquisition_frontier_report") or {}
    frontier_summary = frontier.get("governance_summary", {})
    frontier_total = int(frontier_summary.get("total_api_candidates", 0) or 0)
    frontier_classified = int(frontier_summary.get("classified_api_candidates", 0) or 0)
    frontier_p0p1_total = int(frontier_summary.get("p0p1_total", 0) or 0)
    frontier_p0p1_integrated = int(frontier_summary.get("p0p1_integrated_proven", 0) or 0)
    frontier_governance_ratio = 1.0 if frontier_total <= 0 else min(1.0, frontier_classified / float(frontier_total))
    frontier_p0p1_integration_ratio = (
        1.0 if frontier_p0p1_total <= 0 else min(1.0, frontier_p0p1_integrated / float(frontier_p0p1_total))
    )
    coverage_v2_ratio = min(proof_ratio, visual_ratio, baseline_ratio, qianfan_auto_ratio, frontier_governance_ratio, frontier_p0p1_integration_ratio)

    report = {
        "schema_version": "1.0.0",
        "object_type": "acquisition_coverage_report",
        "coverage_id": deterministic_id("coverage", source_filter, utc_now_iso()),
        "created_at": utc_now_iso(),
        "source_filter": source_filter,
        "qianfan_summary": coverage["qianfan"],
        "creator_summary": coverage["creator"],
        "qianfan_visual_summary": qianfan_visual_summary,
        "creator_visual_summary": creator_visual_summary,
        "missing_surfaces": missing,
        "missing_visual_surfaces": missing_visual,
        "legacy_pdf_baseline": legacy_pdf_baseline,
        "qianfan_extraction_baseline": qianfan_auto_baseline,
        "frontier_summary": {
            "frontier_report_id": frontier.get("report_id"),
            "total_api_candidates": frontier_total,
            "classified_api_candidates": frontier_classified,
            "unknown_api_candidates": int(frontier_summary.get("unknown_api_candidates", 0) or 0),
            "p0p1_total": frontier_p0p1_total,
            "p0p1_integrated_proven": frontier_p0p1_integrated,
        },
        "baseline_alignment": {
            "baseline_ratio": round(baseline_ratio, 4),
            "baseline_met": baseline_ratio >= 1.0 - 1e-9,
        },
        "decision_complete_coverage_pct": round(min(proof_ratio, visual_ratio, baseline_ratio, qianfan_auto_ratio) * 100.0, 2),
        "frontier_governance_coverage_pct": round(frontier_governance_ratio * 100.0, 2),
        "frontier_p0p1_integration_pct": round(frontier_p0p1_integration_ratio * 100.0, 2),
        "coverage_v2_pct": round(coverage_v2_ratio * 100.0, 2),
        "source_of_truth": "selector specs + proof records + quantified visual probe volume + legacy screenshot PDF baseline",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("acquisition_coverage_report", report)
    return report
