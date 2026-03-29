from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from revenue_os.foundation.config import BUSINESS_LIBRARY_ROOT
from revenue_os.foundation.io import object_path, write_json


QUERY_SCRIPT = BUSINESS_LIBRARY_ROOT / "scripts" / "query_knowledge.py"


def _load_query_module():
    spec = importlib.util.spec_from_file_location("revenue_os_query_knowledge", QUERY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def build_official_rules(snapshot_id: str) -> dict[str, Any]:
    module = _load_query_module()
    query_map = getattr(module, "QUERY_MAP", {})
    payload: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "query_dimensions": query_map,
        "source_file": str(getattr(module, "MERGED", "")),
    }
    write_json(object_path("normalized_official_rules", snapshot_id), payload)
    return payload
