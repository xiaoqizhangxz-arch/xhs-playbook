from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse
from typing import Any

from revenue_os.acquisition.creator_catalog import CREATOR_APIS, CREATOR_SURFACES
from revenue_os.acquisition.frontier_policy import classify_endpoint
from revenue_os.acquisition.surface_catalog import SURFACES
from revenue_os.foundation.ids import deterministic_id
from revenue_os.foundation.io import list_artifacts, read_artifact, write_artifact
from revenue_os.foundation.time_utils import utc_now_iso


NOISE_HOST_PREFIXES = (
    "apm-fe.",
    "spider-tracker.",
    "as.xiaohongshu.com",
    "t2.xiaohongshu.com",
)

NOISE_PATH_PATTERNS = (
    "/api/data",
    "/api/p/pj",
    "/api/sec/",
    "/api/redcaptcha/",
    "/api/sns/web/racing_",
)


def _slug(value: str) -> str:
    token = value.strip().lower()
    token = re.sub(r"https?://", "", token)
    token = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", token)
    token = re.sub(r"_+", "_", token).strip("_")
    return token[:80] or "candidate"


def _known_urls(source_system: str) -> set[str]:
    if source_system == "qianfan":
        return {surface.source_url for surface in SURFACES}
    if source_system == "creator":
        return {surface.source_url for surface in CREATOR_SURFACES}
    return set()


def _known_api_paths(source_system: str) -> set[str]:
    if source_system == "creator":
        return {spec.path for spec in CREATOR_APIS}
    # Qianfan has no frozen API map yet; keep empty so frontier report remains conservative.
    return set()


def _report_source(report: dict[str, Any]) -> str:
    return str(report.get("source_system") or "")


def _is_business_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    host = parsed.netloc.lower()
    path = parsed.path
    if not path:
        return False
    if not ("/api/" in path or "/fe_api/" in path):
        return False
    if any(host.startswith(prefix) for prefix in NOISE_HOST_PREFIXES):
        return False
    for pattern in NOISE_PATH_PATTERNS:
        if pattern in path:
            return False
    return True


def _collect_reports(source_filter: str, lookback: int) -> list[dict[str, Any]]:
    rows = []
    for path in list_artifacts("qianfan_discovery_report"):
        report = read_artifact("qianfan_discovery_report", path.stem)
        source_system = _report_source(report)
        if source_filter != "both" and source_filter != source_system:
            continue
        rows.append(report)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    if lookback > 0:
        rows = rows[:lookback]
    return rows


def _candidate_hints_from_urls(source_system: str, urls: list[str]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for url in urls:
        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split("/") if part]
        tail = path_parts[-1] if path_parts else parsed.netloc
        hints.append(
            {
                "source_system": source_system,
                "evidence_type": "missing_catalog_url",
                "evidence": url,
                "proposed_surface_name": _slug(tail),
                "confidence": 0.72,
            }
        )
    return hints


def _candidate_hints_from_labels(source_system: str, labels: list[str]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for label in labels:
        hints.append(
            {
                "source_system": source_system,
                "evidence_type": "missing_click_label",
                "evidence": label,
                "proposed_surface_name": _slug(label),
                "confidence": 0.58,
            }
        )
    return hints


def build_frontier_report(source_filter: str = "both", lookback: int = 20) -> dict[str, Any]:
    if source_filter not in {"qianfan", "creator", "both"}:
        raise ValueError(f"Unsupported source_filter: {source_filter}")

    reports = _collect_reports(source_filter, lookback)
    missing_urls: dict[str, set[str]] = {"qianfan": set(), "creator": set()}
    missing_labels: dict[str, set[str]] = {"qianfan": set(), "creator": set()}
    api_counter: dict[str, Counter[str]] = {"qianfan": Counter(), "creator": Counter()}
    report_ids: list[str] = []

    for report in reports:
        source_system = _report_source(report)
        if source_system not in {"qianfan", "creator"}:
            continue
        report_ids.append(str(report.get("report_id") or ""))
        for url in report.get("missing_from_catalog_urls", []) or []:
            if isinstance(url, str) and url:
                missing_urls[source_system].add(url)
        for label in report.get("missing_from_catalog_click_labels", []) or []:
            if isinstance(label, str) and label:
                missing_labels[source_system].add(label)
        for endpoint in report.get("discovered_api_endpoints", []) or []:
            if isinstance(endpoint, str) and endpoint:
                api_counter[source_system][endpoint] += 1

    unknown_endpoints: dict[str, list[dict[str, Any]]] = {"qianfan": [], "creator": []}
    for source_system in ("qianfan", "creator"):
        known_paths = _known_api_paths(source_system)
        for endpoint, seen in api_counter[source_system].most_common(200):
            parsed = urlparse(endpoint)
            path = parsed.path
            if not _is_business_endpoint(endpoint):
                continue
            if known_paths and path in known_paths:
                continue
            classified = classify_endpoint(endpoint, source_system)
            unknown_endpoints[source_system].append(
                {
                    "endpoint": endpoint,
                    "path": path,
                    "seen_in_reports": int(seen),
                    "known": bool(path in known_paths),
                    "decision": classified["decision"],
                    "category": classified["category"],
                    "usage": classified["usage"],
                    "mapped_surface_name": classified["mapped_surface_name"],
                    "integration_status": classified["integration_status"],
                }
            )

    hints: list[dict[str, Any]] = []
    for source_system in ("qianfan", "creator"):
        hints.extend(_candidate_hints_from_urls(source_system, sorted(missing_urls[source_system])))
        hints.extend(_candidate_hints_from_labels(source_system, sorted(missing_labels[source_system])))

    decision_counter: Counter[str] = Counter()
    integration_counter: Counter[str] = Counter()
    total_candidates = 0
    for source_system in ("qianfan", "creator"):
        for item in unknown_endpoints[source_system]:
            decision_counter[str(item.get("decision") or "unknown")] += 1
            integration_counter[str(item.get("integration_status") or "unmapped")] += 1
            total_candidates += 1
    classified_candidates = total_candidates - int(decision_counter.get("unknown", 0) or 0)
    p0p1_total = int(decision_counter.get("promote_p0", 0) or 0) + int(decision_counter.get("promote_p1", 0) or 0)
    p0p1_integrated = 0
    for source_system in ("qianfan", "creator"):
        for item in unknown_endpoints[source_system]:
            if item.get("decision") not in {"promote_p0", "promote_p1"}:
                continue
            if item.get("integration_status") == "integrated_proven":
                p0p1_integrated += 1

    q_known = _known_urls("qianfan")
    c_known = _known_urls("creator")
    status = "green"
    if hints or unknown_endpoints["qianfan"] or unknown_endpoints["creator"]:
        status = "warning"

    report = {
        "schema_version": "1.0.0",
        "object_type": "acquisition_frontier_report",
        "report_id": deterministic_id("frontier", source_filter, utc_now_iso()),
        "created_at": utc_now_iso(),
        "source_filter": source_filter,
        "lookback_reports": int(lookback),
        "discovery_report_ids": [item for item in report_ids if item],
        "qianfan_known_catalog_url_count": len(q_known),
        "creator_known_catalog_url_count": len(c_known),
        "qianfan_missing_catalog_urls": sorted(missing_urls["qianfan"]),
        "creator_missing_catalog_urls": sorted(missing_urls["creator"]),
        "qianfan_missing_click_labels": sorted(missing_labels["qianfan"]),
        "creator_missing_click_labels": sorted(missing_labels["creator"]),
        "qianfan_candidate_api_endpoints": unknown_endpoints["qianfan"],
        "creator_candidate_api_endpoints": unknown_endpoints["creator"],
        "candidate_surface_hints": hints,
        "candidate_counts": {
            "qianfan_missing_urls": len(missing_urls["qianfan"]),
            "creator_missing_urls": len(missing_urls["creator"]),
            "qianfan_missing_labels": len(missing_labels["qianfan"]),
            "creator_missing_labels": len(missing_labels["creator"]),
            "qianfan_candidate_api_endpoints": len(unknown_endpoints["qianfan"]),
            "creator_candidate_api_endpoints": len(unknown_endpoints["creator"]),
            "total_candidates": len(hints) + len(unknown_endpoints["qianfan"]) + len(unknown_endpoints["creator"]),
        },
        "governance_summary": {
            "total_api_candidates": total_candidates,
            "classified_api_candidates": classified_candidates,
            "unknown_api_candidates": int(decision_counter.get("unknown", 0) or 0),
            "decision_counts": dict(decision_counter),
            "integration_counts": dict(integration_counter),
            "p0p1_total": p0p1_total,
            "p0p1_integrated_proven": p0p1_integrated,
        },
        "status": status,
        "source_of_truth": "union of discovery artifacts compared against frozen catalog and known API maps",
        "freshness_policy": {"immutable": True},
        "validator": "revenue_os.foundation.contracts.validate_contract_document",
        "failure_mode": "warning",
    }
    write_artifact("acquisition_frontier_report", report)
    return report
