"""
state_normalizer.py — opencli JSON 输出 → 标准化 user_state
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import DATA_ROOT

CRITICAL_METRICS = [
    "recent_note_median_views", "cover_ctr", "engagement_rate",
    "shop_visit_to_pay_cvr", "recent_note_count_30d",
]


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except Exception:
        return None


def _from_creator_stats(data: dict) -> dict[str, Any]:
    overview = data.get("overview") or data.get("data") or data
    out: dict[str, Any] = {}
    for key, target in [("followers", "follower_count"), ("fans", "follower_count"),
                        ("total_views", "total_views_30d"), ("total_likes", "total_likes_30d")]:
        if overview.get(key) is not None:
            out[target] = overview[key]
    return out


def _from_creator_notes(data: dict) -> dict[str, Any]:
    notes = data.get("notes") or data.get("data") or []
    if not notes:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent = [n for n in notes if (_parse_date(n.get("created_at") or n.get("publish_time")) or cutoff) >= cutoff]
    if not recent:
        recent = notes  # fallback: use all

    views = [float(n["views"]) for n in recent if n.get("views") is not None]
    out: dict[str, Any] = {"recent_note_count_30d": len(recent)}
    if views:
        out["recent_note_median_views"] = statistics.median(views)
        out["recent_note_total_views"]  = sum(views)
    return out


def _from_note_details(details: list[dict]) -> dict[str, Any]:
    ctrs  = [float(d["ctr"])  for d in details if d.get("ctr")  is not None]
    ers   = [float(d["engagement_rate"]) for d in details if d.get("engagement_rate") is not None]
    crs   = [float(d["completion_rate"]) for d in details
             if d.get("completion_rate") is not None and d.get("type") == "video"]
    out: dict[str, Any] = {}
    if ctrs: out["cover_ctr"] = statistics.mean(ctrs)
    if ers:  out["engagement_rate"] = statistics.mean(ers)
    if crs:  out["completion_rate"] = statistics.mean(crs)
    return out


def _load_json(path: Path) -> dict | list | None:
    if path and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def build_user_state(
    brand_profile: dict[str, Any],
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """
    brand_profile (from brand_profile.yaml)  +  data/ directory  →  user_state
    data/ 里查找: creator_stats.json, creator_notes.json, note_details/*.json
    """
    data_dir = data_dir or DATA_ROOT
    state: dict[str, Any] = {
        "role":              brand_profile.get("role", "merchant"),
        "business_model":    brand_profile.get("business_model", ["ecommerce"]),
        "industry":          brand_profile.get("industry", "通用"),
        "stage":             brand_profile.get("stage", "ramp_up"),
        "primary_objective": brand_profile.get("primary_objective", "conversion"),
        "inferred":          brand_profile.get("inferred", {}),
        "metrics":           dict(brand_profile.get("metrics") or {}),
        "data_sources":      {},
    }

    # opencli: creator-stats
    stats = _load_json(data_dir / "creator_stats.json")
    if stats:
        for k, v in _from_creator_stats(stats).items():
            state["metrics"][k] = v
            state["data_sources"][k] = "opencli:creator-stats"

    # opencli: creator-notes
    notes = _load_json(data_dir / "creator_notes.json")
    if notes:
        for k, v in _from_creator_notes(notes).items():
            if k not in state["metrics"] or state["metrics"][k] is None:
                state["metrics"][k] = v
            state["data_sources"][k] = "opencli:creator-notes"

    # opencli: note details (list of dicts or dir of jsons)
    details_dir = data_dir / "note_details"
    if details_dir.exists():
        details = [json.loads(f.read_text(encoding="utf-8"))
                   for f in details_dir.glob("*.json") if f.is_file()]
        for k, v in _from_note_details(details).items():
            if k not in state["metrics"] or state["metrics"][k] is None:
                state["metrics"][k] = v
            state["data_sources"][k] = "opencli:note-detail"

    # weak_metrics: 低于 brand_profile 阈值的指标
    thresholds = brand_profile.get("thresholds", {})
    weak: list[str] = []
    m = state["metrics"]
    for metric, floor_key in [
        ("shop_visit_to_pay_cvr", "shop_visit_to_pay_cvr_low"),
        ("product_click_to_pay_cvr", "product_click_to_pay_cvr_low"),
        ("aov", "aov_low"),
    ]:
        val = m.get(metric)
        floor = thresholds.get(floor_key, 0)
        if val is not None and floor and float(val) < float(floor):
            weak.append(metric)
    state["weak_metrics"] = weak
    state["missing_metrics"] = [k for k in CRITICAL_METRICS if m.get(k) is None]

    return state
