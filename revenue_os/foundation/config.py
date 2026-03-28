from __future__ import annotations

import os
from pathlib import Path
import yaml


def revenue_os_root() -> Path:
    env = os.environ.get("REVENUE_OS_BASE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


REVENUE_OS_ROOT = revenue_os_root()
KNOWLEDGE_ROOT  = REVENUE_OS_ROOT / "knowledge_base"
RUNTIME_ROOT    = REVENUE_OS_ROOT / "runtime"
DATA_ROOT       = REVENUE_OS_ROOT / "data"

# ── Brand Profile ──────────────────────────────────────────────────────────
_PROFILE_PATH = REVENUE_OS_ROOT / "brand_profile.yaml"

_DEFAULT_PROFILE: dict = {
    "role": "merchant",
    "business_model": ["ecommerce"],
    "industry": "通用",
    "stage": "ramp_up",
    "primary_objective": "conversion",
    "content_start_date": None,
    "thresholds": {
        "shop_visit_to_pay_cvr_low": 0.015,
        "product_click_to_pay_cvr_low": 0.03,
        "aov_low": 0.0,
        "refund_rate_high": 0.15,
        "inquiry_to_pay_cvr_low": 0.20,
        "search_opportunity_ctr": 0.08,
        "min_orders_for_confidence": 10,
        "sample_floor_orders": 5,
        "creator_home_stale_days": 7,
        "creator_note_manager_stale_days": 14,
    },
}


def load_brand_profile() -> dict:
    if _PROFILE_PATH.exists():
        with open(_PROFILE_PATH, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        merged = dict(_DEFAULT_PROFILE)
        merged.update(loaded)
        merged["thresholds"] = {**_DEFAULT_PROFILE["thresholds"], **loaded.get("thresholds", {})}
        return merged
    return dict(_DEFAULT_PROFILE)


def get_thresholds() -> dict:
    return load_brand_profile()["thresholds"]


# ── Convenience shim so old imports still work ──────────────────────────────
def _get(key: str, default=None):
    return load_brand_profile().get("thresholds", {}).get(key, default)

DEFAULT_THRESHOLDS = get_thresholds()   # module-level snapshot (used by stabilizer etc.)

# Legacy constant used by post_feedback.py
LE_FOND_CONTENT_START_DATE = load_brand_profile().get("content_start_date") or "2000-01-01"
