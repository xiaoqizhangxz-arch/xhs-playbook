from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import ANALYSIS_ROOT, BUSINESS_LIBRARY_ROOT
from revenue_os.foundation.io import object_path, read_json, write_json


BRAND_SCRIPT = BUSINESS_LIBRARY_ROOT / "scripts" / "brand_intelligence.py"
BL_RECORDS = BUSINESS_LIBRARY_ROOT / "LeFond_BusinessLibrary_Records_v1.json"


def _load_brand_module():
    spec = importlib.util.spec_from_file_location("revenue_os_brand_intelligence", BRAND_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def build_brand_truth(snapshot_id: str) -> dict[str, Any]:
    module = _load_brand_module()
    records = read_json(BL_RECORDS)
    payload: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "sku_map": getattr(module, "SCOUT_SKU_MAP", {}),
        "bl_insights": getattr(module, "BL_INSIGHTS", {}),
        "records": records.get("records", []),
        "analysis_docs": sorted(str(path) for path in ANALYSIS_ROOT.glob("*.md")),
    }
    write_json(object_path("normalized_brand_truth", snapshot_id), payload)
    return payload
